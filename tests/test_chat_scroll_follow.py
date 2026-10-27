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
def test_new_message_keeps_following_when_at_bottom(fn):
    """贴底时新消息**仍然**跟到新底部（原行为保住；精确贴底，不是差 50px）

    ⚠ 2026-10-27 **语义变更说明**（不是放宽断言）：
      这条原名 `test_new_message_still_jumps_to_bottom`，断言「**无论用户在哪**，
      新消息都要把视图带到下方」。
      本次新需求是「用户正在翻历史时**不打扰**，改为『↓ N 条新消息』提示」，
      与旧断言直接冲突 ⇒ 按新语义改为测「**贴底时**跟到底」。

      行为矩阵（两条测试合起来覆盖完整）：
          贴底   + 新消息 → 跟到底、无提示     ← 本条
          翻历史 + 新消息 → 不动、亮提示条     ← test_quiet_when_user_is_reading_history

      这不是放宽：若连「贴底时」都不跟随了，那才是真回归，本条会红。
    """
    p, app = _pet()
    try:
        sb = _sb(p)
        sb.setValue(sb.maximum())          # 先确保贴底
        _settle(app)
        assert p._chat_follow is True, '前提：应当处于跟随状态'
        getattr(p, fn)('桌宠', '一条新消息')
        _settle(app)
        assert sb.maximum() - sb.value() == 0, (
            '贴底时新消息后距底 %d px（应为 0）—— 内容变高后没有跟到新底部'
            % (sb.maximum() - sb.value()))
        assert p._chat_follow is True, '跟随态应保持'
        assert p.chat_new_btn.isVisible() is False, '贴底时不该亮提示条'
    finally:
        p.close()


def test_force_true_always_scrolls():
    """force=True（默认）必须无视跟随态 —— 保证既有 9 处调用点行为不变"""
    p, app = _pet()
    try:
        _scroll_up_to_middle(p, app)
        p._chat_scroll_bottom()             # 默认 force=True
        _settle(app)
        assert _sb(p).maximum() - _sb(p).value() == 0, 'force=True 后应精确贴底'
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


# ---------------- 「↓ N 条新消息」提示条（2026-10-27） ----------------

def test_quiet_when_user_is_reading_history():
    """★ 核心：用户翻历史时，新消息**不得**把他拽回底部，只亮提示条"""
    p, app = _pet()
    try:
        mid = _scroll_up_to_middle(p, app)
        assert p.chat_new_btn.isVisible() is False, '一开始不该有提示条'
        p._append_chat('桌宠', '第一条新消息')
        _settle(app)
        assert _sb(p).value() == mid, '新消息把正在看历史的用户拽走了'
        assert p.chat_new_btn.isVisible() is True, '应当亮出提示条'
        assert '新消息' in p.chat_new_btn.text()
        # 第二条：位置仍不动，文案改成带条数
        p._append_chat_md('桌宠', '第二条新消息')
        _settle(app)
        assert _sb(p).value() == mid, '第二条又把用户拽走了'
        assert '2' in p.chat_new_btn.text(), '多条时应显示条数'
    finally:
        p.close()


def test_click_hint_jumps_to_bottom_and_clears():
    """点提示条 → 跳到底 + 清零 + 隐藏"""
    p, app = _pet()
    try:
        _scroll_up_to_middle(p, app)
        p._append_chat('桌宠', '新消息')
        _settle(app)
        assert p.chat_new_btn.isVisible() is True
        p._jump_to_latest()          # 等价于点提示条
        _settle(app)
        assert _sb(p).maximum() - _sb(p).value() == 0, '点击后应当贴底'
        assert p.chat_new_btn.isVisible() is False, '点击后提示条应隐藏'
        assert p._pending_new_msgs == 0, '点击后计数应清零'
    finally:
        p.close()


def test_scrolling_back_by_user_clears_hint():
    """用户自己滚回底部 → 提示条自动消失（不用点）"""
    p, app = _pet()
    try:
        _scroll_up_to_middle(p, app)
        p._append_chat('桌宠', '新消息')
        _settle(app)
        assert p._pending_new_msgs == 1
        sb = _sb(p)
        sb.setValue(sb.maximum())
        _settle(app)
        assert p.chat_new_btn.isVisible() is False, '用户已回到底部，提示条应自动消失'
        assert p._pending_new_msgs == 0
    finally:
        p.close()


def test_no_hint_when_already_at_bottom():
    """贴底时来新消息：正常跟随且**不显示**提示条（别在大平时也弹提示）"""
    p, app = _pet()
    try:
        sb = _sb(p)
        sb.setValue(sb.maximum())
        _settle(app)
        p._append_chat('桌宠', '新消息')
        _settle(app)
        assert sb.maximum() - sb.value() == 0, '贴底时应当跟上'
        assert p.chat_new_btn.isVisible() is False, '贴底时不该有提示条'
        assert p._pending_new_msgs == 0
    finally:
        p.close()


def test_clear_history_resets_hint():
    """清空历史 → 提示条与计数归零（否则会残留一个指向空列表的提示）"""
    p, app = _pet()
    try:
        _scroll_up_to_middle(p, app)
        p._append_chat('桌宠', '未读一条')
        _settle(app)
        assert p._pending_new_msgs == 1
        p._clear_chat_history()
        _settle(app)
        assert p.chat_new_btn.isVisible() is False
        assert p._pending_new_msgs == 0
    finally:
        p.close()


def test_hint_widget_is_in_chat_panel():
    """提示条必须真的挂在聊天面板上（否则 show() 也看不见）"""
    p, app = _pet()
    try:
        from PySide6.QtWidgets import QLabel
        labs = p.chat_panel.findChildren(QLabel)
        assert p.chat_new_btn in labs, '提示条不在聊天面板里 ⇒ 永远显示不出来'
        assert p.chat_new_btn.text() == '' or p.chat_new_btn.isVisible() is False
    finally:
        p.close()
