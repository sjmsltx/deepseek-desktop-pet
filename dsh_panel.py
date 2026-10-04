# -*- coding: utf-8 -*-
"""DSH 面板窗口（3.0 · P0 载体）。

定位：桌宠**只做宿主** —— 把 DSH 的界面装进一个窗口，不解析、不注入、不改它的前端。
策略（按顺序尝试，全部失败则明确返回失败原因，由调用方提示用户）：

  1. Edge   `--app=<带令牌地址>`   → 无标签栏/地址栏，最像独立应用（实测可用）
  2. Chrome `--app=<带令牌地址>`   → 同上
  3. 系统默认浏览器打开            → 降级方案（会出现在浏览器标签里）

若服务没在跑：调用 `D:\\dsh\\start-dsh.ps1` 把它拉起来（该脚本会自己读令牌并开浏览器），
再返回结果。全程不读凭据文件、不写 DSH 的任何文件。

对外：open_panel() -> (ok: bool, message: str)
"""
from __future__ import annotations

import ctypes

import os
import subprocess
import sys
import time

import dsh_adapter as ad

BROWSERS = [
    ('Edge', [r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
              r'C:\Program Files\Microsoft\Edge\Application\msedge.exe']),
    ('Chrome', [r'C:\Program Files\Google\Chrome\Application\chrome.exe',
                r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe']),
]

LAUNCHER = os.path.join(ad.DSH_ROOT, 'start-dsh.ps1')

# ⭐ 本模块的日志入口：`ad._log` ✓ —— 但静默护栏的 `_LOG_NAMES` 不认识 `_log` ✗
#    （已请对方补 ✓）；此处用被识别的名字做**同义别名** ✓，跨模块日志也能被判为"已落痕" ✓
_silent_log = ad._log


# ── A7（D1-4）子进程回收：Job Object ✓ ────────────────────────────────
# ⭐ 问题：旧实现只 `Popen` ✗ → 父进程（桌宠）被强杀后，子进程（协作台服务/浏览器）
#    仍在跑 ✗ → 今晚实测留下 **5~7 个孤儿 relay_server** ✗。
# ⭐ 做法：把子进程加入一个 **Job Object** 并设 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` ✓；
#    Job 句柄不显式关闭（随进程存活 ✓）→ 父进程一死 → 句柄关 → ⭐ 系统自动清掉 Job 内全部子进程 ✓
# ⛔ 不依赖子进程自己退出（它可能卡死 ✗）⛔ 不用轮询清理（会漏 + 拖慢关窗 ✗）
_JOB = {'handle': None}
_JOBOBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x0800


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64),
                ('PerJobUserTimeLimit', ctypes.c_int64),
                ('LimitFlags', ctypes.c_uint32),
                ('MinimumWorkingSetSize', ctypes.c_size_t),
                ('MaximumWorkingSetSize', ctypes.c_size_t),
                ('ActiveProcessLimit', ctypes.c_uint32),
                ('Affinity', ctypes.c_size_t),
                ('PriorityClass', ctypes.c_uint32),
                ('SchedulingClass', ctypes.c_uint32)]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [('ReadOperationCount', ctypes.c_uint64),
                ('WriteOperationCount', ctypes.c_uint64),
                ('OtherOperationCount', ctypes.c_uint64),
                ('ReadTransferCount', ctypes.c_uint64),
                ('WriteTransferCount', ctypes.c_uint64),
                ('OtherTransferCount', ctypes.c_uint64)]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION_STRUCT(ctypes.Structure):
    _fields_ = [('BasicLimitInformation', _JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ('IoInfo', _IO_COUNTERS),
                ('ProcessMemoryLimit', ctypes.c_size_t),
                ('JobMemoryLimit', ctypes.c_size_t),
                ('PeakProcessMemoryUsed', ctypes.c_size_t),
                ('PeakJobMemoryUsed', ctypes.c_size_t)]


def _ensure_job():
    """建（或取）本进程的 Job Object；失败返回 None（⭐ 失败降级：仍 spawn ✓ 只不回收 ✗）。"""
    if _JOB['handle'] is not None:
        return _JOB['handle']
    if sys.platform != 'win32':
        return None
    try:
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        h = k32.CreateJobObjectW(None, None)
        if not h:
            raise OSError('CreateJobObject 失败')
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION_STRUCT()
        info.BasicLimitInformation.LimitFlags = (
            _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | _JOB_OBJECT_LIMIT_BREAKAWAY_OK)
        ok = k32.SetInformationJobObject(
            ctypes.c_void_p(h), _JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info), ctypes.sizeof(info))
        if not ok:
            raise OSError('SetInformationJobObject 失败')
        _JOB['handle'] = h
        _JOB['k32'] = k32
        return h
    except Exception as exc:
        _silent_log('Job Object 建立失败（降级为不回收）%r' % (exc,))
        _JOB['handle'] = 0            # 标记已尝试，避免每次重试 ✗
        return None


def _assign_to_job(proc) -> bool:
    """把子进程加入 Job；失败**不阻断**（只记日志 ✓）。"""
    try:
        h = _ensure_job()
        if not h:
            return False
        k32 = _JOB.get('k32')
        if k32 is None:
            k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        handle = int(getattr(proc, '_handle', 0) or 0)
        if not handle:
            return False
        return bool(k32.AssignProcessToJobObject(ctypes.c_void_p(h),
                                                 ctypes.c_void_p(handle)))
    except Exception as exc:
        _silent_log('AssignProcessToJobObject 失败 %r' % (exc,))
        return False


def _spawn(args) -> bool:
    """起一个**分离**子进程并加入 Job ✓（父进程一死即回收 ✓）。"""
    try:
        kwargs = {}
        if sys.platform == 'win32':
            kwargs['creationflags'] = 0x00000008  # DETACHED_PROCESS：不让桌宠被浏览器挂住
        proc = subprocess.Popen(args, close_fds=True, **kwargs)
        _assign_to_job(proc)                  # ⭐ A7：纳入 Job（失败只记日志 ✓ 不阻断 ✓）
        ad._log('_spawn ✓ pid=%s job=%s ｜ %s' % (
            getattr(proc, 'pid', '?'), bool(_JOB.get('handle')), (args or [''])[0][:80]))
        return True
    except Exception as exc:
        _silent_log('_spawn 失败 %r：%r' % (args[:1], exc))
        return False


def open_panel(url: str = None, start_budget: int = 40, poll: float = 0.3,
               allow_start: bool = False, probe_timeout: float = 2.0,
               timeout_ready: int = None):
    """⭐ A5（D1-2）：**启动预算（`start_budget`）与失败判定（`probe_timeout`）拆开** ✗
    —— 旧实现一个 `timeout_ready` 兼两职 ✗ → 45 → 10 → 40 反复改 ✗（血泪史见 EXP.0108 ✓）。

      · `start_budget`：⭐ **等它起来**最多等多久（秒 ✓ 默认 40 ✓ 冷启动实测 ≈19s ✓）
      · `probe_timeout`：⭐ **单次探测**（`is_serving`）最多等多久（秒 ✓ 默认 2.0 ✓）
    `timeout_ready` 保留为**兼容别名** ✗（传了就当 start_budget ✓ 旧调用不破 ✓）。
    """
    if timeout_ready is not None:
        start_budget = timeout_ready          # ⭐ 兼容旧调用 ✓
    """打开 DSH 面板窗口。返回 (ok, 说明文字)。

    ⭐ P0 修复（Owner 2026-10-04 01:53「程序未响应」✓ 微信侧 `WX-…-14` 确诊 ✓）：

      · ⛔ **默认不自动启动** ✗（`allow_start=False`）—— 服务没跑就**立刻返回** ✓
        由调用方**先问用户** ✓（⛔ 不擅自重启用户正在用的服务 ✗）
      · 超时 45s → ⭐ **10s** ✓；轮询 2s → ⭐ **0.3s** ✓（总时长更短 ✓ 且"起来了"更快被发现 ✓）
      · ⚠️ 本函数**可能阻塞** ✗ → ⭐ **调用方必须放到工作线程** ✗
        （此前它被主线程同步调用 ✗ → 最坏 ≈60s → Windows 判"未响应" ✗）
    """
    # 0) 服务没跑
    if not ad.is_serving():
        if not allow_start:
            return False, ('DSH 服务没在运行 ⛔（未自动启动 ✗）—— 🌟 需要的话先启动 DSH，'
                           '或用「启动器」跑一次：%s' % LAUNCHER)
        if os.path.exists(LAUNCHER):
            _spawn(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', LAUNCHER])
            deadline = time.time() + start_budget
            while time.time() < deadline:
                time.sleep(poll)                      # ⭐ 0.3s 粒度 ✓
                if ad.is_serving():
                    break
            if not ad.is_serving():
                return False, '已尝试启动 DSH 服务，但 %d 秒内没起来。请双击 %s 看提示。' % (start_budget, LAUNCHER)
        else:
            return False, 'DSH 服务没在运行，且找不到启动器：%s' % LAUNCHER

    # 1) 取带令牌地址
    url = url or ad.read_token_url()
    if not url:
        return False, '服务在跑，但读不到带令牌的地址（启动日志格式可能变了）—— 请用启动器打开一次。'
    status, size, err = ad.http_status(url)
    if status != 200:
        return False, '带令牌访问失败（%s）—— 请用启动器重新打开一次。' % (err or ('HTTP %s' % status))

    # 2) 优先用 --app 模式（独立窗口，无浏览器外框）
    for name, paths in BROWSERS:
        for exe in paths:
            if os.path.exists(exe):
                if _spawn([exe, '--app=%s' % url, '--window-size=1280,880']):
                    ad._log('已用 %s --app 打开面板' % name)
                    return True, '已用 %s 的应用窗口打开 DSH 面板' % name

    # 3) 降级：系统默认浏览器
    try:
        if sys.platform == 'win32':
            os.startfile(url)  # noqa: S606 - 仅打开 URL
            return True, '已用系统默认浏览器打开（未找到 Edge/Chrome，窗口会带浏览器外框）'
    except Exception as exc:
        return False, '打不开浏览器：%r' % exc

    return False, '没找到可用的浏览器'


if __name__ == '__main__':  # 手工自检：python dsh_panel.py
    ok, msg = open_panel()
    print(('✓ ' if ok else '✗ ') + msg)
