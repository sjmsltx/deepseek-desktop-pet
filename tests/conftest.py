# -*- coding: utf-8 -*-
"""测试统一环境（v6.70）：离屏平台 + 真实字体目录。

**为什么必须显式设字体目录**：离屏平台默认可能加载 **0 个字体** —— 此时所有文字
零宽零高，于是任何"内容装得下 / 按像素省略 / 高度够不够"的断言都会**假通过**。

2026-09-20 实测：
  · 不设字体目录 → `tests/test_stats_window.py` 6 项全绿；
  · 设上之后 → 立刻暴露「最胖内容（3 个来源 + 超长模型名 + 余额行）装不下窗口」的真问题
    （与真机上那条"拖不动 / 卡死"反馈同源）。

只在本机存在该目录时设置（Windows）；其它平台交给 Qt 自己找系统字体。
"""
import os

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

_FONTDIR = r'C:\Windows\Fonts'
if os.path.isdir(_FONTDIR):
    os.environ.setdefault('QT_QPA_FONTDIR', _FONTDIR)


@pytest.fixture(scope='session', autouse=True)
def _cleanup_office_orphans():
    """会话结束后清理**无窗口**的办公进程（COM 残留）。

    背景（HANDOFF 坑 #8）：office_doc 会真的启 WPS/Office（隐藏窗口），用完应 Quit；
    但异常路径 / 子进程被强杀时会留下孤儿进程（2026-09-20 实测残留 3 个 wps）。
    只杀 MainWindowHandle=0 的（无窗口）—— 用户正在用的 WPS 一定有窗口，不会误伤。
    """
    yield
    try:
        import subprocess
        ps = ("Get-Process wps,excel,winword,powerpnt,et,wpp -ErrorAction SilentlyContinue | "
              "Where-Object { $_.MainWindowHandle -eq 0 } | "
              "Stop-Process -Force -ErrorAction SilentlyContinue")
        subprocess.run(['powershell', '-NoProfile', '-Command', ps], capture_output=True,
                       timeout=60, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except Exception:
        pass


@pytest.fixture(scope='session', autouse=True)
def _isolate_config_file(tmp_path_factory):
    """把 config.json 指到临时目录 —— 测试**不得**改动 Owner 的真实配置

    ⛔ 为什么必须是 **session 级**而不是 function 级（2026-10-25 实测）：
      function 级会在每个测试结束时恢复真实路径，而 session 收尾阶段
      （Qt 对象析构、deleteLater 队列处理）仍有对象往 config.json 写窗口位置。
      实测：跑全量前 x=1353 y=290 → 跑完 x=1365 y=200；
      而给每个测试挂"前后哈希对比"的监控一次都没抓到 ⇒ 写入发生在所有
      fixture teardown 之后。只有把整个 session 都隔离开才真正挡住。

    需要自己 config 的测试，继续用 function 级 monkeypatch(dp, 'CONFIG_PATH', ...)
    覆盖即可 —— 优先级更高；teardown 后回到这里的临时文件，仍碰不到真实配置。

    ⚠ 已知边界：`MODEL_REGISTRY = ModelRegistry(MODELS_PATH, CONFIG_PATH)` 是模块加载时
      求值，patch 管不到它。若将来那里开始写盘，需要另行处理（日志已记）。
    """
    try:
        import desktop_pet as _dp
    except Exception:
        yield                       # 该会话不需要主程序
        return
    real = _dp.CONFIG_PATH
    tmp = tmp_path_factory.mktemp('cfg') / 'config.json'
    _dp.CONFIG_PATH = str(tmp)
    try:
        yield
    finally:
        _dp.CONFIG_PATH = real
