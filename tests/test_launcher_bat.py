# -*- coding: utf-8 -*-
"""启动脚本（bat）的两条纪律

背景（2026-10-31）：
1. 评审-268 的教训 —— PYTHONUSERBASE 会把另一个环境的 site-packages 塞进
   sys.path 前面，同一个 import 可能来自别处。268 那次「所有声线固定为一个」
   就是版本取自意外位置，查错方向耗了整轮。启动脚本必须清掉它。
2. 实测 AutoClaw 的 shell 里 %LOCALAPPDATA% 是空的，原来那行会拼成
   `\\Python\\...\\pythonw.exe` 直接找不到 —— 需要 USERPROFILE 兜底。

本文件只锁这两条，不锁 bat 的其他内容（换写法不该让测试变红）。
"""
import io
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

BATS = ('启动桌宠.bat',)


def _read_bat(name):
    """读 bat（UTF-8，统一换行）"""
    p = os.path.join(BASE, name)
    if not os.path.exists(p):
        pytest.skip('没有 %s' % name)
    with io.open(p, 'rb') as f:
        raw = f.read()
    return raw.decode('utf-8-sig', errors='replace').replace('\r\n', '\n')


@pytest.mark.parametrize('name', BATS)
def test_launcher_clears_pythonuserbase(name):
    txt = _read_bat(name)
    # 只认「真正清空」的写法：set "VAR=" 或 set VAR=
    ok = ('set "PYTHONUSERBASE="' in txt) or ('set PYTHONUSERBASE=' in txt)
    assert ok, ('%s 没有清空 PYTHONUSERBASE —— 桌宠会继承外部环境的包路径' % name)


@pytest.mark.parametrize('name', BATS)
def test_launcher_has_userprofile_fallback(name):
    """%LOCALAPPDATA% 为空时要能回退到 %USERPROFILE%"""
    txt = _read_bat(name)
    if '%LOCALAPPDATA%' not in txt:
        pytest.skip('该脚本没用 LOCALAPPDATA，无需兜底')
    assert '%USERPROFILE%' in txt, (
        '%s 只用 %LOCALAPPDATA%，该变量为空时会找不到 python（实测 AutoClaw shell 就是空的）'
        % name)


@pytest.mark.parametrize('name', BATS)
def test_launcher_is_crlf(name):
    """CMD 对 LF-only 的多行 rem 会出错，bat 必须是 CRLF"""
    p = os.path.join(BASE, name)
    if not os.path.exists(p):
        pytest.skip('没有 %s' % name)
    with io.open(p, 'rb') as f:
        raw = f.read()
    lf = raw.count(b'\n')
    crlf = raw.count(b'\r\n')
    assert lf == crlf, '%s 有 %d 处裸 LF（应全 CRLF）' % (name, lf - crlf)


@pytest.mark.parametrize('name', BATS)
def test_launcher_clears_before_start(name):
    """清空 PYTHONUSERBASE 必须发生在 start 之前（顺序错了等于没清）"""
    txt = _read_bat(name)
    i_clear = txt.find('set "PYTHONUSERBASE="')
    if i_clear < 0:
        i_clear = txt.find('set PYTHONUSERBASE=')
    i_start = txt.find('start ')
    assert i_clear >= 0 and i_start >= 0
    assert i_clear < i_start, '清空写在 start 之后，等于没清'
