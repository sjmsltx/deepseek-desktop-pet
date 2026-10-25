# -*- coding: utf-8 -*-
"""主区改版（B 方案）与便签长文面板 —— 2026-10-25

Owner 两条原话：
  ①「主区位置可以调整一下，不然单独占一行太浪费了」
  ②「里面的内容怎么感觉有些鸡肋」

B 方案落点：
  · 入口并入输入行（与 输入框/🎤/📎 同一行），不再独占 22px 一行
  · 主区只装侧栏装不下的：便签长文 + 待办管理（替掉 540×420 独立弹窗）
  · 状态面板不再注册进主区 —— 它是侧栏「◎ 状态」页的复制品（"鸡肋"的来源）

本文件尽量用**行为**判据：
  1 主区按钮与输入框在**同一个布局**里（不是靠名字 grep 猜的）
  2 主区注册的面板恰为 ['todo', 'note']
  3 便签面板与侧栏是同一份数据（双向可见，不是两个副本）
  4 4000 字上限两边一致，且主区是"就地截断"而不是存的时候悄悄丢尾巴
  5 待办入口走主区，不再另开 QDialog
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from PySide6.QtWidgets import QApplication, QLayout  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)


def _pet():
    import desktop_pet as dp
    return dp.PetWidget()


def _layout_of(widget):
    """返回直接包含该控件的布局（找不到返回 None）"""
    root = widget.parentWidget()
    if root is None:
        return None
    for lay in root.findChildren(QLayout):
        if lay.indexOf(widget) >= 0:
            return lay
    return None


# ==================== 1 入口不再单独占一行 ====================

def test_main_area_button_shares_input_row():
    """主区按钮必须和输入框在同一个布局里 —— 这就是「不再单独占一行」"""
    p = _pet()
    try:
        btn = getattr(p, '_main_area_btn', None)
        assert btn is not None, '没有主区按钮'
        lay_btn = _layout_of(btn)
        lay_input = _layout_of(p.chat_input)
        assert lay_btn is not None and lay_input is not None
        assert lay_btn is lay_input, '主区按钮不在输入行里（又单独占一行了）'
    finally:
        p.deleteLater()


def test_main_area_row_layout_is_gone():
    """原先那行 `_main_area_row` 必须消失（否则 22px 还白占着）"""
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    assert '_main_area_row' not in src, '旧的独占行布局还留着'


def test_main_area_button_is_compact_icon():
    p = _pet()
    try:
        b = p._main_area_btn
        assert b.width() == 30 and b.height() == 30, (b.width(), b.height())
        assert b.text().strip(), '图标钮必须有文字/图标，不能是空白方块'
        assert p._t('main_area') in b.toolTip(), 'tooltip 要写清这是主区'
    finally:
        p.deleteLater()


# ==================== 2 主区只装 todo / note ====================

def test_main_area_registers_todo_and_note_only():
    import panel_registry as pr
    pr.clear_panels()
    try:
        p = _pet()
        try:
            n = p._register_builtin_panels()
            assert n == 2, '应该只注册两个面板，实际 %d' % n
            assert pr.panel_keys() == ['todo', 'note'], pr.panel_keys()
        finally:
            p.deleteLater()
    finally:
        pr.clear_panels()


def test_status_panel_not_in_main_area():
    """状态页是侧栏的复制品 ⇒ 不进主区（这就是"鸡肋"的根因）"""
    import panel_registry as pr
    pr.clear_panels()
    try:
        p = _pet()
        try:
            p._register_builtin_panels()
            assert 'status' not in pr.panel_keys(), '状态面板又回到主区了'
        finally:
            p.deleteLater()
    finally:
        pr.clear_panels()


# ==================== 3 便签与侧栏同一份数据 ====================

def test_note_panel_shares_sidebar_data():
    from note_panel import NotePanel
    from side_panel import SidePanel

    sp = SidePanel(tabs=[{'id': 'n1', 'kind': 'note', 'text': '原来的'}],
                   save_cb=lambda *a: None)
    sp._note_save = lambda: None
    np = NotePanel(lambda: sp.note_tabs(), sp.set_note_text, lambda: None)
    try:
        # 主区改 → 侧栏那份页签跟着变
        np.ed.setPlainText('主区写的')
        np.flush()
        got = [t for t in sp.dump_tabs() if t['id'] == 'n1'][0]['text']
        assert got == '主区写的', '主区改完，侧栏页签没跟着变：%r' % got

        # 侧栏改（使用者直接在侧栏打字）→ 主区刷新后看到同一份
        sp._note_editors['n1'].setPlainText('侧栏打的')
        np.ed.clearFocus()
        np.refresh()
        assert np.ed.toPlainText() == '侧栏打的', '侧栏改完，主区没看到：%r' % np.ed.toPlainText()

        # 主区新建 → 建在侧栏页签里（不是主区自己的第二份）
        n_before = len(sp.note_tabs())
        tab = sp.add_tab('note')
        assert tab and len(sp.note_tabs()) == n_before + 1
    finally:
        np.deleteLater()
        sp.deleteLater()


def test_note_panel_writes_then_refresh_keeps_text():
    """收完存盘后刷新，内容不能被自己冲掉（典型的"刷新覆盖输入"事故）"""
    from note_panel import NotePanel
    from side_panel import SidePanel

    sp = SidePanel(tabs=[{'id': 'n1', 'kind': 'note', 'text': ''}], save_cb=lambda *a: None)
    np = NotePanel(lambda: sp.note_tabs(), sp.set_note_text, lambda: None)
    try:
        np.ed.setPlainText('一二三')
        np.flush()
        np.refresh()
        assert np.ed.toPlainText() == '一二三'
    finally:
        np.deleteLater()
        sp.deleteLater()


# ==================== 4 字数上限两边一致 ====================

def test_stale_editor_does_not_block_saving():
    """侧栏那个编辑框被销毁后，写便签仍要成功，且死引用要清掉

    实测撞过一次：Internal C++ object already deleted ⇒ 每次写都白报一遍。
    数据能不能写对是底线，报错能不能自愈是第二条。
    """
    from side_panel import SidePanel

    class _DeadEditor:
        """复刻 Internal C++ object already deleted：一碰就抛 RuntimeError

        ⛔ 不用 deleteLater() 造这个状态 —— 它只是排队，processEvents() 不处理
          DeferredDelete 事件，控件其实还活着，分支根本走不到（实测一次）。
        """

        def toPlainText(self):
            raise RuntimeError('Internal C++ object (QPlainTextEdit) already deleted.')

        def blockSignals(self, *_a):
            return False

        def setPlainText(self, *_a):
            raise RuntimeError('Internal C++ object (QPlainTextEdit) already deleted.')

    sp = SidePanel(tabs=[{'id': 'n1', 'kind': 'note', 'text': ''}], save_cb=lambda *a: None)
    try:
        sp._note_editors['n1'] = _DeadEditor()          # 制造死引用
        assert sp.set_note_text('n1', '照样要存上') is True, '死引用不该阻断数据写入'
        assert sp.dump_tabs()[0]['text'] == '照样要存上'
        assert 'n1' not in sp._note_editors, '死引用没清掉，下次还会撞'
    finally:
        sp.deleteLater()


def test_flush_only_saves_when_dirty():
    """没改过就不该写盘 —— 退出收尾那次 hideEvent 常撞到已销毁的控件"""
    from note_panel import NotePanel
    from side_panel import SidePanel

    calls = []
    sp = SidePanel(tabs=[{'id': 'n1', 'kind': 'note', 'text': '原样'}], save_cb=lambda *a: None)
    sp.set_note_text = lambda i, t: (calls.append((i, t)) or True)
    np = NotePanel(lambda: sp.note_tabs(), sp.set_note_text)
    try:
        assert np.flush() is False and calls == [], '刚装载就保存了（没改过）'
        np.ed.setPlainText('改了')
        assert np.flush() is True and len(calls) == 1
        assert np.flush() is False and len(calls) == 1, '同一份内容被重复写盘'
    finally:
        np.deleteLater()
        sp.deleteLater()


def test_note_ids_do_not_collide():
    """连建多个便签，id 不许重复（撞号会让编辑框同步只认一个）"""
    from side_panel import SidePanel

    sp = SidePanel(tabs=[{'id': 'note1', 'kind': 'note', 'text': ''}], save_cb=lambda *a: None)
    try:
        used = {t['id'] for t in sp.note_tabs()}
        for _ in range(5):
            t = sp.add_tab('note')
            assert t is not None, '便签没建成'
            assert t['id'] not in used, 'id 撞号了：%r' % t['id']
            used.add(t['id'])
        assert len(used) == 6
    finally:
        sp.deleteLater()


def test_note_cap_matches_sidebar_and_truncates_in_place():
    from note_panel import NotePanel
    from side_panel import SidePanel

    assert NotePanel.MAX_CHARS == 4000, '上限应与侧栏一致（side_panel 截到 4000）'
    sp = SidePanel(tabs=[{'id': 'x', 'kind': 'note', 'text': ''}], save_cb=lambda *a: None)
    try:
        sp._note_editors['x'].setPlainText('字' * 5000)
        assert len(sp.dump_tabs()[0]['text']) == 4000, '侧栏上限不是 4000 了'

        saved = {}
        np = NotePanel(lambda: sp.note_tabs(), lambda i, t: saved.__setitem__(i, t))
        try:
            np.ed.setPlainText('字' * 5000)
            assert len(np.ed.toPlainText()) == 4000, '主区没有就地截断'
            np.flush()
            assert len(saved.get('x', '')) == 4000
        finally:
            np.deleteLater()
    finally:
        sp.deleteLater()


# ==================== 5 待办入口走主区 ====================

def test_todo_manager_opens_main_area_not_dialog():
    p = _pet()
    try:
        seen = {}

        class _Shell:
            def show_panel(self, key):
                seen['key'] = key
                return True

        p._open_main_area = lambda: _Shell()
        out = p._open_todo_manager()
        assert out is not None, '待办入口没打开主区'
        assert seen.get('key') == 'todo', '没有切到待办页：%r' % seen
        assert getattr(p, '_todo_dlg', None) is None, '还在造独立弹窗'
    finally:
        p.deleteLater()
