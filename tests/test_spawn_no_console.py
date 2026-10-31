# -*- coding: utf-8 -*-
"""起子进程的护栏：本程序是**无控制台**的 GUI，不能让子进程弹终端窗口。

⛔ 这条为什么存在（2026-10-31，Owner 实测「右键桌宠弹终端窗口」）：
   打包配置 `tools/DeepSeekPet.spec:96` 是 `console=False`。
   Windows 上无控制台的进程调 `subprocess.run([...])` 时，若不带
   `creationflags=CREATE_NO_WINDOW`，子进程会**新建控制台窗口并显示出来**
   ⇒ 用户右键桌宠时看到黑框弹出、菜单被拖住。

   实测（pythonw 下用 EnumWindows 扫 ConsoleWindowClass / PseudoConsoleWindow）：
     裸 subprocess        → 出现 PseudoConsoleWindow，pid 正是子进程
     带 CREATE_NO_WINDOW  → 无新窗口

   ⛔ 这个缺陷**跑测试看不出来**（测试进程自己有控制台，子进程继承，不弹窗），
      只有打包后用户才遇到。所以必须用结构断言钉住 —— 只测行为测不到它。
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import platform_layer as pl  # noqa: E402

CREATE_NO_WINDOW = 0x08000000


def test_safe_spawn_injects_create_no_window(monkeypatch):
    """`safe_spawn` 必须给子进程带上 CREATE_NO_WINDOW"""
    captured = {}

    def fake_run(argv, **kw):
        captured['kw'] = kw
        return 'ok'

    monkeypatch.setattr(pl.subprocess, 'run', fake_run)
    pl.safe_spawn(['powershell', '-NoProfile', '-Command', 'echo hi'],
                  capture_output=True, text=True)
    flags = captured['kw'].get('creationflags')
    assert flags is not None, 'creationflags 没传 —— 打包后会弹终端窗口'
    assert flags & CREATE_NO_WINDOW, '缺 CREATE_NO_WINDOW（实际 %r）' % (flags,)


def test_safe_popen_injects_create_no_window(monkeypatch):
    """`safe_popen` 同样要带"""
    captured = {}

    def fake_popen(argv, **kw):
        captured['kw'] = kw
        return 'proc'

    monkeypatch.setattr(pl.subprocess, 'Popen', fake_popen)
    pl.safe_popen(['powershell', '-NoProfile', '-Command', 'echo hi'])
    flags = captured['kw'].get('creationflags')
    assert flags is not None and (flags & CREATE_NO_WINDOW), \
        'Popen 路径缺 CREATE_NO_WINDOW（实际 %r）' % (flags,)


def test_no_window_keeps_caller_flags(monkeypatch):
    """调用方自己传的 creationflags 不许被覆盖，只能 OR 上去"""
    captured = {}

    def fake_run(argv, **kw):
        captured['kw'] = kw
        return 'ok'

    monkeypatch.setattr(pl.subprocess, 'run', fake_run)
    other = 0x00000200                     # CREATE_NEW_PROCESS_GROUP
    pl.safe_spawn(['powershell', '-Command', 'x'], creationflags=other)
    flags = captured['kw']['creationflags']
    assert flags & CREATE_NO_WINDOW, '自己的 flag 被覆盖了'
    assert flags & other, '调用方的 flag 丢了（实际 %r）' % (flags,)


def test_installed_cache_reduces_ui_thread_wait(monkeypatch):
    """`installed()` 命中缓存时必须是微秒级（右键菜单在 UI 线程调它）

    ⛔ 判据必须能证伪 —— 第一版写错了：
      只清空 `installed()` 的缓存还不够，因为去掉它之后 `resolve_root()` 仍会命中
      30 秒的 `_DISCOVERY_CACHE` ⇒ 照样是微秒级 ⇒ **测不出区别**（实测：回退态仍绿）。
      ⇒ 这里把 `_DISCOVERY_CACHE` 也换掉：
         有 installed 缓存 → 根本不碰 discover → 快
         没有 installed 缓存 → 每轮都要重新扫进程（实测 0.28~0.30 秒）→ 慢
    """
    import time

    import dsh_adapter as ad
    ad.installed(force=True)                        # 先填 installed 缓存
    monkeypatch.setattr(ad, '_DISCOVERY_CACHE', {'ts': 0.0, 'data': None})
    t0 = time.time()
    for _ in range(20):
        # 每轮都把 discover 缓存清掉：否则第一次算完就命中缓存，
        # 20 轮平均被摊薄成 ~15 毫秒，判据抓不到「installed 缓存缺失」。
        ad._DISCOVERY_CACHE.update({'ts': 0.0, 'data': None})
        ad.installed()
    avg = (time.time() - t0) / 20
    assert avg < 0.01, (
        'installed() 命缓存仍要 %.1f 毫秒 —— 说明结果缓存没生效，'
        '右键菜单（UI 线程）会卡' % (avg * 1000,))
