# -*- coding: utf-8 -*-
"""chat_trace.py — 思考过程的树形折叠控件（2026-11-06）

Owner 要求（原话）：
    「思考过程能不能像你这样自动折叠，分为父子过程，还可以继续下分，
      一个父过程完了，其下的子过程自动收起。」

## 为什么可用父子结构

`reasoning_content` 本身是**一整段连续文本**，没有任何层级信息（模型不会给）。
但 agent 循环有天然结构 —— `_ai_worker` 里最多 5 轮工具调用：

    第 1 轮：推理 → 正文? → 工具调用 → 工具结果
    第 2 轮：推理 → 正文? → 工具调用 → ...
    ...
    最终轮：推理 → 正文（最终回复）

⇒ **轮次就是父过程，工具调用就是它下面的子过程**，继续下分还能放工具结果。
这不需要模型配合，也不需要新造语义。

## 「自动收起」的落点

父节点收起时，其下的子节点自然不可见（Qt 父子控件天然如此，不用逐个收起）。
所以只需在**父过程完成时把父节点收起**，就同时满足「子过程自动收起」。

## 本模块不依赖 desktop_pet

只吃注入的 `style_cb(self) -> str`（返回 QSS 文本），不 import 任何产品模块。
这样它能被单独导入、单独验收（panel/skill 契约同口径）。
"""
import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QToolButton, QVBoxLayout, QWidget

_log = logging.getLogger('pet.chat_trace')

#: 子节点左侧缩进（每层 +INDENT px）
INDENT = 12


class TraceNode(QWidget):
    """一个可折叠的思考过程节点（父/子通用，可继续下分）

    结构：
        [▼ 标题 ................ 摘要]      ← QToolButton（点它折叠/展开）
        └ 内容区（可隐藏）
            ├ 文本标签（推理原文 / 工具结果）
            └ 子节点们（递归）
    """

    def __init__(self, title, parent=None, expanded=True, level=0, style_cb=None):
        super().__init__(parent)
        self._level = int(level)
        self._expanded = bool(expanded)
        self._summary = ''
        self._title = str(title or '')
        self._style_cb = style_cb
        self._children = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(INDENT * self._level, 0, 0, 0)
        lay.setSpacing(1)

        self._btn = QToolButton(self)
        self._btn.setCheckable(False)
        self._btn.setAutoRaise(True)
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.setStyleSheet(
            'QToolButton { background:transparent; border:none; padding:0;'
            ' font-size:11px; text-align:left; }')
        self._btn.clicked.connect(self.toggle)
        lay.addWidget(self._btn)

        self._body = QWidget(self)
        body_lay = QVBoxLayout(self._body)
        body_lay.setContentsMargins(INDENT, 0, 0, 0)
        body_lay.setSpacing(1)

        self._label = QLabel('', self._body)
        self._label.setWordWrap(True)
        self._label.setTextFormat(Qt.PlainText)
        self._label.setVisible(False)      # 没内容不占位
        if style_cb:
            try:
                self._label.setStyleSheet(style_cb(self._label))
            except Exception as exc:
                _log.warning('TraceNode 文本样式注入失败：%s', exc)
        body_lay.addWidget(self._label)

        self._child_box = QVBoxLayout()
        self._child_box.setContentsMargins(0, 0, 0, 0)
        self._child_box.setSpacing(1)
        body_lay.addLayout(self._child_box)

        lay.addWidget(self._body)
        self._refresh_head()
        self._body.setVisible(self._expanded)

    # ---------------- 头部 ----------------
    def _refresh_head(self):
        arrow = '▼' if self._expanded else '▶'
        tail = ('  ' + self._summary) if self._summary else ''
        self._btn.setText('%s %s%s' % (arrow, self._title, tail))
        self._btn.setToolTip(self._title + (('\n' + self._summary) if self._summary else ''))

    @property
    def title(self):
        return self._title

    @property
    def summary(self):
        return self._summary

    def set_title(self, title):
        self._title = str(title or '')
        self._refresh_head()

    def set_summary(self, text):
        """右侧摘要（耗时 / 工具名 / 「3 步」这类）"""
        self._summary = str(text or '')
        self._refresh_head()

    # ---------------- 折叠 ----------------
    @property
    def expanded(self):
        return self._expanded

    def set_expanded(self, on):
        self._expanded = bool(on)
        self._body.setVisible(self._expanded)
        self._refresh_head()

    def toggle(self):
        self.set_expanded(not self._expanded)

    @property
    def button(self):
        """折叠按钮（测试点它用）"""
        return self._btn

    # ---------------- 内容 ----------------
    @property
    def label(self):
        """本节点的文本标签（QLabel；`.text()` 读内容）"""
        return self._label

    def text(self):
        return self._label.text()

    def append_text(self, chunk):
        """追加文本（流式用）。首次追加时自动显示标签。

        ⚠ 不能靠 `isVisible()` 判断该不该显示 —— 它依赖整条祖先链已 show 且事件循环跑过，
        在构造/离屏场景下会返回 False，导致「有内容却一直不显示」（实测 2026-11-06）。
        有内容就直接显式设为可见。
        """
        s = str(chunk or '')
        if not s:
            return
        self._label.setText(self._label.text() + s)
        self._label.setVisible(True)

    def set_text(self, text):
        self._label.setText(str(text or ''))
        self._label.setVisible(bool(self._label.text()))

    # ---------------- 子节点 ----------------
    def add_child(self, title, expanded=False, summary=''):
        """加一个子节点（level 自动 +1），返回它"""
        node = TraceNode(title, parent=self._body, expanded=expanded,
                         level=self._level + 1, style_cb=self._style_cb)
        self._child_box.addWidget(node)
        self._children.append(node)
        if summary:
            node.set_summary(summary)
        return node

    @property
    def children(self):
        return list(self._children)

    def child_count(self):
        return len(self._children)

    def iter_children(self):
        """递归遍历所有后代（含自己）"""
        yield self
        for c in self._children:
            yield from c.iter_children()

    def full_text(self):
        """本节点及其所有子孙的文本（按顺序拼，便于「思考全文」类展示）"""
        parts = []
        if self._label.text():
            parts.append(self._label.text())
        for c in self._children:
            t = c.full_text()
            if t:
                parts.append(t)
        return '\n'.join(parts)

    def visible_text(self):
        """只算当前可见部分（父收起时子不可见）

        判据用 `expanded` 而不是 `isVisible()` —— 后者依赖祖先链已显示，
        在离屏/未 layout 场景下不可靠（同 append_text 的坑）。
        """
        if not self._expanded:
            return ''
        parts = []
        if self._label.text() and self._label.isVisible():
            parts.append(self._label.text())
        for c in self._children:
            t = c.visible_text()
            if t:
                parts.append(t)
        return '\n'.join(parts)


class TraceTree(QWidget):
    """思考过程的根容器：一个根节点 + 若干轮次节点

    用法（由宿主驱动）：
        tree = TraceTree(style_cb=...)
        r1 = tree.begin_round(1)              # 第 1 轮
        r1.append_text('先查天气…')            # 推理流式追加
        tool = r1.add_child('query_weather')  # 工具调用
        tool.set_text('多云 24℃')             # 工具结果
        tree.end_round(1, seconds=1.8)        # 该轮完成 → 收起
        tree.finish()                         # 整棵树完成 → 根收起
    """

    def __init__(self, parent=None, title='💭 思考过程', style_cb=None,
                 node_style_cb=None, on_expand_changed=None):
        """on_expand_changed(tree)：根节点展开态变化时回调，参数是**本棵树**

        用途：宿主的「思考过程 ▼」按钮在树外面（为了保持既有文案），
        它必须与树的真实状态保持一致 —— 否则从代码里收起后，
        按钮还显示 ▼，用户点一下反而「更收起」（实测 2026-11-06）。

        ⚠ 参数必须是树而不是 bool：一个气泡一棵树，回调里若取「宿主的当前按钮」
        会拿到**最新气泡**的按钮 —— 点旧气泡会改到新气泡（regression_test B3 实测）。
        """
        super().__init__(parent)
        self._style_cb = node_style_cb
        self._on_expand_changed = on_expand_changed
        #: 宿主绑定：本树所属气泡的折叠按钮 / 摘要 label（由宿主建好后赋值）
        self.owner_toggle = None
        self.owner_summary = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.root = TraceNode(title, parent=self, expanded=True, level=0,
                              style_cb=node_style_cb)
        lay.addWidget(self.root)
        self._rounds = {}          # {轮号: TraceNode}
        self._order = []           # 轮号顺序
        if style_cb:
            try:
                self.setStyleSheet(style_cb(self))
            except Exception as exc:
                _log.warning('TraceTree 样式注入失败：%s', exc)

    # ---------------- 根 ----------------
    @property
    def toggle_button(self):
        """根节点的折叠按钮（宿主把它当「思考过程 ▼」用）"""
        return self.root.button

    @property
    def root_label(self):
        return self.root.label

    def set_expanded(self, on):
        """收起/展开根节点；变化时通知宿主回调（保持外部按钮同步）"""
        changed = (bool(on) != self.root.expanded)
        self.root.set_expanded(bool(on))
        if changed and self._on_expand_changed is not None:
            try:
                self._on_expand_changed(self)     # 传树本身：一个气泡一棵树，宿主据此找对应按钮
            except Exception as exc:
                _log.warning('on_expand_changed 回调失败：%s', exc)

    @property
    def expanded(self):
        return self.root.expanded

    # ---------------- 轮次 ----------------
    def begin_round(self, n):
        """开始第 n 轮（已存在就复用）。返回该轮节点。

        ⚠ 进行中的轮要**展开**：流式期间得能看到实时推理（旧行为）。
        「自动收起」只在结束时的 end_round / finish 发生 —— 先展开后收起，
        才是「父过程完了，其下子过程自动收起」。
        """
        n = int(n)
        if n in self._rounds:
            return self._rounds[n]
        node = self.root.add_child('第 %d 轮推理' % n, expanded=True)
        self._rounds[n] = node
        self._order.append(n)
        return node

    def round_node(self, n):
        return self._rounds.get(int(n))

    def rounds(self):
        """已建的轮节点，按轮号顺序"""
        return [self._rounds[n] for n in self._order]

    def end_round(self, n, seconds=None):
        """该轮完成：写摘要 + **收起该轮**（其下子节点随之不可见）"""
        node = self._rounds.get(int(n))
        if node is None:
            return False
        bits = []
        if seconds is not None:
            bits.append('%.1fs' % float(seconds))
        n_tools = sum(1 for c in node.children
                      if c.title.startswith(('调用', '工具')))
        if n_tools:
            bits.append('%d 次工具' % n_tools)
        node.set_summary(' · '.join(bits))
        node.set_expanded(False)          # ← 「父过程完了，其下子过程自动收起」
        return True

    def finish(self):
        """整棵树完成：写总摘要 + **收起根**（所有轮次一并不再显示）"""
        n = len(self._order)
        n_tools = sum(1 for r in self.rounds() for c in r.children
                      if c.title.startswith(('调用', '工具')))
        bits = ['%d 轮' % n] if n else []
        if n_tools:
            bits.append('%d 次工具' % n_tools)
        self.root.set_summary(' · '.join(bits))
        self.set_expanded(False)          # ← 自动折叠（经 set_expanded 才会通知宿主）
        return True

    def full_text(self):
        return self.root.full_text()

    def visible_text(self):
        return self.root.visible_text()
