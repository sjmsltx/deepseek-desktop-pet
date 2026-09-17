# -*- coding: utf-8 -*-
"""v6.58 新增：UI「真绘制」扫荡测试（防"能构造但画不出来"这类 bug）

背景：小游戏界面曾因 `QPainter` 等绘图类**被误删的 import**，导致 `paintEvent` 抛
NameError —— 对话框能打开、样式表也有色，但**画面全白**（使用者实测「游戏界面没了」）。
当时所有测试只断言"能构造 / 样式表有色"，抓不到绘制期错误。

本测试把每个 UI 面都 **show + processEvents + grab**（真正触发 paintEvent），
并捕获 excepthook / stderr 里的异常 —— 任何绘制期错误都会让它失败。

运行：python -m pytest tests/test_ui_paint_sweep.py -q
"""
import contextlib
import io
import os
import sys
import traceback

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


def _paint(w):
    """show → 触发绘制 → grab 同步再绘一次；返回 stderr 文本"""
    app = _app()
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        w.show()
        w.resize(360, 480)
        app.processEvents()
        pm = w.grab()
        app.processEvents()
    assert not pm.isNull(), '%s grab 返回空图（没画出来）' % type(w).__name__
    w.close()
    return buf.getvalue()


def _run(items):
    """items: [(说明, 构造并返回控件)] —— 逐个绘制，收集异常"""
    app = _app()
    errs = []
    old_hook = sys.excepthook

    def _hook(*a):
        errs.append('excepthook: ' + ''.join(traceback.format_exception(*a))[-400:])

    sys.excepthook = _hook
    try:
        for label, make in items:
            try:
                text = _paint(make())
            except Exception as e:
                errs.append('%s → %s: %s' % (label, type(e).__name__, e))
                continue
            if 'Traceback' in text or 'Error calling Python override' in text:
                errs.append('%s → 绘制期报错: %s' % (label, text.strip().splitlines()[-1][:160]))
        app.processEvents()
    finally:
        sys.excepthook = old_hook
    return errs


def test_minigames_paint():
    import pet_minigames as mg
    errs = _run([(name, (lambda c=cls: c(lambda *a, **k: None))) for name, cls in mg.GAMES.items()]
                + [('小游戏列表页', lambda: mg.GameWindow(lambda *a, **k: None))])
    assert not errs, f'小游戏绘制异常：{errs[:4]}'


def test_dialogs_paint():
    import desktop_pet as dp
    import settings_ui as su
    import affection_ui as au
    pet = dp.PetWidget()
    pet._save_cfg_value = lambda *a, **k: True
    items = [
        ('主窗口', lambda: pet),
        ('设置窗', lambda: su.SettingsDialog(pet, getattr(pet, 'registry', None))),
        ('关系面板', lambda: au.RelationDialog(pet.affection, 'flash', '测试角色')),
        ('回忆相册', lambda: au.MemoriesDialog(pet.memories, 'flash', '测试角色')),
    ]
    try:
        from model_registry import ModelRegistry
        import model_manager_ui as mmu
        reg = ModelRegistry(os.path.join(BASE, 'models.json'))
        items.append(('模型管理窗', lambda: mmu.ModelManagerDialog(reg, pet)))
    except Exception:
        pass
    errs = _run(items)
    assert not errs, f'对话框绘制异常：{errs[:4]}'


def test_cards_paint():
    import chat_cards as cc
    errs = _run([
        ('代码卡', lambda: cc.CodeCard('print(1)')),
        ('表格卡', lambda: cc.TableCard('|a|\n|-|\n|1|', '<table><tr><td>1</td></tr></table>')),
    ])
    assert not errs, f'卡片绘制异常：{errs[:4]}'
