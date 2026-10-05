# -*- coding: utf-8 -*-
"""协作台宿主窗口（3.0）：在桌宠里**打开协作台**（Owner 2026-10-04 01:48 问"没有入口" ✓）

定位（照 `dsh_panel` 同款 ✓ 复用其浏览器探测／spawn ✓ 不另造 ✗）：
  · ⭐ 本机服务（`127.0.0.1` ✓）—— ⛔ **绝不上网** ✗
  · 优先 Edge/Chrome `--app=`（无外框 ✓）；失败降级系统默认浏览器 ✓
  · ⭐ 服务没跑 → **先问用户**（由调用方问 ✓ 本模块只按 `allow_start` 执行 ✓）
     启动 = `python collab/relay_server.py --log <日志> --port <端口>` ✓（只读面 ✓ 默认不开动作端点 ✓）
  · ⚠️ 本模块**可能阻塞**（等待服务就绪 ✓）→ ⭐ 调用方必须放工作线程 ✗

对外：`open_collab(base_dir, port=8792, allow_start=False, timeout_ready=12, poll=0.3)`
"""
from __future__ import annotations

import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dsh_panel as _hp            # ⭐ 复用其 BROWSERS／_spawn（同款宿主窗口 ✓）

DEFAULT_PORT = 8792                # ⭐ 默认端口（可配 ✓）
HEALTH = '/api/health'             # 只读探针（该端点恒在 ✓ 不需 --enable-actions ✓）


def _probe(port: int, timeout: float = 1.0) -> bool:
    """探协作台是否在跑（只读 ✓ 失败不抛 ✗）。"""
    try:
        import urllib.request
        with urllib.request.urlopen('http://127.0.0.1:%d%s' % (port, HEALTH), timeout=timeout) as fh:
            return fh.status == 200
    except Exception:
        return False



def _pid_alive(pid) -> bool:
    """⭐ `pid` 是否还活着 ✓（⭐ 判不了就**当活着** ✗ ⇒ 宁可保守也不误清 ✓）。"""
    try:
        pid = int(pid or 0)
    except Exception:
        return True
    if pid <= 0:
        return False
    try:
        if os.name == 'nt':
            import subprocess
            out = subprocess.run(['tasklist', '/FI', 'PID eq %d' % pid],
                                 capture_output=True, text=True, timeout=8)
            return str(pid) in (out.stdout or '')
        os.kill(pid, 0)
        return True
    except Exception:
        return True


def _clear_ready(base_dir: str = '') -> bool:
    """⭐ 清掉陈旧就绪标记 ✓（⭐ 只在**判定陈旧**时调用 ✓；⛔ 不静默 ✗ 留痕 ✓）。"""
    try:
        d = base_dir or os.path.dirname(os.path.abspath(__file__))
        p = os.path.join(d, 'collab', '.ready')
        if os.path.isfile(p):
            os.remove(p)
            print('  ℹ️ 已清除陈旧就绪标记：%s' % p)     # ⭐ 落痕 ✓
            return True
    except Exception as exc:
        print('  ℹ️ 清就绪标记失败：%r' % (exc,))          # ⭐ 落痕 ✓
    return False


def ready_info(base_dir: str = '') -> dict:
    """⭐ A4：读服务自写的就绪标记（`<base>/collab/.ready` ✓ 含 pid/port/ts ✓）。"""
    try:
        d = base_dir or os.path.dirname(os.path.abspath(__file__))
        p = os.path.join(d, 'collab', '.ready')
        if not os.path.isfile(p):
            return {}
        import json
        with io.open(p, encoding='utf-8') as fh:
            return json.load(fh) or {}
    except Exception as exc:
        print('  ℹ️ 读就绪标记失败：%r' % (exc,))     # ⭐ 落痕 ✓
        return {}


def is_ready(port: int, base_dir: str = '') -> bool:
    """⭐ A4：**双确认** —— ① 就绪标记在且端口对 ✓ ② 端口真能应答 ✓
    （⛔ 只看标记 ✗ 陈旧会撒谎；⛔ 只探测 ✗ 慢启动期会误判 ✗）"""
    info = ready_info(base_dir)
    if not info or int(info.get('port') or 0) != int(port):
        return False
    # ⭐ ⭐ 采纳微信侧 `WX-…-20261005-45` §二 建议：
    #   ⭐ 硬崩溃/断电后 `finally` **不执行** ✗ ⇒ 标记**必然残留** ✓
    #   ⇒ ⭐ **必须把"写标记的那个进程还活着吗"也纳入判定** ✗（⛔ 只看端口应答 ✗ ——
    #      ⭐ 若端口被**别的**进程占了，就会**误判为就绪** ✓）
    if not _pid_alive(info.get('pid')):
        print('  \u2139\ufe0f 就绪标记显示 pid=%s **已不存在** ⇒ 判定为陈旧 ✓（自动清一次 ✓）'
              % (info.get('pid'),))
        _clear_ready(base_dir)
        return False
    ok = _probe(port)
    if not ok:
        # ⭐ 进程还活着但端口不应答 ⇒ ⭐ 可能在**启动中** ✓ ⇒ ⛔ **不清标记** ✗（⭐ 清了会打断慢启动 ✓）
        print('  \u2139\ufe0f 就绪标记在、进程在，但端口暂不应答 ⇒ 按"未就绪"处理（保留标记 ✓）')
    return ok


def _server_script(base_dir: str) -> str:
    return os.path.join(base_dir, 'collab', 'relay_server.py')


def open_collab(base_dir: str, port: int = DEFAULT_PORT, allow_start: bool = False,
                start_budget: int = 40, poll: float = 0.3, timeout_ready: int = None):
    """打开协作台窗口。返回 `(ok, 说明)` ✓。

    ⛔ `allow_start=False`（默认）：服务没跑就**立刻返回** ✗ 不擅自启动 ✓（由用户确认后再来 ✓）
    """
    if not _probe(port):
        if not allow_start:
            return False, ('协作台没在运行 ⛔（未自动启动 ✗）—— 需要的话点“启动协作台”即可'
                           '（本机 http://127.0.0.1:%d/）' % port)
        script = _server_script(base_dir)
        if not os.path.isfile(script):
            return False, '找不到协作台服务脚本：%s' % script
        log = os.path.join(base_dir, 'collab', 'relay.log')
        try:
            os.makedirs(os.path.dirname(log), exist_ok=True)
        except OSError:
            pass
        # ⭐ 只读面启动（⛔ 不带 --enable-actions ✗）；仅监听 127.0.0.1 ✓
        ok_spawn = _hp._spawn([sys.executable, script, '--log', log, '--port', str(port)])
        if not ok_spawn:
            return False, '启动协作台失败（spawn 被拒）'
        deadline = time.time() + start_budget
        while time.time() < deadline:
            time.sleep(poll)                       # ⭐ 0.3s 粒度 ✓
            if _probe(port):
                break
        if not _probe(port):
            return False, ('已尝试启动协作台，但 %d 秒内没起来 —— 请手动跑一次看提示：'
                           'python collab\\relay_server.py --port %d' % (start_budget, port))
    url = 'http://127.0.0.1:%d/' % port
    for name, paths in _hp.BROWSERS:
        for exe in paths:
            if os.path.exists(exe):
                if _hp._spawn([exe, '--app=%s' % url, '--window-size=1280,880']):
                    return True, '已用 %s 的应用窗口打开协作台（%s）' % (name, url)
    try:
        if sys.platform == 'win32':
            os.startfile(url)                      # noqa: S606 - 仅打开本机 URL ✓
            return True, '已用系统默认浏览器打开协作台（%s）' % url
    except Exception as exc:
        return False, '打不开浏览器：%r' % exc
    return False, '没找到可用的浏览器'


if __name__ == '__main__':                          # 手工自检
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    print(open_collab(base))
