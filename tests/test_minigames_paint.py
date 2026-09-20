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
import random
import sys
import threading
import zlib

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


# 判错的依据：只认“提到 pet_minigames 的异常” —— 不再看全局 stderr 里有没有 Traceback
# （v6.70 修抖动：满载时别的延迟输出/Qt 警告/finally 里的痕迹会落进捕获窗口，
#   旧的文本扫描会偶发假红。现在按游戏归属 + 固定种子 + 关定时器，让它可复现）
BAD_MARKERS = ('Traceback', 'NameError', 'Error calling Python override')
_GLOBAL_ERRS = []


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


def _paint_all():
    """构造全部游戏并强制绘制一次，返回 (错误列表, 成功数)

    确定性保证（v6.70 去抖动）：
      1. 每个游戏绘制前 **固定随机种子** → 棋盘/目标/食物与上次完全一致，
         真的画不出来就**每次都红**，不再时红时绿
      2. 绘制前 **停掉游戏内 QTimer** → 不靠“延迟是否恰好落在窗口里”
      3. 错误按**每个游戏单独归属**（各自的 stderr + Qt 消息处理钩子），
         且只采信提到 pet_minigames 的异常
    """
    import pet_minigames as mg
    from PySide6.QtCore import QTimer, qInstallMessageHandler
    app = _app()
    errs = []
    ok = 0
    qt_msgs = []

    def _qt_handler(mode, ctx, text):
        qt_msgs.append(str(text))

    old_hook = sys.excepthook
    old_thread_hook = getattr(threading, 'excepthook', None)
    old_qt = qInstallMessageHandler(_qt_handler)
    sys.excepthook = lambda *a: _GLOBAL_ERRS.append(repr(a))
    try:
        threading.excepthook = lambda a: _GLOBAL_ERRS.append(repr(a))
    except Exception:
        pass
    _GLOBAL_ERRS.clear()
    try:
        for name, cls in mg.GAMES.items():
            random.seed(zlib.crc32(name.encode('utf-8')))   # ★ 固定种子
            mark = len(qt_msgs)
            buf = io.StringIO()
            try:
                with contextlib.redirect_stderr(buf):
                    w = cls(lambda *a, **k: None)
                    w.resize(360, 480)
                    w.show()
                    for tm in w.findChildren(QTimer):         # ★ 停掉游戏内定时器
                        tm.stop()
                    app.processEvents()
                    pm = w.grab()                             # 同步再绘一次
                    if pm.isNull():
                        errs.append((name, 'grab 返回空图'))
                    else:
                        ok += 1
                    w.close()
                    w.deleteLater()
            except Exception as e:                            # 构造期/绘制期同步异常
                errs.append((name, repr(e)))
            text = buf.getvalue() + '\n'.join(qt_msgs[mark:])
            if any(k in text for k in BAD_MARKERS) and 'pet_minigames' in text:
                errs.append((name, 'stderr/qt: ' + text[-400:]))
        app.processEvents()
    finally:
        sys.excepthook = old_hook
        if old_thread_hook is not None:
            threading.excepthook = old_thread_hook
        qInstallMessageHandler(old_qt)
    for e in _GLOBAL_ERRS:
        if 'pet_minigames' in e:
            errs.append(('global', e[:200]))
    return errs, ok


def test_all_games_paint_without_error():
    errs, ok = _paint_all()
    assert ok >= 10, f'只有 {ok} 个游戏成功绘制'
    assert not errs, f'绘制期出错：{errs[:4]}'


def test_paint_result_is_reproducible():
    """同一份代码两次绘制结果必须一致（固定种子后不存在“偶发”）"""
    e1, o1 = _paint_all()
    e2, o2 = _paint_all()
    assert (o1, [x[0] for x in e1]) == (o2, [x[0] for x in e2]), '两次结果不一致 → 还有不确定性'


def test_names_used_by_paint_are_imported():
    """源码护栏：paintEvent 里用到的 Qt 绘图类必须在文件顶部导入"""
    src = open(os.path.join(BASE, 'pet_minigames.py'), encoding='utf-8').read()
    for name in ('QPainter', 'QPen', 'QColor', 'QBrush'):
        assert ('%s(' % name) in src, f'{name} 未被使用？护栏可能需要更新'
        assert ('import %s' % name) in src or (', %s' % name) in src or ('%s,' % name) in src, \
            f'{name} 被使用但没有导入（paintEvent 会 NameError → 界面空白）'
