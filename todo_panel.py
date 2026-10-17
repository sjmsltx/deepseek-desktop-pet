"""任务面板：待办清单控件（可装进 QDockWidget，也可装在对话框里）

抽取自 desktop_pet.py 的 `_open_todo_manager`，为 3.0 大界面「一个窗口两种布局」做准备。

设计要点
--------
**所有回调的数据定位一律用条目 id，不用表格行号。**

理由：
  对话框是「打开—刷新—销毁」的闭环，行号与列表索引在每一步都同步，
  所以历史上用 `self.todos[row]` 从不出错；
  但常驻面板存在「外部改动窗口」——AI 通过 `_manage_todo('add', ...)` 在别处
  改了 todos，面板收不到任何通知，表格没重建 ⇒ 行号与索引错位 ⇒
  用户点「A 写周报」实际勾中「X 老板临时加的」，**静默无报错**。

依赖注入（todos 列表引用 + 保存回调），便于脱离主程序单测。
"""

import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLineEdit, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

#: 把条目 id 存在每个单元格里，回调按 id 定位数据
ID_ROLE = Qt.UserRole


class TodoPanel(QWidget):
    """待办面板。

    Args:
        todos: 待办列表（**与主程序共享同一个 list 对象**，本类就地修改）
        save_cb: 保存回调（通常是主程序的 `_save_todos`）
        labels: i18n 文案映射，缺省项用中文兜底
        parent: 父控件
    """

    #: 数据变动后发出，外部可据此刷新其他视图
    changed = Signal()

    def __init__(self, todos, save_cb, labels=None, parent=None):
        super().__init__(parent)
        self.todos = todos
        self._save = save_cb
        self._L = labels or {}

        def g(key, default):
            return self._L.get(key, default)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        # ---- 表格：状态 / 内容 / 时间 ----
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([
            g('status', '状态'), g('content', '内容'), g('time', '时间')])
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 70)
        self.table.setColumnWidth(2, 110)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.cellDoubleClicked.connect(self._on_toggle)
        lay.addWidget(self.table, 1)

        # ---- 输入行 ----
        top = QHBoxLayout()
        self.inp = QLineEdit()
        self.inp.setPlaceholderText(g('placeholder', '记一笔待办…'))
        self.inp.returnPressed.connect(self._on_add)
        b_add = QPushButton(g('add', '添加'))
        b_add.clicked.connect(self._on_add)
        top.addWidget(self.inp, 1)
        top.addWidget(b_add)
        lay.addLayout(top)

        # ---- 操作行 ----
        bottom = QHBoxLayout()
        for text, slot in ((g('done', '完成'), self._on_done_selected),
                           (g('del', '删除'), self._on_del_selected),
                           (g('clear', '清空已完成'), self._on_clear_done)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            bottom.addWidget(b)
        bottom.addStretch(1)
        lay.addLayout(bottom)

        self.refresh()

    # ================= 数据定位（核心） =================

    def _todo_by_id(self, tid):
        """按稳定 id 找条目。找不到返回 None。

        ⛔ 绝不退回用行号 —— 行号在常驻面板下会错位（见模块 docstring）。
        """
        if not tid:
            return None
        for t in self.todos:
            if t.get('id') == tid:
                return t
        return None

    def _ensure_ids(self):
        """给没有 id 的条目补一个（兼容早期数据）。返回是否发生过改动。"""
        changed = False
        now_ms = int(datetime.datetime.now().timestamp() * 1000)
        for i, t in enumerate(self.todos):
            if not t.get('id'):
                t['id'] = 't%d_%d' % (now_ms, i)
                changed = True
        return changed

    def _id_at_row(self, row):
        """取某行对应的条目 id（三个单元格都存了，取第一个即可）"""
        item = self.table.item(row, 0)
        return item.data(ID_ROLE) if item is not None else None

    def _selected_ids(self):
        """当前选中的条目 id 列表（去重，保持行序）"""
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [tid for tid in (self._id_at_row(r) for r in rows) if tid]

    def _persist(self):
        """保存并通知外部。

        本层**不做 try/except**：`_save` 由调用方注入，主程序的 `_save_todos`
        自己会记录日志并向用户提示（见 desktop_pet.py）。在本层再包一层只会
        把问题吞掉，且属于项目护栏明确禁止的静默点。
        """
        self._save()
        self.changed.emit()

    # ================= 表格重建 =================

    def refresh(self):
        """按当前 todos 重建表格。

        外部改动 todos 后应调用本方法（常驻面板必须能被外部刷新）。
        """
        if self._ensure_ids():
            self._persist()
        self.table.setRowCount(0)
        for t in self.todos:
            r = self.table.rowCount()
            self.table.insertRow(r)
            tid = t.get('id')
            cells = ('✅' if t.get('done') else '⬜',
                     t.get('text', ''),
                     t.get('created', ''))
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(ID_ROLE, tid)
                self.table.setItem(r, c, item)

    # ================= 操作 =================

    def _on_toggle(self, row, col=0):
        """双击切换完成状态（按 id 定位）"""
        todo = self._todo_by_id(self._id_at_row(row))
        if todo is None:
            # 表格与数据不同步（外部刚改过）⇒ 重建，让用户重新点
            self.refresh()
            return
        todo['done'] = not todo.get('done', False)
        self._persist()
        self.refresh()

    def add_text(self, text):
        """新增一条待办。空文本返回 False。"""
        text = (text or '').strip()
        if not text:
            return False
        now = datetime.datetime.now()
        self.todos.append({
            'id': 't%d' % int(now.timestamp() * 1000),
            'text': text,
            'done': False,
            'created': now.strftime('%m-%d %H:%M'),
        })
        self._persist()
        self.refresh()
        return True

    def _on_add(self):
        if self.add_text(self.inp.text()):
            self.inp.clear()

    def _on_done_selected(self):
        ids = self._selected_ids()
        if not ids:
            return
        for tid in ids:
            t = self._todo_by_id(tid)
            if t:
                t['done'] = True
        self._persist()
        self.refresh()

    def _on_del_selected(self):
        ids = self._selected_ids()
        if not ids:
            return
        # 用切片赋值保持列表对象身份（外部可能持有同一个 list 引用）
        self.todos[:] = [t for t in self.todos if t.get('id') not in ids]
        self._persist()
        self.refresh()

    def _on_clear_done(self):
        before = len(self.todos)
        self.todos[:] = [t for t in self.todos if not t.get('done')]
        if len(self.todos) != before:
            self._persist()
            self.refresh()
