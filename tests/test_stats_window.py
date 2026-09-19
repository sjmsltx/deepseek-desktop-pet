# -*- coding: utf-8 -*-
"""API 统计悬浮窗护栏（v6.62 修 bug）

复现的两条反馈：
① 打开悬浮窗后「拖不动、直接卡死」—— 内容（后来加的余额行/来源行）装不下 320×142 的写死窗口，
   布局被挤压；且拖拽只挂在 panel 上，抓到按钮/边缘就完全拖不动，用户体感＝卡死。
② 余额查询 404 —— 见 tests/test_balance.py 的 normalize_base 用例。

这里锁住：尺寸必须容得下内容、任意位置可拖、拖动期间暂停刷新、松手记住位置。

运行：python -m pytest tests/test_stats_window.py -q
"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PySide6.QtCore import QEvent, QPointF, Qt, QTimer          # noqa: E402
from PySide6.QtGui import QMouseEvent, QFontMetrics             # noqa: E402
from PySide6.QtWidgets import (QApplication, QLabel,             # noqa: E402
                               QProgressBar, QPushButton, QWidget)


def _win():
    QApplication.instance() or QApplication(sys.argv)
    import desktop_pet as dp
    p = dp.PetWidget()
    saved = []
    p._save_cfg_value = lambda k, v: (saved.append((k, v)), True)[1]
    p._toggle_api_stats_window()
    win = p._api_stats_win
    panel = [c for c in win.children() if isinstance(c, QWidget) and c.objectName() == 'ap'][0]
    return p, win, panel, saved


def _fat_content(p):
    """塞入最胖的内容：余额缓存 + 多来源 + 长模型名"""
    p.api_stats.balance = {'ok': True, 'total': 68.75, 'granted': 0.0, 'topped_up': 68.75,
                           'currency': 'CNY', 'at': '2026-09-19 20:30:00', 'is_available': True}
    p.api_stats.today['by_app'] = {'桌宠': {'count': 12, 'total': 34567},
                                   '其他app名字很长很长很长': {'count': 3, 'total': 1234},
                                   '第三个来源': {'count': 1, 'total': 99}}
    p.api_stats.last = {'model': 'deepseek-flash-特别长的模型标识', 'prompt': 123456,
                        'completion': 2345, 'cost': 0.0123, 'price_unknown': False}
    for t in p._api_stats_win.findChildren(QTimer):
        if t.isActive():
            t.timeout.emit()


def test_window_fits_content():
    p, win, panel, _ = _win()
    lay = panel.layout()
    assert lay.minimumSize().width() <= win.width(), '内容宽度不得超出窗口（否则挤压/抖动）'
    assert lay.minimumSize().height() <= win.height(), '内容高度不得超出窗口'


def test_window_fits_even_with_fat_content():
    p, win, panel, _ = _win()
    _fat_content(p)
    lay = panel.layout()
    assert lay.minimumSize().width() <= win.width()
    assert lay.minimumSize().height() <= win.height()
    # 长行必须被按像素收口（省略号），而不是把窗口顶宽
    app_lbl = [c for c in panel.findChildren(QLabel) if c.text().startswith('来源')][0]
    fm = QFontMetrics(app_lbl.font())
    assert fm.horizontalAdvance(app_lbl.text()) <= win.width()


def test_drag_works_from_any_spot():
    """标题、数据行、进度条、空白处都要能拖（原先只有 panel 能拖）"""
    p, win, panel, saved = _win()
    targets = [('标题', panel.findChildren(QLabel)[0]),
               ('数据行', panel.findChildren(QLabel)[3]),
               ('进度条', panel.findChildren(QProgressBar)[0]),
               ('空白', panel)]
    for name, w in targets:
        before = (win.x(), win.y())

        def ev(kind, gx, gy, btn=Qt.LeftButton, buttons=Qt.NoButton):
            return QMouseEvent(kind, QPointF(5.0, 5.0), QPointF(float(gx), float(gy)),
                               btn, buttons, Qt.NoModifier)

        gx, gy = before[0] + 100, before[1] + 50
        QApplication.sendEvent(w, ev(QEvent.MouseButtonPress, gx, gy, buttons=Qt.LeftButton))
        QApplication.sendEvent(w, ev(QEvent.MouseMove, gx + 40, gy + 30, Qt.NoButton, Qt.LeftButton))
        QApplication.sendEvent(w, ev(QEvent.MouseButtonRelease, gx + 40, gy + 30, Qt.LeftButton))
        assert (win.x(), win.y()) != before, '从【%s】拖动无效' % name
    assert any(k == 'stats_win_pos' for k, _ in saved), '松手后应记住位置'


def test_button_click_not_swallowed_by_drag():
    """按钮要保留点击语义（拖动过滤器不能吃掉它的按压）"""
    p, win, panel, _ = _win()
    btn = [b for b in panel.findChildren(QPushButton) if '查询' in b.text()][0]
    before = (win.x(), win.y())
    gx, gy = before[0] + 60, before[1] + 120

    def ev(kind, x, y, btn_, buttons):
        return QMouseEvent(kind, QPointF(5.0, 5.0), QPointF(float(x), float(y)),
                           btn_, buttons, Qt.NoModifier)

    QApplication.sendEvent(btn, ev(QEvent.MouseButtonPress, gx, gy, Qt.LeftButton, Qt.LeftButton))
    QApplication.sendEvent(btn, ev(QEvent.MouseButtonRelease, gx, gy, Qt.LeftButton, Qt.NoButton))
    assert (win.x(), win.y()) == before, '在按钮上按住拖动不应移动窗口'


def test_refresh_timer_paused_while_dragging():
    """拖动时暂停 1 秒刷新（避免刷新与移动互相干扰），松手恢复"""
    p, win, panel, _ = _win()
    timer = [t for t in win.findChildren(QTimer) if t.isActive()][0]
    gx, gy = win.x() + 100, win.y() + 50

    def ev(kind, x, y, btn_, buttons):
        return QMouseEvent(kind, QPointF(5.0, 5.0), QPointF(float(x), float(y)),
                           btn_, buttons, Qt.NoModifier)

    QApplication.sendEvent(panel, ev(QEvent.MouseButtonPress, gx, gy, Qt.LeftButton, Qt.LeftButton))
    assert not timer.isActive(), '拖动期间应暂停刷新'
    QApplication.sendEvent(panel, ev(QEvent.MouseButtonRelease, gx, gy, Qt.LeftButton, Qt.NoButton))
    assert timer.isActive() and timer.interval() == 1000, '松手后应恢复刷新'


def test_balance_line_is_short_with_full_tooltip():
    """余额行文案要短（不撑宽），完整信息放 tooltip"""
    p, win, panel, _ = _win()
    _fat_content(p)
    bal = [c for c in panel.findChildren(QLabel) if c.text().startswith('余额')][0]
    assert '赠金' not in bal.text(), '赠金/充值明细不该放在行内（会撑宽窗口）'
    assert '赠金' in (bal.toolTip() or ''), '完整信息应进 tooltip'


if __name__ == '__main__':
    import pytest
    raise SystemExit(pytest.main([__file__, '-q']))
