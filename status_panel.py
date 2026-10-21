# -*- coding: utf-8 -*-
"""状态面板（3.0 大界面 · 批 3）

搬的是什么
----------
原状态页 = `desktop_pet._side_panel_data()`（取数） + `side_panel._text_for('status')`（格式化）。
本批**只搬格式化**，取数仍留在宿主 —— 因为取数那段里有若干 `except: pass` 与
`d['x'] = '—'` 兜底（已在静默护栏基线里）；整块搬进来等于把静默兜底复制进新文件，
基线管不到新文件，等于开一个新的静默入口。

面板契约（判据 4）
------------------
⛔ 不 import desktop_pet。只吃注入的 `data_cb`：
    data_cb() → dict（字段见 FIELDS，缺的按 '—' 显示）

显示口径与侧栏**必须一致**：同一份 data 喂给两边，值要相同。
这条有测试（tests/test_panel_shell.py::test_status_panel_matches_sidebar_values）——
搬移最怕"两边显示不一致"，那比没搬还糟。
"""

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFormLayout, QLabel, QVBoxLayout, QWidget)

#: 要显示的字段（顺序即显示顺序）。左侧标题、右侧取 data 的哪个键、缺省值
FIELDS = (
    ('今日调用', 'today_count', 0),
    ('今日 token', 'today_tokens', '—'),
    ('今日花费', 'today_cost', '0.0000'),
    ('账户余额', 'balance', '未查询'),
    ('当前模型', 'model', '—'),
    ('声线', 'voice', '—'),
    ('峰谷时段', 'peak', '—'),
    ('好感', 'affection', '—'),
    ('饱食度', 'satiety', '—'),
)


class StatusPanel(QWidget):
    """只读状态面板。

    Args:
        data_cb: 无参可调用，返回 dict（宿主注入；面板不知道宿主是谁）
        parent: 父控件
        labels: 预留 i18n（本批只用中文兜底）
    """

    def __init__(self, data_cb, parent=None, labels=None):
        super().__init__(parent)
        self._data_cb = data_cb
        self._L = labels or {}
        self._rows = {}

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        self.lb_hungry = QLabel('', self)
        self.lb_hungry.setWordWrap(True)
        self.lb_hungry.setVisible(False)
        v.addWidget(self.lb_hungry)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(4)
        for title, key, default in FIELDS:
            lb = QLabel(self._fmt(default), self)
            lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
            form.addRow(QLabel(title + '：', self), lb)
            self._rows[key] = (lb, default)
        v.addLayout(form)

        self.lb_hint = QLabel('', self)
        self.lb_hint.setWordWrap(True)
        v.addWidget(self.lb_hint)
        v.addStretch(1)

        self.refresh()

    # ================= 对外 =================

    def refresh(self):
        """重新取数并刷新。取数失败不崩，显示 '—' 并提示。"""
        data = {}
        err = ''
        try:
            data = self._data_cb() or {}
        except Exception as exc:
            # 取数是宿主注入的，它坏了本面板不能跟着崩；
            # 但**不能静默**：护栏判据要求落痕。用标准库 logger，不依赖宿主通道。
            _log.warning('StatusPanel 取数失败：%s', exc)
            err = '%s: %s' % (type(exc).__name__, exc)
        for key, (lb, default) in self._rows.items():
            val = data.get(key, default)
            if val is None or val == '':
                val = default
            lb.setText(self._fmt(val))
        # 饿状态单独提示（原先挤在状态页末尾括号里，容易漏看）
        hungry = bool(data.get('satiety_low'))
        self.lb_hungry.setText('（饿了，喂点东西）' if hungry else '')
        self.lb_hungry.setVisible(hungry)
        self.lb_hint.setText(('取数失败：' + err) if err else str(data.get('hint') or ''))
        self.lb_hint.setVisible(bool(self.lb_hint.text()))
        return data

    def values(self):
        """当前显示值的快照（测试用：与侧栏逐字段比对）"""
        return {k: lb.text() for k, (lb, _d) in self._rows.items()}

    @staticmethod
    def _fmt(v):
        s = str(v)
        return s if s else '—'


_log = logging.getLogger('status_panel')
