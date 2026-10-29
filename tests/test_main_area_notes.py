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


# ==================== 6 标题可自己取（2026-10-29）====================

def _pair(notes=None):
    """照 desktop_pet._make_note_panel 的接法造一套（含新加的两个回调）"""
    from note_panel import NotePanel
    from side_panel import SidePanel

    sp = SidePanel(tabs=notes or [{'id': 'n1', 'kind': 'note', 'text': '正文第一行'}],
                   save_cb=lambda *a: None)
    np = NotePanel(sp.note_tabs, sp.set_note_text, lambda: sp.add_tab('note')['id'],
                   title_cb=sp.set_note_title, del_cb=sp.remove_note)
    np._confirm_delete = lambda name: True        # 跳过模态框（离屏会卡住）
    return sp, np


def test_note_title_can_be_set_from_main_area():
    """主区能自己取标题 —— 写进侧栏那一份，侧栏页签也立刻变"""
    sp, np = _pair()
    try:
        np.ed_title.setText('十月会议纪要')
        assert np.flush_title() is True, '标题没写进去'
        tab = [t for t in sp.dump_tabs() if t['id'] == 'n1'][0]
        assert tab.get('title') == '十月会议纪要', tab
        i = [k for k, t in enumerate(sp._tabs) if t['id'] == 'n1'][0]
        assert sp.tabbar.tabText(i) == '十月会议纪要', '侧栏页签没跟着改'
    finally:
        np.deleteLater()
        sp.deleteLater()


def test_note_title_shows_in_list_immediately():
    """改名后主区左边列表要立刻显示新名字（不能非等到 refresh）"""
    sp, np = _pair()
    try:
        np.ed_title.setText('会议纪要')
        np.flush_title()
        assert np.lst.item(0).text() == '会议纪要', np.lst.item(0).text()
    finally:
        np.deleteLater()
        sp.deleteLater()


def test_note_title_cleared_falls_back_to_first_line():
    """清空标题 = 回到「用正文第一行当名字」（改错了要能退回去）"""
    sp, np = _pair([{'id': 'n1', 'kind': 'note', 'text': '原第一行\n第二行'}])
    try:
        np.ed_title.setText('先取个名')
        np.flush_title()
        assert [t for t in sp.dump_tabs() if t['id'] == 'n1'][0]['title'] == '先取个名'
        np.ed_title.setText('')
        assert np.flush_title() is True
        tab = [t for t in sp.dump_tabs() if t['id'] == 'n1'][0]
        assert not tab.get('title'), '标题没清掉：%r' % tab.get('title')
        assert np.lst.item(0).text() == '原第一行', np.lst.item(0).text()
    finally:
        np.deleteLater()
        sp.deleteLater()


def test_note_title_cap_matches_sidebar():
    """上限 18 字与 side_panel.rename_tab 同口径（不同步会出现「主区输得进、侧栏少几个字」）"""
    from note_panel import NotePanel
    assert NotePanel.MAX_TITLE == 18
    sp, np = _pair()
    try:
        np.ed_title.setText('x' * 40)
        # setMaxLength 先挡一层
        assert len(np.ed_title.text()) <= 18
        np.flush_title()
        assert len([t for t in sp.dump_tabs() if t['id'] == 'n1'][0]['title']) <= 18
        # 直接调侧栏那个接口也要截（防有人绕过输入框）
        assert sp.set_note_title('n1', 'y' * 40) is True
        assert len([t for t in sp.dump_tabs() if t['id'] == 'n1'][0]['title']) == 18
    finally:
        np.deleteLater()
        sp.deleteLater()


def test_title_only_edit_does_not_rewrite_body():
    """只改标题不该顺带写一遍正文（否则每次改名都白写一次 4000 字）"""
    from note_panel import NotePanel
    from side_panel import SidePanel

    calls = []
    sp = SidePanel(tabs=[{'id': 'n1', 'kind': 'note', 'text': '原文'}], save_cb=lambda *a: None)
    np = NotePanel(sp.note_tabs,
                   lambda i, t: (calls.append(('body', t)) or True),
                   None,
                   title_cb=lambda i, t: (calls.append(('title', t)) or True))
    try:
        np.ed_title.setText('只改标题')
        np.flush_title()
        np.flush()
        assert calls == [('title', '只改标题')], calls
    finally:
        np.deleteLater()
        sp.deleteLater()


# ==================== 7 便签可自由删除（2026-10-29）====================

def test_note_can_be_deleted_from_main_area():
    """主区能把便签删掉 —— 侧栏那份也要跟着没"""
    sp, np = _pair([{'id': 'n1', 'kind': 'note', 'text': 'a'},
                    {'id': 'n2', 'kind': 'note', 'text': 'b'}])
    try:
        np._cur_id = 'n2'
        np.refresh()
        assert np._on_delete() is True, '没删掉'
        assert [t['id'] for t in sp.note_tabs()] == ['n1'], sp.note_tabs()
        assert np.lst.count() == 1, '主区列表没同步'
    finally:
        np.deleteLater()
        sp.deleteLater()


def test_delete_cancelled_keeps_note():
    """确认框点「否」就不许删（防误点）"""
    sp, np = _pair()
    try:
        np._confirm_delete = lambda name: False
        assert np._on_delete() is False
        assert len(sp.note_tabs()) == 1, '点了取消还是删了'
    finally:
        np.deleteLater()
        sp.deleteLater()


def test_delete_last_note_keeps_sidebar_alive():
    """删到一条不剩：主区显示空态，侧栏不能塌成空面板"""
    sp, np = _pair()
    try:
        np._cur_id = 'n1'
        np.refresh()
        assert np._on_delete() is True
        assert sp.note_tabs() == [], '便签没删干净'
        assert np.lst.count() == 0
        assert np.ed.isReadOnly(), '没便签了正文框还能打字'
        assert np.ed_title.isReadOnly(), '没便签了标题框还能打字'
        assert '还没有便签' in np.lb_info.text()
        assert sp._tabs, '侧栏把页签删空了（DEFAULT_TABS 兜底失效）'
    finally:
        np.deleteLater()
        sp.deleteLater()


def test_remove_note_never_touches_non_note_tabs():
    """remove_note 只认便签：不许拿它误删任务/状态等页签"""
    from side_panel import SidePanel

    sp = SidePanel(tabs=[{'id': 'tasks', 'kind': 'tasks'},
                         {'id': 'n1', 'kind': 'note', 'text': ''}], save_cb=lambda *a: None)
    try:
        assert sp.remove_note('tasks') is False, '把任务页签删了'
        assert any(t['kind'] == 'tasks' for t in sp._tabs), '任务页签没了'
        assert sp.remove_note('不存在的id') is False
    finally:
        sp.deleteLater()


# ==================== 8 没有回调时降级（老调用方不破）====================

def test_panel_degrades_without_new_callbacks():
    """只传 notes/save/add（老写法）：标题框只读、删除钮不出现，正文照旧能存"""
    from note_panel import NotePanel
    from side_panel import SidePanel

    sp = SidePanel(tabs=[{'id': 'n1', 'kind': 'note', 'text': ''}], save_cb=lambda *a: None)
    np = NotePanel(sp.note_tabs, sp.set_note_text, lambda: None)
    try:
        assert np.ed_title.isReadOnly(), '没有 title_cb 却让人以为能改名'
        assert np.btn_del.isHidden(), '没有 del_cb 却留了个删除钮'
        np.ed.setPlainText('正文照旧')
        assert np.flush() is True
        assert sp.dump_tabs()[0]['text'] == '正文照旧'
    finally:
        np.deleteLater()
        sp.deleteLater()
