# -*- coding: utf-8 -*-
"""随机演动作的「时机」做成可选（Owner 2026-10-31 新需求）

Owner 原话：
    「我觉得聊天面板没收起来的时候也可以有，因为你这个随机演动作它不是还要冒气泡吗？
      然后用户看见他冒着气泡肯定就把他打开，但是打开之后还是那个待机图片，
      所以说我觉得那个聊天面板有的时候也应该可以看到那个演动作。
      哎呀这样吧你给他做成一个可选项吧，就选择什么时候随机演动作」

Owner 观察的实测依据（本轮量的）：
    面板展开 → 窗口 440x560，立绘区 (90,0,260,320)，聊天面板 (10,320,420,240)
    面板收起 → 窗口 440x340，立绘区 (90,0,260,340)，聊天面板隐藏
    气泡     → y=6，高约 35
    ⇒ **立绘、气泡、聊天面板三者互不重叠**，面板开着时演动作完全看得见。

三档：
    always  一直（默认 —— 响应 Owner 这次的需求）
    hidden  仅面板收起时（上一版的行为）
    off     关闭

本文件锁七件事：
A. 三档常量齐全，默认 always
B. always：面板开着也演
C. hidden：面板开着不演、收起才演
D. off：一律不演
E. 原有的四条安全约束（睡眠/贴边/AI忙/气泡）在三档下都不失效
F. 配置值写错时回落默认（不静默变成别的档）
G. 写错的档位名被拒绝，不静默变成某一档
"""
import os
import sys

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

import desktop_pet as dp  # noqa: E402


def _pet():
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p._append_chat = lambda *a, **k: None
    p._ra_calls = []
    p.random_action = lambda: p._ra_calls.append(1)
    return p


def _panel(p, visible):
    """visible=True 展开面板；False 收起"""
    if visible:
        p.chat_panel.show()
    else:
        p.chat_panel.hide()
    _app.processEvents()


# ---------- A. 三档 ----------
def test_three_modes_exist():
    assert set(dp.PetWidget.RANDOM_ACTION_MODES) == {'always', 'hidden', 'off'}, \
        '时机档位应有 always/hidden/off，实际 %r' % (dp.PetWidget.RANDOM_ACTION_MODES,)


def test_default_is_always():
    assert dp.PetWidget.RANDOM_ACTION_DEFAULT == 'always', \
        '默认应为 always（Owner 这次要的就是「面板开着也能看到」）'


def test_pet_defaults_to_always():
    p = _pet()
    assert p.random_action_when == 'always', '实例默认档应为 always，实际 %r' % p.random_action_when


# ---------- B. always ----------
def test_always_fires_with_panel_open():
    p = _pet()
    p.random_action_when = 'always'
    _panel(p, True)
    p._random_action_tick()
    assert len(p._ra_calls) == 1, 'always 档下面板展开时也该演'


def test_always_fires_with_panel_closed():
    p = _pet()
    p.random_action_when = 'always'
    _panel(p, False)
    p._random_action_tick()
    assert len(p._ra_calls) == 1


# ---------- C. hidden ----------
def test_hidden_skips_when_panel_open():
    p = _pet()
    p.random_action_when = 'hidden'
    _panel(p, True)
    p._random_action_tick()
    assert not p._ra_calls, 'hidden 档下面板展开时不该演'


def test_hidden_fires_when_panel_closed():
    p = _pet()
    p.random_action_when = 'hidden'
    _panel(p, False)
    p._random_action_tick()
    assert len(p._ra_calls) == 1


# ---------- D. off ----------
def test_off_never_fires():
    p = _pet()
    p.random_action_when = 'off'
    for vis in (True, False):
        _panel(p, vis)
        p._random_action_tick()
    assert not p._ra_calls, 'off 档不该演'


def test_off_does_not_start_timer():
    p = _pet()
    p.random_action_when = 'off'
    p._start_random_action_timer()
    assert not p._random_action_timer.isActive(), 'off 档不该起定时器'


# ---------- E. 安全约束不失效 ----------
@pytest.mark.parametrize('mode', ['always', 'hidden'])
def test_sleeping_blocks_in_both_modes(mode):
    p = _pet()
    p.random_action_when = mode
    p.sleeping = True
    _panel(p, False)
    p._random_action_tick()
    assert not p._ra_calls, '%s 档下睡眠仍不该演' % mode


@pytest.mark.parametrize('mode', ['always', 'hidden'])
def test_docked_blocks_in_both_modes(mode):
    p = _pet()
    p.random_action_when = mode
    # 2026-11-01：_edge_docked 是死标志（真实代码从不为真，已删）。
    # 改走真实进入贴边的路径 —— 否则测的是一个现实中不存在的状态（假绿）。
    p._edge_side = 'left'
    _panel(p, False)
    p._random_action_tick()
    assert not p._ra_calls, '%s 档下贴边仍不该演' % mode


@pytest.mark.parametrize('mode', ['always', 'hidden'])
def test_ai_busy_blocks_in_both_modes(mode):
    p = _pet()
    p.random_action_when = mode
    p._ai_busy = True
    _panel(p, False)
    p._random_action_tick()
    assert not p._ra_calls, '%s 档下 AI 忙仍不该演' % mode


# ---------- F. 配置值校验 ----------
@pytest.mark.parametrize('val,want', [
    ('always', 'always'),
    (' HIDDEN ', 'hidden'),
    ('off', 'off'),
    ('whatevr', 'always'),      # 写错 → 回落默认
    ('', 'always'),
    (None, 'always'),
    (True, 'always'),           # 旧 bool 已不兼容，会回落默认（不崩）
    (False, 'always'),
])
def test_normalize_mode(val, want):
    """配置值规整：合法照用，非法回落默认

    ⚠ 旧 bool（True/False）不再做语义迁移 ——
      那个键（random_action_when_hidden）只活了约 1 小时且从未落盘，
      为它保留分支会产生一条死配置 + 一段零调用代码。
      这里只保证「不崩、回落默认」，不保证「False 等于关」。
    """
    got = dp.PetWidget._normalize_random_action_mode(val)
    assert got == want, '%r 应规整成 %r，实际 %r' % (val, want, got)


# ---------- G. 写错档位名 ----------
def test_bad_mode_keeps_previous():
    p = _pet()
    p.random_action_when = 'hidden'
    ok = p._set_random_action('whatevr')
    assert ok is False, '写错的档位名应返回 False'
    assert p.random_action_when == 'hidden', '写错时不该改档位'
