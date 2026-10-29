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

from PySide6.QtCore import Qt, QTimer
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

    #: 最小可用尺寸。实测（2026-10-29）：Qt 默认给的是 418×158，
    #: 那个高度连「顶部提示 + 左列三个按钮」都放不下。这里按内容反推：
    #: 宽 = 左列按钮 112 + 间距 8 + 内容区 ≥420 + 边距 16；高 = 提示行 + 三个按钮 + 内容区 ≥220。
    MIN_SIZE = (560, 340)
    #: 默认打开尺寸（没用过/配置里没有时）
    DEFAULT_SIZE = (720, 480)
    #: 改大小后多久落盘。⛔ 宿主 _save_cfg_value 会热加载配置，
    #: 拖拽每秒触发几十次 resizeEvent，不防抖等于每秒热加载几十次。
    SAVE_DELAY_MS = 800

    def __init__(self, host, parent=None, labels=None, size_cb=None,
                 initial_size=None, initial_maximized=False):
        """Args:
            size_cb: (w, h, maximized) -> None，尺寸变了叫一次（防抖后）。
                     ⛔ 不传就不上报，但仍然可以拖拽改大小。
            initial_size: (w, h) 上次的尺寸；None 用 DEFAULT_SIZE
            initial_maximized: 上次是不是最大化
        """
        super().__init__(parent)
        self._host = host
        self._L = labels or {}
        self._built = {}          # key -> 控件（懒建，用过的才建）
        self._btns = {}
        self._size_cb = size_cb
        self._size_ready = False      # 首次 show 之前不上报，免得把配置冲掉

        self.setWindowTitle(self._L.get('title', '主区'))
        # 可拖拽改大小：不设 fixed size，只给一个合理下限
        # （实测：Qt 默认下限 418×158，那个高度基本没法用）
        self.setMinimumSize(*self.MIN_SIZE)
        w, h = self._norm_size(initial_size)
        self.resize(w, h)
        if initial_maximized:
            self.setWindowState(self.windowState() | Qt.WindowMaximized)

        self._size_timer = QTimer(self)
        self._size_timer.setSingleShot(True)
        self._size_timer.setInterval(self.SAVE_DELAY_MS)
        self._size_timer.timeout.connect(self._report_size)

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

    # ================= 尺寸记忆（2026-10-29）=================

    @classmethod
    def _norm_size(cls, size):
        """把配置里读出来的尺寸洗成合法值。

        ⛔ 越界不报错、直接夹到可用范围：手改坏的 config 不该让主区打不开。
        """
        try:
            w, h = int(size[0]), int(size[1])
        except (TypeError, ValueError, IndexError, KeyError):
            return cls.DEFAULT_SIZE
        lo_w, lo_h = cls.MIN_SIZE
        # 上限按「屏幕可用区」夹：移到小屏上时不至于开出一个够不着的窗口
        from PySide6.QtWidgets import QApplication
        scr = QApplication.primaryScreen()
        max_w = max(lo_w, scr.availableGeometry().width()) if scr else 3840
        max_h = max(lo_h, scr.availableGeometry().height()) if scr else 2160
        return (min(max(w, lo_w), max_w), min(max(h, lo_h), max_h))

    def current_size(self):
        """当前该记下来的尺寸 —— 最大化时记还原后的那个

        ⛔ 不能记 geometry()：最大化时它是整屏，下次打开会变成一个
          「占满屏但还是普通窗口」的东西（边框在屏外，拖都拖不动）。
        """
        if self.isMaximized():
            g = self.normalGeometry()
        else:
            g = self.geometry()
        return (g.width(), g.height())

    def _report_size(self):
        if not callable(self._size_cb) or not self._size_ready:
            return
        try:
            w, h = self.current_size()
            self._size_cb(w, h, bool(self.isMaximized()))
        except Exception as _exc:
            _log.warning('上报窗口尺寸失败（不影响使用）：%s', _exc)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self._size_ready:
            self._size_timer.start()

    def showEvent(self, ev):
        super().showEvent(ev)
        # 首帧布局稳定后才允许上报（否则构造期的 resize 会立刻把配置写成默认值）
        if not self._size_ready:
            self._size_ready = True

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
