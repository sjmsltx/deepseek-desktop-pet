# -*- coding: utf-8 -*-
"""便签长文面板（3.0 主区 · B 方案，2026-10-25）

为什么需要它
------------
侧栏「📝 便签」页签只有 186px 宽 —— 随手记一两个词够用，写长文等于在夹缝里打字。
主区 720×480 正好补这个缺口：左侧便签列表，右侧大编辑区。

和数据的关系（重要）
--------------------
本面板**不存自己的数据**：`notes_cb()` 直接从侧栏页签里读 note 页签，
`save_cb(id, text)` 写回同一份页签。
⛔ 不另存 JSON、不建第二副本 —— 否则侧栏改了主区看不见、主区改了侧栏看不见，
   就是「两个副本各自为政」那类老问题（2026-10-24 日志 §4.3 记过一次）。

契约（panel_registry）
----------------------
· 不 import desktop_pet，只吃注入的三个回调
· 提供 refresh()，容器切页/重开主区时会调
· 不加硬编码颜色（外观跟系统主题，避免破坏 theme_tokens 的「只减不增」ratchet）
"""

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

_log = logging.getLogger('note_panel')


class NotePanel(QWidget):
    """便签长文编辑器。

    Args:
        notes_cb: () -> [{'id','title','text'}]，随取随读，不缓存
        save_cb:  (note_id, text) -> bool
        add_cb:   () -> 新便签 id（可为 None）
        title_cb: (note_id, title) -> bool，改标题（2026-10-29 加；不传则标题框只读）
        del_cb:   (note_id) -> bool，删便签（同上；不传则不显示删除按钮）
        labels:   i18n 文案
    """

    #: 与侧栏一致：side_panel._on_note_changed 也截到 4000 字。
    #: ⛔ 两边上限必须相同，否则「主区能存、侧栏存完丢尾巴」。
    MAX_CHARS = 4000
    #: 停手 500ms 再落盘，与宿主 _save_side_panel 的 800ms 防抖叠加后仍不打字卡顿
    SAVE_DELAY_MS = 500
    #: 标题上限，与 side_panel.rename_tab 的 `[:18]` 同口径。
    #: ⛔ 不一致会出现「主区输得进、侧栏存完少几个字」。
    MAX_TITLE = 18

    def __init__(self, notes_cb, save_cb, add_cb=None, title_cb=None, del_cb=None,
                 labels=None, parent=None):
        super().__init__(parent)
        self._notes_cb = notes_cb
        self._save_cb = save_cb
        self._add_cb = add_cb
        self._title_cb = title_cb       # 2026-10-29 加：改标题。不传 = 标题框只读
        self._del_cb = del_cb           # 2026-10-29 加：删便签。不传 = 不显示删除钮
        self._L = labels or {}
        self._cur_id = ''
        self._loading = False          # 装载正文时屏蔽 textChanged，免得把刚读出来的又写回去
        self._dirty = False            # 正文真被改过才置 True —— 没改就不写盘
                                       # （退出收尾时也走 flush，无条件写会撞已销毁的控件）
        self._title_dirty = False      # 标题同上，但**与正文分开记**：
                                       # 混成一个 flag 会让「只改标题」被当成「正文也脏了」

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.SAVE_DELAY_MS)
        self._timer.timeout.connect(self.flush)

        self._title_timer = QTimer(self)      # 标题单独一个防抖：两件事落盘时间互不牵连
        self._title_timer.setSingleShot(True)
        self._title_timer.setInterval(self.SAVE_DELAY_MS)
        self._title_timer.timeout.connect(self.flush_title)

        self._build_ui()
        self.refresh()

    # ---------------- 界面 ----------------
    def _build_ui(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        # 左：便签列表 + 新建 + 删除
        left = QVBoxLayout()
        left.setSpacing(4)
        self.btn_new = QPushButton(self._L.get('new', '＋ 新建便签'), self)
        self.btn_new.setCursor(Qt.PointingHandCursor)
        self.btn_new.clicked.connect(self._on_add)
        left.addWidget(self.btn_new)
        self.lst = QListWidget(self)
        self.lst.setFixedWidth(150)
        self.lst.currentItemChanged.connect(lambda *_: self._on_pick())
        left.addWidget(self.lst, 1)
        # 2026-10-29 Owner：「新增便签之后不能自由删除」 ⇒ 删除入口放这儿，
        # 与「＋ 新建」上下呼应；只删**当前选中**那一条（不搞多选，避免误删一片）
        self.btn_del = QPushButton(self._L.get('del', '🗑 删除本便签'), self)
        self.btn_del.setCursor(Qt.PointingHandCursor)
        self.btn_del.clicked.connect(self._on_delete)
        self.btn_del.setEnabled(False)      # 没有便签时不可点
        left.addWidget(self.btn_del)
        lay.addLayout(left)

        # 右：标题 + 编辑区
        right = QVBoxLayout()
        right.setSpacing(4)
        # 2026-10-29 Owner：「标题他怎么不能自己取」 ⇒ 标题从只读 QLabel 换成可编辑输入框
        self.ed_title = QLineEdit(self)
        self.ed_title.setMaxLength(self.MAX_TITLE)
        self.ed_title.setPlaceholderText(self._L.get('title_hint', '标题（留空则用正文第一行）'))
        self.ed_title.textChanged.connect(self._on_title_changed)
        right.addWidget(self.ed_title)
        self.lb_info = QLabel('', self)
        self.lb_info.setWordWrap(False)
        right.addWidget(self.lb_info)
        self.ed = QPlainTextEdit(self)
        self.ed.setPlaceholderText(self._L.get('hint', '在这里写；停手一会儿会自动保存'))
        self.ed.textChanged.connect(self._on_text_changed)
        right.addWidget(self.ed, 1)
        self.lb_count = QLabel('', self)
        self.lb_count.setAlignment(Qt.AlignRight)
        right.addWidget(self.lb_count)
        lay.addLayout(right, 1)

        # 降级：没注入对应回调就做不了这件事，控件要如实反映（别让人点了没反应）
        #   · 无 title_cb → 标题框只读（老调用方只传 notes/save/add）
        #   · 无 del_cb   → 删除按钮整块隐藏，而不是留个点了没用的钮
        if not callable(self._title_cb):
            self.ed_title.setReadOnly(True)
        if not callable(self._del_cb):
            self.btn_del.setVisible(False)

    # ---------------- 对外 ----------------
    def refresh(self):
        """重新读一遍便签列表。

        ⚠ 不抢正在输入的正文：编辑框有焦点时不覆盖它 ——
          否则侧栏定时刷新、AI 改别的页签都会把使用者打到一半的字冲掉。
        """
        notes = self._safe_notes()
        keep = self._cur_id
        self.lst.blockSignals(True)
        self.lst.clear()
        row = -1
        for n in notes:
            text = str(n.get('text') or '')
            title = str(n.get('title') or '').strip()
            label = title or (text.strip().splitlines()[0][:18] if text.strip() else '（空便签）')
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, n.get('id') or '')
            it.setToolTip(text[:200] or '（空便签）')
            self.lst.addItem(it)
            if (n.get('id') or '') == keep:
                row = self.lst.count() - 1
        if row < 0 and self.lst.count():
            row = 0
        if row >= 0:
            self.lst.setCurrentRow(row)
        self.lst.blockSignals(False)

        if not self.lst.count():
            self._cur_id = ''
            self._set_editor('', editable=False)
            self._set_title('', editable=False)
            self.btn_del.setEnabled(False)
            self.lb_info.setVisible(True)
            self.lb_info.setText(self._L.get('empty', '还没有便签 —— 点「＋ 新建便签」开始'))
            return
        self.btn_del.setEnabled(callable(self._del_cb))
        # 列表空信号被屏蔽了，这里手动同步一次当前条目
        self._load_current(force_text=not self.ed.hasFocus())

    def flush(self):
        """把编辑框内容写回去（切便签、藏窗口、定时器都走这里）。

        ⛔ 只在 _dirty 时落盘：程序退出时 hideEvent 也会走到这里，
          那时 Qt 控件已销毁，无条件写会报 "Internal C++ object already deleted"。
          没改过就什么都不做 —— 既没噪音，也不会白写盘。
        """
        if not self._cur_id or not self._dirty:
            return False
        try:
            ok = self._save_cb(self._cur_id, self.ed.toPlainText())
        except Exception as exc:
            _log.warning('保存便签 %r 失败：%s', self._cur_id, exc)
            return False
        if ok is False:
            # id 找不到 = 这条便签在别处被删了；保留 dirty 没意义，清掉即可
            self._dirty = False
            _log.warning('便签 %r 已不存在，放弃本次保存', self._cur_id)
            return False
        self._dirty = False
        self._sync_item_label()     # 正文变了、又没取标题时，列表要跟着第一行走
        return True

    def flush_title(self):
        """把标题写回去。没改过不写（与 flush 同口径）。

        ⛔ 空标题也要写：那不是「没改」，是「清掉标题、回到用正文第一行当名字」——
           note_panel 的列表和侧栏页签都靠这个兜底。少写这一次，清空就不生效。
        """
        if not self._cur_id or not self._title_dirty:
            return False
        if not callable(self._title_cb):
            return False
        try:
            ok = self._title_cb(self._cur_id, self.ed_title.text())
        except Exception as exc:
            _log.warning('保存便签标题 %r 失败：%s', self._cur_id, exc)
            return False
        self._title_dirty = False
        if ok is not False:
            self._sync_item_label()     # 改名后列表要立刻显示新名字
        return ok is not False

    # ---------------- 内部 ----------------
    def _safe_notes(self):
        try:
            got = self._notes_cb() or []
        except Exception as exc:
            _log.warning('读取便签失败：%s', exc)
            return []
        return [n for n in got if isinstance(n, dict)]

    def _set_editor(self, text, editable=True):
        self._loading = True
        self._dirty = False
        try:
            self.ed.setPlainText(text or '')
            self.ed.setReadOnly(not editable)
        finally:
            self._loading = False
        self._update_count()

    def _sync_item_label(self):
        """只改「当前那一项」的显示字 —— 不重建列表。

        ⛔ 不调 refresh()：它会 clear() 整个列表再重填，正在打字的焦点和滚动位置
          都会被冲掉（note_panel.refresh 的注释里记过这个坑）。
        显示口径与 refresh() 里完全一致：有标题用标题，没有就用正文第一行前 18 字。
        """
        it = self.lst.currentItem()
        if it is None:
            return
        title = self.ed_title.text().strip()
        body = self.ed.toPlainText().strip()
        label = title or (body.splitlines()[0][:18] if body else '（空便签）')
        if it.text() != label:
            it.setText(label)

    def _set_title(self, title, editable=True):
        """装载标题。⛔ 必须屏蔽 textChanged：否则装载就被当成「使用者改了标题」而白写盘。"""
        self._loading = True
        try:
            self.ed_title.setText(title or '')
            self.ed_title.setReadOnly(not editable or not callable(self._title_cb))
        finally:
            self._loading = False
        self._title_dirty = False

    def _current_item_id(self):
        it = self.lst.currentItem()
        return (it.data(Qt.UserRole) or '') if it is not None else ''

    def _on_pick(self):
        if not self.lst.count():
            return
        self.flush()                    # 切走前先把上一份存了
        self.flush_title()
        self._load_current(force_text=True)

    def _load_current(self, force_text=True):
        nid = self._current_item_id()
        if not nid:
            return
        note = None
        for n in self._safe_notes():
            if (n.get('id') or '') == nid:
                note = n
                break
        if note is None:
            # 便签在别处被删了：退回列表让 refresh 收拢
            self._cur_id = ''
            self.refresh()
            return
        self._cur_id = nid
        body = str(note.get('text') or '')
        if force_text or self.ed.toPlainText() != body:
            self._set_editor(body, editable=True)
        else:
            self._update_count()
        # 2026-10-29：标题从「只读 QLabel 显示」改成「可编辑输入框」——
        # Owner 原话「标题他怎么不能自己取」。原先只显示、没有改的入口。
        title = str(note.get('title') or '').strip()
        self._set_title(title, editable=True)
        # lb_info 这一行只在空态（还没有便签）时用，有便签就收起，不白占高度
        self.lb_info.setVisible(False)

    def _on_text_changed(self):
        if self._loading:
            return
        text = self.ed.toPlainText()
        if len(text) > self.MAX_CHARS:
            # 到上限就地截断，而不是"存的时候悄悄丢尾巴"
            cur = self.ed.textCursor()
            pos = min(cur.position(), self.MAX_CHARS)
            self._loading = True
            try:
                self.ed.setPlainText(text[:self.MAX_CHARS])
                cur = self.ed.textCursor()
                cur.setPosition(pos)
                self.ed.setTextCursor(cur)
            finally:
                self._loading = False
        self._dirty = True
        self._update_count()
        if self._cur_id:
            self._timer.start()

    def _on_title_changed(self):
        """标题被改：防抖后落盘。与正文共用 _loading 屏蔽，但脏标记分开。"""
        if self._loading:
            return
        self._title_dirty = True
        if self._cur_id:
            self._title_timer.start()

    def _update_count(self):
        n = len(self.ed.toPlainText())
        tpl = self._L.get('chars', '%d / %d 字')
        try:
            txt = tpl % (n, self.MAX_CHARS)
        except TypeError:
            txt = '%d / %d 字' % (n, self.MAX_CHARS)
        if n >= self.MAX_CHARS:
            txt += '  已达上限' if self._L.get('title', '').find('便签') >= 0 else '  limit'
        self.lb_count.setText(txt)

    def _on_add(self):
        if not callable(self._add_cb):
            return
        self.flush()
        try:
            nid = self._add_cb()
        except Exception as exc:
            _log.warning('新建便签失败：%s', exc)
            return
        if not nid:
            return
        self._cur_id = str(nid)
        self.refresh()

    def _confirm_delete(self, name):
        """删前问一句。抽成方法是为了测试能替换掉（模态框会卡住离屏测试）。"""
        tpl = self._L.get('del_confirm', '确定删掉「{name}」？删了就找不回来了。')
        try:
            body = tpl.format(name=(name or '')[:self.MAX_TITLE])
        except (KeyError, IndexError, ValueError):
            # 文案里没有 {name} 占位符（或写错了）：退回一句不依赖格式的话
            body = '确定删掉这条便签？删了就找不回来了。'
        r = QMessageBox.question(
            self, self._L.get('del_title', '删除便签'), body,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return r == QMessageBox.Yes

    def _on_delete(self):
        """删掉当前这条便签。返回是否真的删了。"""
        if not self._cur_id or not callable(self._del_cb):
            return False
        # 先把在编辑的内容落盘，再删 —— 万一使用者是「写一半想删」，
        # 存过的东西在原件/备份里还查得到，不留下「刚打的字凭空没了」这种事
        self.flush()
        self.flush_title()
        name = self.ed_title.text().strip()
        if not name:
            # 没取名字的便签，用正文第一行给人认（与列表里显示的口径一致）
            body = self.ed.toPlainText().strip()
            name = body.splitlines()[0][:self.MAX_TITLE] if body else self._L.get('unnamed', '空便签')
        if not self._confirm_delete(name):
            return False
        try:
            ok = self._del_cb(self._cur_id)
        except Exception as exc:
            _log.warning('删除便签 %r 失败：%s', self._cur_id, exc)
            return False
        if ok is False:
            _log.warning('删除便签 %r 没删掉（id 不在了？）', self._cur_id)
            return False
        self._cur_id = ''
        self._dirty = False
        self._title_dirty = False
        self.refresh()
        return True

    # 藏起来/关掉前把没落盘的那几百毫秒存掉
    def hideEvent(self, ev):
        try:
            self.flush()
            self.flush_title()
        except Exception as exc:
            _log.warning('hide 时保存便签失败：%s', exc)
        return super().hideEvent(ev)
