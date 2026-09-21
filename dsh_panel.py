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


def _spawn(args) -> bool:
    try:
        kwargs = {}
        if sys.platform == 'win32':
            kwargs['creationflags'] = 0x00000008  # DETACHED_PROCESS：不让桌宠被浏览器挂住
        subprocess.Popen(args, close_fds=True, **kwargs)
        return True
    except Exception as exc:
        ad._log('_spawn 失败 %r：%r' % (args[:1], exc))
        return False


def open_panel(url: str = None, timeout_ready: int = 45):
    """打开 DSH 面板窗口。返回 (ok, 说明文字)。"""
    # 0) 服务没跑 → 先用启动器拉起来（启动器会写日志、读令牌、开浏览器）
    if not ad.is_serving():
        if os.path.exists(LAUNCHER):
            _spawn(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', LAUNCHER])
            deadline = time.time() + timeout_ready
            while time.time() < deadline:
                time.sleep(2)
                if ad.is_serving():
                    break
            if not ad.is_serving():
                return False, '已尝试启动 DSH 服务，但 %d 秒内没起来。请双击 %s 看提示。' % (timeout_ready, LAUNCHER)
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
