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
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

_log = logging.getLogger('note_panel')


class NotePanel(QWidget):
    """便签长文编辑器。

    Args:
        notes_cb: () -> [{'id','title','text'}]，随取随读，不缓存
        save_cb:  (note_id, text) -> bool
        add_cb:   () -> 新便签 id（可为 None）
        labels:   i18n 文案
    """

    #: 与侧栏一致：side_panel._on_note_changed 也截到 4000 字。
    #: ⛔ 两边上限必须相同，否则「主区能存、侧栏存完丢尾巴」。
    MAX_CHARS = 4000
    #: 停手 500ms 再落盘，与宿主 _save_side_panel 的 800ms 防抖叠加后仍不打字卡顿
    SAVE_DELAY_MS = 500

    def __init__(self, notes_cb, save_cb, add_cb=None, labels=None, parent=None):
        super().__init__(parent)
        self._notes_cb = notes_cb
        self._save_cb = save_cb
        self._add_cb = add_cb
        self._L = labels or {}
        self._cur_id = ''
        self._loading = False          # 装载正文时屏蔽 textChanged，免得把刚读出来的又写回去
        self._dirty = False            # 正文真被改过才置 True —— 没改就不写盘
                                       # （退出收尾时也走 flush，无条件写会撞已销毁的控件）

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.SAVE_DELAY_MS)
        self._timer.timeout.connect(self.flush)

        self._build_ui()
        self.refresh()

    # ---------------- 界面 ----------------
    def _build_ui(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        # 左：便签列表 + 新建
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
        lay.addLayout(left)

        # 右：编辑区
        right = QVBoxLayout()
        right.setSpacing(4)
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
            self.lb_info.setText(self._L.get('empty', '还没有便签 —— 点「＋ 新建便签」开始'))
            return
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
        return True

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

    def _current_item_id(self):
        it = self.lst.currentItem()
        return (it.data(Qt.UserRole) or '') if it is not None else ''

    def _on_pick(self):
        if not self.lst.count():
            return
        self.flush()                    # 切走前先把上一份存了
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
        # 只显示标题本身：写成「会议纪要（📝 便签长文）」属于页名重复，读着啰嗦（截图 2026-10-25 发现）
        title = str(note.get('title') or '').strip()
        self.lb_info.setText(title or self._L.get('title', '📝 便签长文'))

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

    # 藏起来/关掉前把没落盘的那几百毫秒存掉
    def hideEvent(self, ev):
        try:
            self.flush()
        except Exception as exc:
            _log.warning('hide 时保存便签失败：%s', exc)
        return super().hideEvent(ev)
