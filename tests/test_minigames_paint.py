# -*- coding: utf-8 -*-
"""v6.58 修复回归：小游戏必须能真正**绘制**（不只是能构造）

背景（使用者实测「游戏界面没了」）：A2-1 主题化迁移时，替换 import 块的锚点把
`from PySide6.QtGui import QPainter, QPen, QColor, QBrush` 整行吃掉了 →
所有画布类游戏（五子棋/扫雷/贪吃蛇/2048/俄罗斯方块…）的 `paintEvent` 抛
`NameError: name 'QPainter' is not defined` → 对话框能打开但**画面空白**。

教训：只断言"能构造、样式表里有色"抓不到绘制期错误 —— 本测试补上"真触发一次绘制"。

运行：python -m pytest tests/test_minigames_paint.py -q
"""
import contextlib
import io
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


def _paint_all():
    """构造全部游戏并强制绘制一次，返回 (错误列表, 成功数)。"""
    import pet_minigames as mg
    app = _app()
    errs = []
    ok = 0
    old_hook = sys.excepthook
    sys.excepthook = lambda *a: errs.append(a)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stderr(buf):
            for name, cls in mg.GAMES.items():
                try:
                    w = cls(lambda *a, **k: None)
                    w.show()
                    w.resize(360, 480)
                    app.processEvents()      # 触发 paintEvent
                    pm = w.grab()            # 同步再绘一次（更能暴露绘制期异常）
                    if pm.isNull():
                        errs.append((name, 'grab 返回空图'))
                    else:
                        ok += 1
                    w.close()
                    w.deleteLater()
                except Exception as e:       # 构造期/绘制期同步异常
                    errs.append((name, repr(e)))
            app.processEvents()
    finally:
        sys.excepthook = old_hook
    text = buf.getvalue()
    if 'Traceback' in text or 'NameError' in text or 'Error calling Python override' in text:
        errs.append(('stderr', text[-800:]))
    return errs, ok


def test_all_games_paint_without_error():
    errs, ok = _paint_all()
    assert ok >= 10, f'只有 {ok} 个游戏成功绘制'
    assert not errs, f'绘制期出错：{errs[:4]}'


def test_names_used_by_paint_are_imported():
    """源码护栏：paintEvent 里用到的 Qt 绘图类必须在文件顶部导入"""
    src = open(os.path.join(BASE, 'pet_minigames.py'), encoding='utf-8').read()
    for name in ('QPainter', 'QPen', 'QColor', 'QBrush'):
        assert ('%s(' % name) in src, f'{name} 未被使用？护栏可能需要更新'
        assert ('import %s' % name) in src or (', %s' % name) in src or ('%s,' % name) in src, \
            f'{name} 被使用但没有导入（paintEvent 会 NameError → 界面空白）'
