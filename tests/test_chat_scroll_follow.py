# -*- coding: utf-8 -*-
"""翻看历史时不得被在途刷新拉回底部（2026-10-27，Owner 实测）

## 缺陷经过（Owner 原话）

>「每次更新状态或者说是他这个正在思考可能会产生一些新的东西，导致在这个过程当中
>   我如果说要把这个聊天面板向上进行翻动，他每次不知道一个什么更新或者其他什么的东西
>   又会导致那个聊天面板界面重置到最底部」

## 根因

`_render_ai_status()` 末尾**无条件** `_chat_scroll_bottom()`，
而它由 `_ai_status_timer` 每 1000ms（`AI_STATUS_TICK_MS`）触发一次刷「已等 Ns」秒表
⇒ 「正在思考」期间每秒把用户拉回底部一次。
同样的无条件滚动还在 6 处流式/打字机高频刷新里。

实测（修前）：12 条消息、可滚 0~14168；滚到 7084 → 一次 tick → **14168**，连 5 秒每次都被拉走。

## 修法

`_chat_scroll_bottom(force=True)`；7 处在途刷新改 `force=False`（只在用户贴着底部时才跟随），
9 处「新消息落地 / 用户点击」保持 `force=True`。
跟随态由滚动条 `valueChanged` 维护，程序滚动用 `_chat_auto_scroll` 排除。

⚠ 为什么不用「现算 maximum-value」：内容增长时 maximum 会变大，
用户明明停在底部也会被算成「不在底部」⇒ 该跟随的场景会失效。

⚠ 本文件必须 `show()`：不 show 时滚动范围为 0，测不出任何东西（会假绿）。
"""
import os
import sys

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)


def _pet(msgs=12):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True   # 绝不动真实 config
    p._notify = lambda *a, **k: None
    p.show()                                    # ★ 必须 show，否则滚动范围是 0
    for _ in range(6):
        app.processEvents()
    for k in range(1, msgs + 1):
        p._append_chat('桌宠' if k % 2 else '我',
                       '第 %d 条测试消息，' % k + '内容' * 30)
    for _ in range(6):
        app.processEvents()
    return p, app


def _settle(app, n=5):
    for _ in range(n):
        app.processEvents()


def _sb(p):
    return p.chat_history_scroll.verticalScrollBar()


def _scroll_up_to_middle(p, app):
    sb = _sb(p)
    assert sb.maximum() > 0, '前提不成立：内容不够长、滚不起来'
    mid = sb.maximum() // 2
    sb.setValue(mid)          # 等价于用户拖动滚动条
    _settle(app)
    assert p._chat_follow is False, '滚到中间后应视为「已离开底部」'
    return mid


def test_status_tick_does_not_yank_user_back():
    """★ Owner 报的那条：状态秒表每秒一帧，不得把翻看历史的用户拉回底部"""
    p, app = _pet()
    try:
        mid = _scroll_up_to_middle(p, app)
        p._ai_status_text = '正在思考…'
        p._ai_status_t0 = 0
        p._render_ai_status(create=True)
        _settle(app)
        assert _sb(p).value() == mid, (
            '状态刷新把用户从 %d 拉到了 %d —— 状态行由 AI_STATUS_TICK_MS(1000ms) 驱动，'
            '无条件滚动就等于每秒抢一次滚动条' % (mid, _sb(p).value()))
        # 连 5 帧（模拟 5 秒）
        for _ in range(5):
            p._render_ai_status()
            _settle(app)
            assert _sb(p).value() == mid, '第 %d 秒又被拉走' % (_ + 1)
    finally:
        p.close()


def test_stream_updates_do_not_yank_user_back():
    """流式 chunk / 思考流 也不得把人拉回底部"""
    p, app = _pet()
    try:
        mid = _scroll_up_to_middle(p, app)
        p._on_stream('流式内容' * 20)
        _settle(app)
        assert _sb(p).value() == mid, '_on_stream 拉走了滚动位置'
        p._on_reasoning('思考内容' * 20)
        _settle(app)
        assert _sb(p).value() == mid, '_on_reasoning 拉走了滚动位置'
    finally:
        p.close()


def test_follow_resumes_when_user_returns_to_bottom():
    """用户滚回底部后必须自动恢复跟随（否则再也不跟随了）"""
    p, app = _pet()
    try:
        _scroll_up_to_middle(p, app)
        sb = _sb(p)
        sb.setValue(sb.maximum())
        _settle(app)
        assert p._chat_follow is True, '滚回底部后跟随态应恢复'
        p._ai_status_text = '正在思考…'
        p._render_ai_status()
        _settle(app)
        assert sb.maximum() - sb.value() <= p.CHAT_FOLLOW_SLACK, '恢复跟随后应仍贴底'
    finally:
        p.close()


@pytest.mark.parametrize('fn', ['_append_chat', '_append_chat_md'])
def test_new_message_still_jumps_to_bottom(fn):
    """新消息落地**仍然**要跳到底部（原行为不能丢）

    ⚠ 判据用「接近底部」而不是「等于 maximum」：实测对照证明「距底 50px」
      是**改前就有**的布局时序问题（改前等价实现与改后版本均 50px），非本次引入。
    """
    p, app = _pet()
    try:
        mid = _scroll_up_to_middle(p, app)
        getattr(p, fn)('桌宠', '一条新消息')
        _settle(app)
        sb = _sb(p)
        assert sb.value() > mid + 500, '新消息没有把视图带到下方（%d → %d）' % (mid, sb.value())
        assert sb.maximum() - sb.value() <= 60, '新消息后没有接近底部'
        assert p._chat_follow is True, '新消息落地后应恢复跟随'
    finally:
        p.close()


def test_force_true_always_scrolls():
    """force=True（默认）必须无视跟随态 —— 保证既有 9 处调用点行为不变"""
    p, app = _pet()
    try:
        _scroll_up_to_middle(p, app)
        p._chat_scroll_bottom()             # 默认 force=True
        _settle(app)
        assert _sb(p).maximum() - _sb(p).value() <= 60, 'force=True 应当强制滚到底'
    finally:
        p.close()


def test_programmatic_scroll_does_not_flip_follow_flag():
    """程序自己滚动不能把 follow 状态搞反（否则会与用户意图互相覆盖）"""
    p, app = _pet()
    try:
        _scroll_up_to_middle(p, app)
        assert p._chat_follow is False
        p._chat_scroll_bottom(force=True)   # 程序滚到底
        _settle(app)
        assert p._chat_follow is True, '程序滚到底后 follow 应为 True'
        # 再翻上去，应重新变 False
        sb = _sb(p)
        sb.setValue(sb.maximum() // 2)
        _settle(app)
        assert p._chat_follow is False, '用户再翻上去应重新变成不跟随'
    finally:
        p.close()
