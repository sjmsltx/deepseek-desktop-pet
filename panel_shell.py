# -*- coding: utf-8 -*-
"""主区容器（3.0 大界面 · 批 2）

形态（按 WX-094 §3.1 的简化建议）
---------------------------------
默认启动仍是现有桌宠；本容器是**可选打开**的入口窗口。
不做双形态切换状态机、不做停靠拖拽、不做布局记忆 —— 那三样已划到范围外。

本类只做三件事：
  1. 左侧一列按钮（每个注册面板一个）
  2. 右侧内容区（点按钮切换）
  3. 关掉即隐藏，不销毁数据、不影响桌宠

⛔ 不 import desktop_pet：宿主通过构造参数注入，面板通过 panel_registry 提供。
   这样本文件可以脱离主程序单独测试（判据 3/4 的可复算前提）。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

import logging

import panel_registry

_log = logging.getLogger('panel_shell')


class PanelShell(QWidget):
    """装面板的容器窗口。

    Args:
        host: 宿主对象，原样传给 panel_registry 的 factory（面板自己决定用它的什么）
        parent: 父控件
        labels: i18n 文案，缺省中文
    """

    def __init__(self, host, parent=None, labels=None):
        super().__init__(parent)
        self._host = host
        self._L = labels or {}
        self._built = {}          # key -> 控件（懒建，用过的才建）
        self._btns = {}

        self.setWindowTitle(self._L.get('title', '主区'))
        self.resize(720, 480)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        self.lb_hint = QLabel(self._L.get('hint', '这是可选打开的主区；关掉不影响桌面宠物。'), self)
        self.lb_hint.setWordWrap(True)
        outer.addWidget(self.lb_hint)

        body = QHBoxLayout()
        body.setSpacing(8)

        # ---- 左侧按钮列 ----
        left = QVBoxLayout()
        left.setSpacing(4)
        specs = panel_registry.panels()
        for spec in specs:
            b = QPushButton(spec.title, self)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            # 2026-10-29 实测：左列按钮按 sizeHint（84px）排不下「📋 待办管理」，
            # Qt 会折成两行。给个下限，够放最长标题。
            b.setMinimumWidth(112)
            if spec.hint:
                b.setToolTip(spec.hint)
            b.clicked.connect(lambda _=False, k=spec.key: self.show_panel(k))
            left.addWidget(b)
            self._btns[spec.key] = b
        if not specs:
            left.addWidget(QLabel(self._L.get('empty', '还没有注册任何面板'), self))
        left.addStretch(1)
        body.addLayout(left)

        # ---- 右侧内容区 ----
        self.stack = QStackedWidget(self)
        body.addWidget(self.stack, 1)

        outer.addLayout(body, 1)

        if specs:
            self.show_panel(specs[0].key)

    # ================= 对外 =================

    def show_panel(self, key):
        """切到某个面板（首次会建）。返回是否成功。

        2026-10-29：切回一个**已建过**的面板时刷一次数据。
          原先只 setCurrentWidget，不刷新 —— 主区开着不动、从「待办」切到
          「用量分析」，看到的是上次建面板那一刻的数字（用量分析每时都在变，
          这个缺陷被新面板放大成肉眼可见）。
          刚建出来的不刷：建的时候读的就是最新。
        ⚠ 便签不会因此丢字：QStackedWidget 切页会给旧控件发 hideEvent，
          NotePanel.hideEvent 里就是 flush() + flush_title()。
        """
        key = str(key or '')
        if key not in self._btns:
            return False
        w = self._built.get(key)
        fresh = w is None
        if fresh:
            w = panel_registry.build(key, self._host)
            if w is None:
                return False
            self.stack.addWidget(w)
            self._built[key] = w
        self.stack.setCurrentWidget(w)
        for k, b in self._btns.items():
            b.setChecked(k == key)
        if not fresh:
            self.refresh_panel(key)
        return True

    def built_keys(self):
        """已经真正建出来的面板 key（懒建的证据，测试用）"""
        return sorted(self._built.keys())

    def refresh_panel(self, key):
        """只刷某一个已建面板（外部数据变了时用）。返回是否刷到。

        为什么不直接用 refresh_all：便签面板的 refresh 会重读正文，
        连带刷它等于给"正在打字"多一次被覆盖的机会。
        """
        w = self._built.get(str(key or ''))
        fn = getattr(w, 'refresh', None)
        if not callable(fn):
            return False
        try:
            fn()
            return True
        except Exception as _exc:
            # 与 refresh_all 同口径：不许静默，也不能拖垮容器
            _log.warning('面板 %s 的 refresh 失败：%s',
                         getattr(w, '__class__', type(w)).__name__, _exc)
            return False

    def refresh_all(self):
        """把已建出来的面板都刷一遍（外部数据变了时用）。返回刷了几个。"""
        n = 0
        for w in self._built.values():
            fn = getattr(w, 'refresh', None)
            if callable(fn):
                try:
                    fn()
                    n += 1
                except Exception as _exc:
                    # 面板自己的 refresh 抛错不该拖垮整个容器，但**不许静默**
                    # （静默护栏判据：except 里必须落痕）。用标准库记一笔，
                    # 不依赖宿主是否有 _silent_log —— 本文件要能独立导入。
                    _log.warning('面板 %s 的 refresh 失败：%s', getattr(w, '__class__', type(w)).__name__, _exc)
                    continue
        return n

    @staticmethod
    def contract_violations(module_paths):
        """检查面板文件是否违反「不 import 宿主」契约（判据 4）。

        先剥注释与文档字符串再判（2026-10-21 实测踩过）：
            本文件与 panel_registry 的 docstring 里都写着那句话本身，
            按行 grep 会把说明文字判成违规 —— 旧记录里「结构钉 grep 会命中注释」同一条。
            改用 ast 解析，只认真实 import。

        Args:
            module_paths: 面板文件的路径列表
        Returns:
            违规清单 [(path, 命中的行)]；空列表表示全部合格。
        """
        import ast
        bad = []
        for p in module_paths:
            try:
                with open(p, encoding='utf-8') as f:
                    text = f.read()
            except Exception as exc:
                bad.append((p, '读取失败：%s' % exc))
                continue
            try:
                tree = ast.parse(text)
            except SyntaxError as exc:
                bad.append((p, '语法错误，无法校验：%s' % exc))
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        if a.name.split('.')[0] == 'desktop_pet':
                            bad.append((p, 'import %s' % a.name))
                            break
                elif isinstance(node, ast.ImportFrom):
                    mod = (node.module or '').split('.')[0]
                    if mod == 'desktop_pet':
                        bad.append((p, 'from %s import ...' % node.module))
        return bad
