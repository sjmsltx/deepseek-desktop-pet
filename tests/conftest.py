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
