# -*- coding: utf-8 -*-
"""_office_child.py — 子进程入口：在**独立进程**里跑某个 `_impl_*` 用例。

为什么需要它：真正调用 COM（WPS/Office）的路径在 RPC 异常时会抛 **Windows 致命异常**
（0x800706ba / 0x800706be），Python 的 try/except **抓不住** —— 在主进程里会把整个
pytest 进程打崩（2026-09-20 实测：`test_report_roundtrip` 把进程带走）。隔离到子进程后，
崩也只崩子进程，主进程能如实报"这一条失败"。

用法：python tests/_office_child.py _impl_report_roundtrip
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
sys.path.insert(0, BASE)
sys.path.insert(0, HERE)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
_FONTDIR = r'C:\Windows\Fonts'
if os.path.isdir(_FONTDIR):
    os.environ.setdefault('QT_QPA_FONTDIR', _FONTDIR)

import test_office_skill as t   # noqa: E402  （同目录导入）

name = sys.argv[1]
fn = getattr(t, name)
fn()
print('CHILD_OK')
