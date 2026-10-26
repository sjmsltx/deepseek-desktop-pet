# -*- coding: utf-8 -*-
"""贴边 → 拖出后，聊天输入框不得塌成一行（2026-10-26，Owner 实测）

## 缺陷经过（Owner 原话）

> 「输入一个文本然后它现在这个显示范围确实扩大了，但是我现在把这个桌面宠物给它拖到边上
>   变成贴边状态然后再给它拖出来，那个显示框就变成只有一行的了，然后进行显示框输入操作
>   又可以变回来，但是这显然有问题」

## 根因

`_exit_dock_to_free` 与 `_popup_from_dock` 在恢复聊天面板时都写了
`self.chat_input.setFixedHeight(34)`（34 = 单行高度，**硬编码**）。
而 `_auto_resize_input` 只挂在 `document().contentsChanged` 上
⇒ 内容没变就不会重算 ⇒ 高度停在一行，直到用户再打字（正好对上「再输入又变回来」）。

## 实测（修前 / 修后）

    单行 34px ; 5 行 88px
    贴边 → 拖出 : 88 → 34（修前塌）     /  88 → 88（修后保持）
    贴边 → 弹出 : 88 → 34（修前塌）     /  88 → 88（修后保持）

⚠ 本文件必须 `show()`：不 show 时 `chat_panel.isVisible()` 恒 False，
  `_enter_dock` 里 `if self.chat_panel.isVisible():` 不成立 ⇒ 恢复块整段不执行，
  测出来会是「假绿」。另外未 show 时 `document().size().height()` 也算不出真实高度。
"""
import os
import sys

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

MULTI = '第一行\n第二行\n第三行\n第四行\n第五行'
LONG = '\n'.join('第%d行内容' % i for i in range(1, 21))   # 20 行，必然触顶


def _pet():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True   # 绝不动真实 config
    p._notify = lambda *a, **k: None
    p.show()                                    # ★ 必须 show，否则测出假绿
    app.processEvents()
    return p, app


def _settle(app, n=4):
    for _ in range(n):
        app.processEvents()


def _fill(p, app, text):
    p.chat_input.setPlainText(text)
    _settle(app)
    p._auto_resize_input()
    _settle(app)
    return p.chat_input.height()


def _dock_and(p, app, leave_by):
    """填好多行 → 贴边 → 按指定方式离开贴边，返回 (离开前高, 离开后高)"""
    h_before = _fill(p, app, MULTI)
    p._enter_dock('left', 200)
    _settle(app)
    assert p.chat_panel.isVisible() is False, '贴边应当隐藏聊天面板（前提不成立，本测试无意义）'
    assert p._chat_hidden_for_dock is True
    if leave_by == 'drag':
        p._exit_dock_to_free()
    else:
        p._popup_from_dock()
    _settle(app)
    return h_before, p.chat_input.height()


@pytest.mark.parametrize('leave_by', ['drag', 'popup'])
def test_multiline_height_survives_dock_roundtrip(leave_by):
    """多行内容贴边往返后，输入框高度必须保持不变（不许塌成一行）"""
    p, app = _pet()
    try:
        before, after = _dock_and(p, app, leave_by)
        assert before > 34, '前提：多行内容应当先让输入框变高（否则测不出塌陷）'
        assert p.chat_input.toPlainText() == MULTI, '内容不该变'
        assert after == before, (
            '贴边→%s 后输入框从 %dpx 塌成 %dpx —— '
            '内容没变却把高度写死回单行（_exit_dock_to_free/_popup_from_dock 的旧缺陷）'
            % ('拖出' if leave_by == 'drag' else '弹出', before, after))
    finally:
        p.close()


@pytest.mark.parametrize('leave_by', ['drag', 'popup'])
def test_empty_input_stays_single_line(leave_by):
    """空输入框往返后仍是单行（不能反过来被撑高）"""
    p, app = _pet()
    try:
        p.chat_input.setPlainText('')
        _settle(app)
        p._auto_resize_input()
        _settle(app)
        base = p.chat_input.height()
        p._enter_dock('left', 200)
        _settle(app)
        if leave_by == 'drag':
            p._exit_dock_to_free()
        else:
            p._popup_from_dock()
        _settle(app)
        assert p.chat_input.height() == base == 34
    finally:
        p.close()


@pytest.mark.parametrize('leave_by', ['drag', 'popup'])
def test_tall_input_keeps_cap(leave_by):
    """超长内容往返后仍是上限 120（不许超过，也不许塌）"""
    p, app = _pet()
    try:
        p.chat_input.setPlainText(LONG)
        _settle(app)
        p._auto_resize_input()
        _settle(app)
        assert p.chat_input.height() == 120, '20 行应当触到 120 上限'
        p._enter_dock('left', 200)
        _settle(app)
        if leave_by == 'drag':
            p._exit_dock_to_free()
        else:
            p._popup_from_dock()
        _settle(app)
        assert p.chat_input.height() == 120
    finally:
        p.close()


def test_window_tall_enough_after_roundtrip():
    """拖出后窗口高度要装得下聊天面板（防输入框被窗口挤压）"""
    p, app = _pet()
    try:
        p.chat_input.setPlainText(MULTI)
        _settle(app)
        p._auto_resize_input()
        _settle(app)
        p._enter_dock('left', 200)
        _settle(app)
        p._exit_dock_to_free()
        _settle(app)
        need = p.chat_panel.sizeHint().height()
        assert p.height() >= need, '窗口 %d px 装不下聊天面板 %d px' % (p.height(), need)
    finally:
        p.close()
