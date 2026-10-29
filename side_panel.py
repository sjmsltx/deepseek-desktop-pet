# -*- coding: utf-8 -*-
"""side_panel.py — 聊天面板右侧信息栏（v6.65）
================================================

背景
----
原先右侧只有「任务队列」一栏（还要手动展开），大部分时间是空的，占着约 1/3 宽度。
使用者反馈："太占空间""只放一个东西有点浪费"，并补充：**希望页签能自己加、自己删**。

本模块把那一栏改成**多页签信息栏**：

| 页签 | 内容 | 能否删除 |
|---|---|---|
| 📋 任务 | FCFS 队列：拖拽排序 / 双击取消排队 / `/stop` 急停 | ❌（队列管理需要界面） |
| 📊 状态 | 今日用量、余额、当前模型与声线、峰谷时段、好感与饱食度 | ✅ |
| 💰 花费 | 今日/累计花费、未配价格未计入次数 | ✅ |
| ✔ 待办 | 待办清单概览 | ✅ |
| 📝 便签 | 自己写点东西，自动保存（可加多个；**纯文本**，单条 ≤4000 字） | ✅ |
| 🖥 系统 | CPU 核数、内存占用、运行时长 | ✅ |

- **自定义**：右上「＋」加页签；页签上右键「重命名 / 删除」；页签可拖拽排序
- **记忆**：页签列表（含便签文本）与折叠状态存进 config.json，下次打开还原
- **省空间**：没有任务时不再白占地方 —— 折叠后只留一个竖条把手；页签为空时自动隐藏页签条
- 依赖：只用 PySide6 + 宿主注入的数据获取回调（不直接 import 宿主，便于单测）
"""
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QInputDialog, QLabel,
                               QListWidget, QListWidgetItem, QMenu, QPlainTextEdit, QPushButton,
                               QStackedWidget, QTabBar, QVBoxLayout, QWidget)

TAB_KINDS = (
    ('tasks', '📋 任务', 'FCFS 队列：拖拽排序 · 双击取消排队 · /stop 急停'),
    ('status', '📊 状态', '今日用量、余额、模型与声线、峰谷时段、好感与饱食度'),
    ('cost', '💰 花费', '今日/累计花费与「未配价格未计入」次数'),
    ('todo', '✔ 待办', '待办清单概览（管理入口：设置 → 记忆与数据）'),
    ('note', '📝 便签', '随手记点东西，自动保存（可以加多个）'),
    ('system', '🖥 系统', 'CPU 核数、内存占用、运行时长'),
)
KIND_LABEL = {k: lab for k, lab, _tip in TAB_KINDS}
KIND_TIP = {k: tip for k, _lab, tip in TAB_KINDS}
# 页签上只放图标（186px 宽里面放不下「📋 任务」四个字，会被省略成「…」）；
# 完整名字在工具提示与顶部标题里都能看到
# 页签图标：必须用**细窄的单色符号**，不能用彩色 emoji
# v6.66 fix：彩色 emoji（📋/📊/📝 实测各 16px）+ 页签内边距 刚好超过页签格宽（~26px），
# Qt 的 ElideRight 会把它省略成“…”——使用者看到的“页签显示成 …”就是这个（跟进程新旧无关）。
# 下面这批实测宽度 6~12px（Microsoft YaHei UI 9pt），页签格放得下。
KIND_ICON = {'tasks': '☰', 'status': '◎', 'cost': '¥',
             'todo': '✓', 'note': '✎', 'system': '⌗'}
CORE_KINDS = ('tasks',)          # 不可删除
COLLAPSED_W = 24                 # 折叠后的宽度（只留一个把手）


def _silent_note(msg):
    """side_panel 内的落痕出口（与主程序 _silent_log 同义；本文件要能独立导入）"""
    import logging
    logging.getLogger('side_panel').warning(msg)


def tab_text(tab):
    """页签上显示什么：内置类型只显示图标（186px 里放不下四个字）；自定义名字保留"""
    title = str(tab.get('title') or '').strip()
    if title:
        return title[:6]
    return KIND_ICON.get(tab.get('kind'), '•')
DEFAULT_TABS = ({'id': 'tasks', 'kind': 'tasks'},
                {'id': 'status', 'kind': 'status'},
                {'id': 'todo', 'kind': 'todo'})


def normalize_tabs(raw):
    """把配置里的页签列表洗成合法结构

    - 未知类型丢弃；id 去重；至少留一个（默认布局）
    - v6.66 fix：除便签外**同类型只留一个** —— “状态/花费/待办/系统”是同一份全局信息，
      重复添加只会重复显示（使用者已实际加出重复页签），加载时直接洗净
    """
    out, seen, kinds = [], set(), set()
    for item in (raw or []):
        try:
            kind = str(item.get('kind') or '').strip()
            if kind not in KIND_LABEL:
                continue
            if kind != 'note' and kind in kinds:
                continue
            kinds.add(kind)
            tid = str(item.get('id') or kind).strip() or kind
            base, n = tid, 2
            while tid in seen:
                tid = '%s%d' % (base, n)
                n += 1
            seen.add(tid)
            tab = {'id': tid, 'kind': kind}
            if item.get('title'):
                tab['title'] = str(item['title'])[:18]
            if kind == 'note':
                tab['text'] = str(item.get('text') or '')[:4000]
            out.append(tab)
        except Exception:
            continue
    if not out:
        out = [dict(t) for t in DEFAULT_TABS]
    return out


class SidePanel(QFrame):
    """右侧信息栏：多页签 + 可增删改 + 可折叠。宿主通过回调提供数据与持久化。"""

    def __init__(self, parent=None, tabs=None, collapsed=False, save_cb=None,
                 data_cb=None, theme_qss=None):
        super().__init__(parent)
        self._tabs = normalize_tabs(tabs)
        self._collapsed = bool(collapsed)
        self._save_cb = save_cb                      # save_cb(tabs, collapsed)
        self._data_cb = data_cb or (lambda: {})      # 返回动态数据 dict（给状态/花费/待办/系统页）
        self._task_hooks = {'dblclick': None, 'reorder': None}
        self._note_save = None                       # note 页编辑后的回存回调
        self._note_editors = {}                      # note id -> 编辑框（主区改便签时要同步这里）
        self._width = 186
        self.setFixedWidth(self._width)
        if theme_qss:
            try:
                self.setStyleSheet(theme_qss())
            except Exception:
                pass

        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(4)
        self.lb_head = QLabel('信息栏', self)
        head.addWidget(self.lb_head)
        head.addStretch(1)
        self.btn_add = QPushButton('＋', self)
        self.btn_add.setFixedSize(18, 18)
        self.btn_add.setCursor(Qt.PointingHandCursor)
        self.btn_add.setToolTip('添加页签（任务 / 状态 / 花费 / 待办 / 便签 / 系统）')
        self.btn_add.clicked.connect(self._show_add_menu)
        head.addWidget(self.btn_add)
        self.collapse_btn = QPushButton('◀', self)
        self.collapse_btn.setFixedSize(18, 18)
        self.collapse_btn.setCursor(Qt.PointingHandCursor)
        self.collapse_btn.setToolTip('收缩/展开信息栏')
        head.addWidget(self.collapse_btn)
        v.addLayout(head)

        self.tabbar = QTabBar(self)
        self.tabbar.setExpanding(False)
        self.tabbar.setMovable(True)
        # 页签内边距收紧 + 保底宽度，避免文字/图标被省略成“…”（图标页签只需要十几 px）
        self.tabbar.setStyleSheet('QTabBar::tab{padding:2px 5px;min-width:14px;}')
        self.tabbar.setDrawBase(False)
        self.tabbar.setElideMode(Qt.ElideRight)
        self.tabbar.setUsesScrollButtons(True)
        self.tabbar.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabbar.customContextMenuRequested.connect(self._tab_menu)
        self.tabbar.currentChanged.connect(self._on_tab_changed)
        self.tabbar.tabMoved.connect(lambda *_: self._persist())
        v.addWidget(self.tabbar)

        self.stack = QStackedWidget(self)
        v.addWidget(self.stack, 1)
        self.hint = QLabel('', self)
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet('font-size:10px;')
        v.addWidget(self.hint)

        self._build_all()
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.refresh_dynamic)
        self.timer.start()
        self._apply_collapsed()

    def showEvent(self, ev):
        # 窗口刚显示时立即填一次，不等 2 秒定时器（否则会停在占位符上）
        try:
            self.refresh_dynamic(force=True)
        except Exception:
            pass
        return super().showEvent(ev)

    # ---------------- 页签构建 ----------------
    def _build_all(self):
        while self.tabbar.count():
            self.tabbar.removeTab(0)
        while self.stack.count():
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            w.deleteLater()
        self._tasks_list = None
        self._note_editors = {}
        for i, tab in enumerate(self._tabs):
            w = self._make_widget(tab)
            self.stack.addWidget(w)
            title = tab_text(tab)
            self.tabbar.addTab(title)
            self.tabbar.setTabToolTip(i, '%s —— %s' % (tab.get('title') or KIND_LABEL.get(tab['kind'], ''),
                                                      KIND_TIP.get(tab['kind'], '')))
        if self.tabbar.count():
            self.tabbar.setCurrentIndex(0)
            self._on_tab_changed(0)

    def _make_widget(self, tab):
        kind = tab['kind']
        if kind == 'tasks':
            w = QWidget(self)
            lay = QVBoxLayout(w)
            lay.setContentsMargins(0, 0, 0, 0)
            self._tasks_list = QListWidget(w)
            self._tasks_list.setDragDropMode(QAbstractItemView.InternalMove)
            self._tasks_list.setDefaultDropAction(Qt.MoveAction)
            self._tasks_list.itemDoubleClicked.connect(
                lambda it: self._task_hooks['dblclick'] and self._task_hooks['dblclick'](it))
            try:
                self._tasks_list.model().rowsMoved.connect(
                    lambda *a: self._task_hooks['reorder'] and self._task_hooks['reorder']())
            except Exception:
                pass
            lay.addWidget(self._tasks_list, 1)
            return w
        if kind == 'note':
            ed = QPlainTextEdit(w_ := QWidget(self))
            ed.setPlaceholderText('随手记…（自动保存）')
            ed.setPlainText(str(tab.get('text') or ''))
            ed.textChanged.connect(lambda t=tab, e=ed: self._on_note_changed(t, e))
            self._note_editors[tab.get('id')] = ed
            lay = QVBoxLayout(w_)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(ed, 1)
            return w_
        # 其余都是只读文本页
        lb = QLabel('正在读取…', self)
        lb.setWordWrap(True)
        lb.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
        return lb

    def _on_note_changed(self, tab, editor):
        tab['text'] = editor.toPlainText()[:4000]
        if self._note_save:
            self._note_save()

    # ---------------- 增删改 ----------------
    def _show_add_menu(self):
        m = QMenu(self)
        for kind, label, _tip in TAB_KINDS:
            act = m.addAction(label)
            act.setEnabled(not (kind in CORE_KINDS and self._has_kind(kind)))
            act.triggered.connect(lambda _c=False, k=kind: self.add_tab(k))
        m.addSeparator()
        m.addAction('📝 再加一个便签').triggered.connect(lambda: self.add_tab('note'))
        m.exec(self.btn_add.mapToGlobal(self.btn_add.rect().bottomLeft()))

    def _has_kind(self, kind):
        return any(t['kind'] == kind for t in self._tabs)

    def _index_of_kind(self, kind):
        for i, t in enumerate(self._tabs):
            if t['kind'] == kind:
                return i
        return -1

    def add_tab(self, kind, title=None, text=None, switch=True):
        if kind not in KIND_LABEL:
            return None
        tab = {'id': '%s%d' % (kind, int(time.time() * 1000) % 100000), 'kind': kind}
        # 撞号防护：上面这个 id 是「毫秒数 % 100000」——100 秒一循环。
        # 同一进程里连建两个便签、或历史页签恰好同余，就会撞。
        # 撞了之后 _note_editors 只能记住一个编辑框，另一个永远同步不到
        # （实测见过 "Internal C++ object already deleted"，2026-10-25）。
        _used = {str(t.get('id')) for t in self._tabs}
        if tab['id'] in _used:
            _i = 2
            while '%s-%d' % (tab['id'], _i) in _used:
                _i += 1
            tab['id'] = '%s-%d' % (tab['id'], _i)
        if kind in CORE_KINDS and self._has_kind(kind):
            return None
        # v6.66 fix：除便签外不允许重复 —— “状态/花费/待办/系统”是全局同一份信息，
        # 加两个只会重复显示、白占位置；已存在就切过去并给一句说明（使用者反馈过这个）。
        if kind != 'note' and self._has_kind(kind):
            idx = self._index_of_kind(kind)
            if 0 <= idx < self.tabbar.count():
                self.tabbar.setCurrentIndex(idx)      # 先切过去（切页签会把提示刷成默认说明）
            self.hint.setText('“%s”已经有了（只有便签可以开多个）' % KIND_LABEL.get(kind, kind))
            return None
        if title:
            tab['title'] = title[:18]
        if kind == 'note':
            tab['text'] = text or ''
        self._tabs.append(tab)
        w = self._make_widget(tab)
        self.stack.addWidget(w)
        self.tabbar.addTab(tab_text(tab))
        self.tabbar.setTabToolTip(self.tabbar.count() - 1,
                                  '%s —— %s' % (tab.get('title') or KIND_LABEL[kind],
                                               KIND_TIP.get(kind, '')))
        if switch:
            self.tabbar.setCurrentIndex(self.tabbar.count() - 1)
        self._persist()
        return tab

    def remove_tab(self, index):
        if not (0 <= index < len(self._tabs)):
            return False
        kind = self._tabs[index]['kind']
        if kind in CORE_KINDS:
            return False
        self._tabs.pop(index)
        if not self._tabs:
            self._tabs = [dict(t) for t in DEFAULT_TABS]
            self._build_all()
        else:
            self.tabbar.removeTab(index)
            w = self.stack.widget(index)
            self.stack.removeWidget(w)
            w.deleteLater()
            if index == 0 and self.stack.count():
                self.stack.setCurrentIndex(0)
                self.tabbar.setCurrentIndex(0)
        self._persist()
        return True

    def rename_tab(self, index):
        if not (0 <= index < len(self._tabs)):
            return None
        cur = self._tabs[index].get('title') or KIND_LABEL[self._tabs[index]['kind']]
        txt, ok = QInputDialog.getText(self, '重命名页签', '新名字：', text=cur)
        if not ok or not txt.strip():
            return None
        self._tabs[index]['title'] = txt.strip()[:18]
        self.tabbar.setTabText(index, tab_text(self._tabs[index]))
        self.tabbar.setTabToolTip(index, '%s —— %s' % (
            self._tabs[index]['title'], KIND_TIP.get(self._tabs[index]['kind'], '')))
        self._persist()
        return self._tabs[index]['title']

    def _tab_menu(self, pos):
        idx = self.tabbar.tabAt(pos)
        if idx < 0:
            return
        m = QMenu(self)
        m.addAction('✏ 重命名…').triggered.connect(lambda: self.rename_tab(idx))
        kind = self._tabs[idx]['kind']
        if kind in CORE_KINDS:
            a = m.addAction('（核心页签，不可删除）')
            a.setEnabled(False)
        else:
            m.addAction('🗑 删除这个页签').triggered.connect(lambda: self.remove_tab(idx))
        m.exec(self.tabbar.mapToGlobal(pos))

    # ---------------- 折叠 / 持久化 ----------------
    @property
    def collapsed(self):
        return self._collapsed

    def set_collapsed(self, flag, notify=True):
        self._collapsed = bool(flag)
        self._apply_collapsed()
        if not self._collapsed:
            self.refresh_dynamic(force=True)      # 展开后立即填内容，不等 2 秒定时器
        if notify:
            self._persist()

    def _apply_collapsed(self):
        """折叠：真的把面板收窄（只留一个把手），而不是“藏控件但还占着宽度”

        v6.66 fix：使用者反馈“点収进去后是一整块空面板、还把聊天盖住了” —— 根因是
        折叠只做了 setVisible(False)，但 QFrame 仍然 setFixedWidth(186) → 留了一大块空白。
        """
        show = not self._collapsed
        for w in (self.tabbar, self.stack, self.hint, self.lb_head):
            w.setVisible(show)
        if 'btn_add' in self.__dict__:
            self.btn_add.setVisible(show)
        self.collapse_btn.setText('▶' if self._collapsed else '◀')
        # ★ 宽度才是关键：折叠 → 24px（只够一个把手）；展开 → 原宽
        try:
            self.setFixedWidth(COLLAPSED_W if self._collapsed else self._width)
        except Exception:
            pass
        self.setVisible(True)

    def _persist(self):
        if self._save_cb:
            try:
                self._save_cb([dict(t) for t in self._tabs], self._collapsed)
            except Exception:
                pass

    def dump_tabs(self):
        return [dict(t) for t in self._tabs]

    # ---------------- 数据刷新 ----------------
    def _on_tab_changed(self, index):
        if 0 <= index < len(self._tabs):
            kind = self._tabs[index]['kind']
            self.lb_head.setText(self._tabs[index].get('title') or KIND_LABEL.get(kind, '信息栏'))
            self.hint.setText(KIND_TIP.get(kind, ''))
            # ★ v6.66 fix：以前只改标题和底部说明，**从来没切内容区** —— 点“状态”时
            # 标题写着“状态”、底下一行也是状态的说明，但内容区永远停在任务页
            # （没任务时任务页就是一块空白）→ 使用者看到“内容一片空”。
            if 0 <= index < self.stack.count():
                self.stack.setCurrentIndex(index)
            self.refresh_dynamic(force=True)

    def refresh_tasks(self, cur_text, queue):
        """宿主刷新任务：首行 = 执行中，其后排队（可拖拽）"""
        if self._tasks_list is None:
            return
        try:
            self._tasks_list.clear()
            if cur_text:
                it = QListWidgetItem('⏳ ' + str(cur_text)[:13])
                it.setFlags(it.flags() & ~Qt.ItemIsDropEnabled & ~Qt.ItemIsDragEnabled)
                self._tasks_list.addItem(it)
            for i, t in enumerate(queue or []):
                it = QListWidgetItem('⏸ %d. %s' % (i + 1, str((t or {}).get('text', ''))[:13]))
                it.setData(Qt.UserRole, t)
                self._tasks_list.addItem(it)
            if self._tasks_list.count() == 0:
                # 空的时候给一句说明，而不是一大块空白（使用者反馈“看着就是一整块空的”）
                it = QListWidgetItem('（暂无任务）\n发消息后若还在忙，就会排在这里')
                it.setFlags(Qt.NoItemFlags)
                self._tasks_list.addItem(it)
        except Exception:
            pass

    # ---------------- 便签（供 3.0 主区「便签长文」用）----------------

    def note_tabs(self):
        """便签页签的副本（主区便签面板读这里）

        ⛔ 主区不另存一份 —— 两端必须是同一条数据，否则侧栏改了主区看不见。
        """
        return [dict(t) for t in self._tabs if t.get('kind') == 'note']

    def set_note_text(self, note_id, text):
        """改便签正文（主区编辑后回写）。返回是否命中。

        ⛔ 不调 _build_all 重建：那会丢掉使用者正在输入的焦点与滚动位置。
        这里只把 tab['text'] 改掉，并同步侧栏那个编辑框（顺带屏蔽信号，
        否则 textChanged 又回调 _on_note_changed，来回多存一次盘）。
        """
        body = str(text or '')[:4000]
        for t in self._tabs:
            if t.get('id') == note_id and t.get('kind') == 'note':
                t['text'] = body
                ed = self._note_editors.get(note_id)
                if ed is not None:
                    try:
                        if ed.toPlainText() != body:
                            ed.blockSignals(True)
                            ed.setPlainText(body)
                            ed.blockSignals(False)
                    except RuntimeError as exc:
                        # 控件已随页签销毁（Qt 对象没了）：数据已改好，把死引用清掉，
                        # 否则每次 set 都白报一遍，而那条便签的侧栏编辑框永远不同步。
                        self._note_editors.pop(note_id, None)
                        _silent_note('set_note_text 同步编辑框失败（已清掉死引用）：%r %s'
                                     % (note_id, exc))
                self._persist()
                return True
        return False

    def set_note_title(self, note_id, title):
        """按 id 改便签标题（3.0 主区改名用）。返回是否命中。

        为什么加它：主区 NotePanel 手里只有 note_id，没有 tab index；
        而侧栏现有的是 rename_tab(index) —— 主区调不了（2026-10-29 实测）。

        - 传空字符串 = **清掉标题**，回到「用正文第一行当名字」
          （note_panel 的列表就是这么兜底的；清空要能还原，否则改错了没法退）
        - 上限 18 字，与 rename_tab 同一口径。⛔ 两处不一致会让侧栏页签显示
          和主区输入框里的字不一样 —— 使用者会以为没存上。
        """
        t_ = str(title or '').strip()[:18]
        for i, t in enumerate(self._tabs):
            if t.get('id') == note_id and t.get('kind') == 'note':
                if t_:
                    t['title'] = t_
                else:
                    t.pop('title', None)
                # 侧栏那个页签要立刻跟着变，否则「主区改了侧栏不认」
                if 0 <= i < self.tabbar.count():
                    self.tabbar.setTabText(i, tab_text(t))
                    self.tabbar.setTabToolTip(
                        i, '%s —— %s' % (t.get('title') or KIND_LABEL.get('note', ''),
                                         KIND_TIP.get('note', '')))
                self._persist()
                return True
        return False

    def remove_note(self, note_id):
        """按 id 删便签（3.0 主区删除用）。返回是否真的删了。

        ⛔ 只认 kind == 'note'：不许用这个方法误删任务/状态等核心页签
          （CORE_KINDS 里只有 tasks，这里条件更窄，是双保险）。
        复用 remove_tab，不重复实现「删光回退默认页签」那套逻辑。
        """
        for i, t in enumerate(self._tabs):
            if t.get('id') == note_id and t.get('kind') == 'note':
                return self.remove_tab(i)
        return False

    def refresh_dynamic(self, force=False):
        """刷新状态/花费/待办/系统页

        force=True 时忽略“折叠/不可见”的省开销判断 —— 展开、切页签、窗口刚显示时必须
        立刻填内容，不能停在占位符上（使用者反馈过“内容一直是 …”）。
        """
        if not force and (self._collapsed or not self.isVisible()):
            return
        try:
            data = self._data_cb() or {}
        except Exception:
            data = {}
        for i, tab in enumerate(self._tabs):
            kind = tab['kind']
            if kind in ('tasks', 'note'):
                continue
            w = self.stack.widget(i)
            if not isinstance(w, QLabel):
                continue
            try:
                w.setText(self._text_for(kind, data))
            except Exception:
                w.setText('—')

    def _text_for(self, kind, data):
        if kind == 'status':
            return ('今日：%s 次 · %s tok · ¥%s\n'
                    '余额：%s\n'
                    '模型：%s\n声线：%s\n时段：%s\n好感：%s\n饱食：%s%s'
                    % (data.get('today_count', 0), data.get('today_tokens', '—'),
                       data.get('today_cost', '0.0000'), data.get('balance', '未查询'),
                       data.get('model', '—'), data.get('voice', '—'),
                       data.get('peak', '—'), data.get('affection', '—'),
                       data.get('satiety', '—'),
                       '（饿了，喂点东西）' if data.get('satiety_low') else ''))
        if kind == 'cost':
            return ('今日：¥%s（%s 次）\n累计：¥%s（%s 次）\n未计入：%s 次\n最近：%s\n\n%s'
                    % (data.get('today_cost', '0.0000'), data.get('today_count', 0),
                       data.get('total_cost', '0.0000'), data.get('total_count', 0),
                       data.get('unknown', 0), data.get('last', '—'),
                       data.get('hint', '')))
        if kind == 'todo':
            items = data.get('todos') or []
            if not items:
                return '当前没有待办事项\n\n（让桌宠加一条，或在设置 → 记忆与数据 里管理）'
            return '\n'.join(('✅ ' if t.get('done') else '⬜ ') + str(t.get('text', ''))[:24]
                             for t in items[:12]) + ('\n…' if len(items) > 12 else '')
        if kind == 'system':
            return ('CPU：%s 核\n内存：%s\n运行：%s\n版本：%s'
                    % (data.get('cpu', '—'), data.get('mem', '—'),
                       data.get('uptime', '—'), data.get('version', '—')))
        return ''
