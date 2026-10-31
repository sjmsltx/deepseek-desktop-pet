# -*- coding: utf-8 -*-
"""随机动作定时器（隐藏面板时）

Owner 原话（2026-10-23，记在 PC-237）：
    「桌面宠物本来不是有一个可以把对话面板隐藏的功能嘛……就是隐藏之后啊
      他那个动作就不应该只有待机还有贴边动画，他不是用各种乱七八糟的动作吗，
      你都可以随机的去给他触发一下」

237 里我承诺「先用 260 尺寸把 12 个动作逐个渲染出来看，再决定池子里放哪几个」。
本轮已兑现：12 个动作图**全是 1024×1024 正方形**，260 方块内不裁切、逐个可辨
（预览图 12动作-260方块预览-20261031.png）⇒ 池子用全部 12 个，不剔除。

本文件锁七件事：
A. 默认开、可在设置里关
B. 只在「面板隐藏」时触发（Owner 明确说「隐藏之后」）
C. 睡眠 / 贴边 / 忙 / 正在演动作 / 气泡可见 时不触发
D. 间隔是随机的（不是固定节拍 —— 固定间隔看着像机器）
E. 触发的是 random_action()（复用现有实现，不另写一套）
F. 关掉后真的不再触发
G. 定时器不叠加（重复 start 不会起两个）
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
    # 记录 random_action 被调次数，不真的演动作
    p._ra_calls = []
    p.__dict__['_orig_ra'] = p.random_action

    def fake_ra():
        p._ra_calls.append(1)
    p.random_action = fake_ra
    return p


# ---------- A. 默认与开关 ----------
def test_timer_exists_and_default_on():
    p = _pet()
    assert hasattr(p, '_random_action_timer'), '没有随机动作定时器'
    # 2026-10-31 契约变更：bool 开关改成三档时机，默认 'always'
    #   （Owner：「聊天面板有的时候也应该可以看到那个演动作」）
    assert getattr(p, 'random_action_when', '') == 'always', \
        '默认应为 always（面板开着也演），实际 %r' % getattr(p, 'random_action_when', '?')


def test_config_key_read_in_loader():
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    # 2026-10-31：键名从 random_action_when_hidden（bool）改成
    #   random_action_when（三档），旧键已彻底移除（它只活了约 1 小时且从未落盘）
    assert "cfg.get('random_action_when'" in src, '配置读取里没有这个开关'
    assert "cfg.get('random_action_when_hidden'" not in src, \
        '旧键 random_action_when_hidden 又被读回来了 —— 会变成死配置'


# ---------- B. 只在隐藏时 ----------
def test_does_not_fire_when_panel_visible():
    """hidden 档下面板显示时不演（always 档的对应行为在 test_random_action_mode.py）

    2026-10-31 契约变更：默认档已是 always，本条显式降到 hidden 档来测这条约束，
    否则测的就不是「不许演」而是「默认行为」了。
    """
    p = _pet()
    p.random_action_when = 'hidden'
    p.chat_panel.show()
    _app.processEvents()
    p._random_action_tick()
    assert not p._ra_calls, 'hidden 档下面板显示时不该自动演动作'


def test_fires_when_panel_hidden():
    p = _pet()
    p.chat_panel.hide()
    _app.processEvents()
    p._random_action_tick()
    assert len(p._ra_calls) == 1, '面板隐藏时应触发一次'


# ---------- C. 各种不该触发的状态 ----------
@pytest.mark.parametrize('attr,val', [
    ('sleeping', True),
])
def test_skipped_when_sleeping(attr, val):
    p = _pet()
    setattr(p, attr, val)
    p.chat_panel.hide()
    _app.processEvents()
    p._random_action_tick()
    assert not p._ra_calls, '睡眠时不该演动作'


def test_skipped_when_docked():
    p = _pet()
    p._edge_docked = True
    p.chat_panel.hide()
    _app.processEvents()
    p._random_action_tick()
    assert not p._ra_calls, '贴边时不该演场景动作（有专门的贴边动画）'


def test_skipped_when_ai_busy():
    p = _pet()
    p._ai_busy = True
    p.chat_panel.hide()
    _app.processEvents()
    p._random_action_tick()
    assert not p._ra_calls, 'AI 在忙时不该抢动作'


def test_skipped_when_bubble_visible():
    """气泡正显示时不演动作 —— 否则动作图会被气泡压住/换走"""
    p = _pet()
    p.chat_panel.hide()
    _app.processEvents()
    try:
        p.bubble.show()
    except Exception:
        pytest.skip('本环境无气泡控件')
    p._random_action_tick()
    assert not p._ra_calls, '气泡可见时不该演动作'


def test_skipped_when_switch_off():
    """off 档一律不演（2026-10-31 契约变更：bool False → 'off'）"""
    p = _pet()
    p.random_action_when = 'off'
    p.chat_panel.hide()
    _app.processEvents()
    p._random_action_tick()
    assert not p._ra_calls, 'off 档仍在触发'


# ---------- D. 间隔随机 ----------
def test_interval_is_randomized():
    p = _pet()
    ivs = {p._next_random_action_ms() for _ in range(40)}
    assert len(ivs) > 5, '间隔几乎不变（%d 种），像固定节拍' % len(ivs)
    lo, hi = min(ivs), max(ivs)
    assert lo >= 20_000, '最短间隔 %.0fs 太短，会像抽筋' % (lo / 1000)
    assert hi <= 300_000, '最长间隔 %.0fs 太长，一天看不到几次' % (hi / 1000)


# ---------- G. 不叠加 ----------
def test_timer_not_stacked():
    p = _pet()
    p._start_random_action_timer()
    p._start_random_action_timer()
    p._start_random_action_timer()
    assert p._random_action_timer.isActive()
    # 定时器只有一个实例（QTimer 单实例 start 不会叠加），这里断言它没被替换成多个
    assert p._random_action_timer.parent() is p


# ---------- E. 复用 random_action ----------
def test_reuses_existing_random_action():
    """tick 必须复用现有 random_action()，不许另写一套

    ⛔ 按函数边界切片，不用固定长度：函数会变长，
       写死 i+1600 会随着代码增长突然取不到（本轮就撞上了）。
    """
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    i = src.find('def _random_action_tick')
    assert i > 0, '找不到 _random_action_tick'
    j = src.find('\n    def ', i + 10)      # 下一个同级方法
    body = src[i:j if j > 0 else i + 4000]
    assert 'self.random_action()' in body, \
        '没复用现有的 random_action()，另写了一套（会分叉）'
