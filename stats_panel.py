# -*- coding: utf-8 -*-
"""用量分析面板（3.0 主区 · 2026-10-29）

为什么需要它
------------
Owner 2026-10-29：「主区……感觉现在内容有点少」，选定先加「用量分析」。
判据沿用 10-25 定的那条：**主区只装侧栏 186px 装不下的东西**。
用量分析有按天表格 + 三张图表（按天花费 / 累计构成 / 小时活跃度）+ 六段文字分析，
侧栏那条缝里放不下，720 宽的主区才装得下。

为什么是「包一层」而不是重写界面
------------------------------
`stats_ui.UsageStatsDialog` 已有 18 个方法、三张图表、缓存/峰谷/时段/模型分析。
重写等于造第二个副本 —— 正是本项目反复记过的那类毛病（2026-10-24 日志 §4.3）。
所以这里只做四件事：

  1 `setWindowFlags(Qt.Widget)` 把 QDialog 变成可嵌入的普通控件
     （2026-10-29 实测：设置后 isWindow() → False，跟随父控件尺寸）
  2 外面套 QScrollArea：实测它的内容高 **802px**，主区只有 480px，不套就溢出
  3 藏掉「关闭」按钮（面板归主区容器管，不该自己关自己）
  4 补一条容器背景色（`QDialog { ... }` 选择器在嵌入模式下匹配不到）

契约（panel_registry）
--------------------
· 不 import desktop_pet；只吃注入的 host（用它的 `.api_stats` 与 `.theme`）
· 提供 refresh()，容器切页/重开主区时会调
· 只读：本面板不写任何文件、不改任何统计值（沿用 UsageStatsDialog 的承诺）
"""
import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QPushButton, QScrollArea, QVBoxLayout, QWidget)

_log = logging.getLogger('stats_panel')

#: 这些文字的按钮在面板里藏掉 —— UsageStatsDialog 的「关闭」对它自己是必要的，
#: 对嵌进主区的面板没意义（面板不该自己关自己）。
#: ⛔ 不改 stats_ui.py：设置里那个入口还要用「关闭」。
_HIDE_BTN_TEXT = ('关闭', 'Close')


class StatsPanel(QWidget):
    """用量分析面板：包一层 QScrollArea + 把 QDialog 变成子控件。

    Args:
        host: 宿主，需要 `.api_stats`（统计接口）与 `.theme`（颜色 token）。
              与 UsageStatsDialog 的要求完全一样 —— 本类不加新依赖。
    """

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self._host = host
        self._inner = None
        self._build_ui()

    # ---------------- 界面 ----------------
    def _build_ui(self):
        from stats_ui import UsageStatsDialog

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)      # 内容跟着面板宽度走，不出现横向滚动
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lay.addWidget(self._scroll)

        # ⚠ setWindowFlags 会隐藏控件，必须放在 setWidget 之前 —— 由 QScrollArea 接管显示
        inner = UsageStatsDialog(self._host)
        inner.setWindowFlags(Qt.Widget)
        self._inner = inner
        self._hide_useless_buttons(inner)
        self._scroll.setWidget(inner)
        self._fix_container_bg()

    def _hide_useless_buttons(self, inner):
        """藏掉「关闭」。

        ⛔ 不改 stats_ui.py：它对设置里那个独立窗口是有用的。
        这里只能按文字找 —— `_build` 里的 btn_close 是局部变量，没存成属性
        （这是唯一一处「靠文字认控件」的地方，写在这里备查）。
        """
        try:
            n = 0
            for b in inner.findChildren(QPushButton):
                if b.text().strip() in _HIDE_BTN_TEXT:
                    b.setVisible(False)
                    n += 1
            if n == 0:
                _log.warning('没找到「关闭」按钮 —— stats_ui 的文案可能改了，'
                             '面板里会多出一个点了没用的钮')
        except Exception as exc:
            _log.warning('隐藏关闭按钮失败（不影响使用）：%s', exc)

    def _fix_container_bg(self):
        """`QDialog { background: ... }` 在嵌入模式下匹配不到本控件 → 背景会露底。

        只补一条背景色，别的样式仍由 UsageStatsDialog._apply_theme 提供。
        """
        try:
            th = dict(getattr(self._host, 'theme', None) or {})
            from pet_theme import DEFAULT_THEME
            bg = th.get('dialog_bg') or DEFAULT_THEME.get('dialog_bg')
            if bg:
                self._inner.setStyleSheet(self._inner.styleSheet() +
                                          '\nQWidget { background: %s; }' % bg)
        except Exception as exc:
            # 颜色补不上不影响功能，留痕即可
            _log.warning('补容器背景色失败（用继承色）：%s', exc)

    # ---------------- 对外 ----------------
    def refresh(self):
        """重读统计（容器切页/重开主区时调）。返回是否刷到。"""
        if self._inner is None:
            return False
        try:
            self._inner.reload()
            return True
        except Exception as exc:
            _log.warning('用量分析面板刷新失败：%s', exc)
            return False

    # ---------------- 测试用 ----------------
    def inner(self):
        """暴露内部那个 UsageStatsDialog（测试断言用，不参与业务）"""
        return self._inner
