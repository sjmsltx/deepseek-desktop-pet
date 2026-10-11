# -*- coding: utf-8 -*-
"""D11-1 护栏：系统提示气泡**必须换行** ＋ **不得超出父窗口被裁** ✗

现象（Owner 2026-10-11 实测 ✓）：
  「你那个气泡它不会换行，就导致了如果说这个整个对话面板太小的话有些字会被吃掉。」

根因：
  `affection_ui.CostBubble` 是 QLabel ✓，而 **QLabel 默认不折行** ✗
  ⇒ 气泡按整行文字撑到自然宽度 ✗ ⇒ 超出父窗口右侧 ⇒ **被裁掉** ✗
  且调用方（`desktop_pet._show_pet_bubble`）按 `len(text) * 6` **估宽** ✗
  ⇒ 中文 / emoji / 混排时估算必偏 ✗（估算跑在控件之外，控件自己无从纠正 ✗）

修法（收在控件内部 ✓ —— 与 D11-2「门收到唯一出口」同一思路 ✓）：
  ① `setWordWrap(True)` ✓（仅此不够：**必须配合最大宽度**才有意义 ✓）
  ② `_fit_width()`：最大宽度 ＝ 父宽 − 2×PAD ✓
  ③ `show_bubble()`：显示前**按当前父宽重算** ✓ ＋ **夹取 x / y** ✓
     ⇒ 无论调用方怎么估，气泡都完整落在父控件内 ✓

运行：python -m pytest tests/test_pet_bubble_wrap.py -q
"""
import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import io  # noqa: E402

LONG = ('这是一条很长的系统提示气泡文本，用来验证它不会再被父窗口裁掉，' * 3)
SHORT = '短句'


def _pet():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(sys.argv)
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    return p


def _bubble(p, text):
    from affection_ui import CostBubble
    return CostBubble(p, text)


# ── ① 必须开启换行 ✓ ──────────────────────────────────────────────
def test_bubble_word_wrap_enabled():
    p = _pet()
    b = _bubble(p, LONG)
    assert b.wordWrap() is True, '⭐ 气泡必须允许换行 ✗（QLabel 默认不折行 ⇒ 字被吃掉 ✓）'


# ── ② ⭐ 长文本宽度不得超出父控件 ✓（核心）────────────────────────
def test_long_text_width_within_parent():
    p = _pet()
    b = _bubble(p, LONG)
    b._fit_width()
    b.adjustSize()
    limit = p.width() - 2 * b.PAD
    assert b.width() <= limit, \
        '⭐ 长文本气泡宽度 %d 超出父窗口可用宽 %d ✗（会被裁 ✓）' % (b.width(), limit)


# ── ③ 短文本不应被强行压窄 ✓（防"一刀切退化"✗）──────────────────
def test_short_text_keeps_natural_width():
    p = _pet()
    b = _bubble(p, SHORT)
    b._fit_width()
    b.adjustSize()
    assert b.width() < p.width() - 2 * b.PAD, \
        '⭐ 短文本应保持自然宽度 ✓（不该被撑满或压弯 ✗）'
    assert b.height() > 0


# ── ④ ⭐ show_bubble 后气泡必须完整落在父控件内 ✓ ─────────────────
def test_show_bubble_clamped_inside_parent():
    p = _pet()
    b = _bubble(p, LONG)
    # ⭐ 故意给一个"会跑出右边界"的 x（模拟调用方的错误估算 ✓）
    bad_x = p.width() - 5
    b.show_bubble(bad_x, 8, dy=-46, duration=10, hold_ms=0)
    try:
        assert b.x() >= 0, '⭐ 气泡不得跑到父控件左侧外 ✗'
        assert b.x() + b.width() <= p.width(), \
            '⭐ 气泡右边界 %d 超出父宽 %d ✗（正是"字被吃掉"的成因 ✓）' % (b.x() + b.width(), p.width())
    finally:
        b._pos_anim.stop()
        b._op_anim.stop()
        b.hide()


def test_show_bubble_clamped_vertical_when_too_low():
    """⭐ 底部场景：气泡不得从下方溢出 ✓（顶部提示与底部状态条共用同一控件 ✓）"""
    p = _pet()
    b = _bubble(p, LONG)
    b.show_bubble(10, p.height() - 10, dy=-46, duration=10, hold_ms=0)
    try:
        assert b.y() >= 0, '⭐ 气泡不得跑出上边界 ✗'
        assert b.y() + b.height() <= p.height(), \
            '⭐ 气泡下边界 %d 超出父高 %d ✗' % (b.y() + b.height(), p.height())
    finally:
        b._pos_anim.stop()
        b._op_anim.stop()
        b.hide()


# ── ⑤ 源码护栏：收在控件内部 ✓，不靠调用方估算 ✓ ─────────────────
def test_source_guard_fit_inside_widget():
    s = io.open(os.path.join(BASE, 'affection_ui.py'), encoding='utf-8').read()
    assert 'self.setWordWrap(True)' in s, '⭐ 气泡必须开启换行 ✗'
    assert 'def _fit_width(self):' in s, '⭐ 最大宽度必须由控件自己算 ✓（⛔ 不靠调用方估宽 ✗）'
    assert 'setMaximumWidth(' in s, '⭐ 需要设最大宽度 ✓（只开 wordWrap 不生效 ✓）'
    # show_bubble 里必须重算（父窗口后续 resize 也要跟上 ✓）
    i = s.index('def show_bubble(')
    body = s[i:i + 1800]
    assert 'self._fit_width()' in body, '⭐ show_bubble 显示前必须重算宽度 ✓（父可能已 resize ✓）'
