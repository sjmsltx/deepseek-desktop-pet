# -*- coding: utf-8 -*-
"""统计悬浮窗在设置面板（应用级模态）下的可操作性（v3.1d，2026-10-24）

Owner 反馈：「从设置面板打开统计面板之后，需要先把设置面板关闭才能够关闭统计面板」

根因：`_open_settings` 用 `dlg.exec()`（应用级模态），而统计窗原来 `QWidget()` **无 parent**
⇒ 被模态挡住、点不动（但 WindowStaysOnTopHint 让它看得见）。

实测（真机）：
    无父窗 activateWindow 后仍不是活动窗；构造时带 parent 的窗可以激活。
    ⚠ 运行时 setParent 无效 —— 必须构造时传（对照实验 A/B/C 已验）。

本文件锁三件事：
1. 模态开着时，统计窗 parent = 该模态窗（可激活的前提）
2. 模态关闭（finished）后，统计窗被解放：parent 变 None 且仍可见
3. 没有模态时（右键菜单路径）parent 保持 None —— 不引入新副作用

运行：python -m pytest tests/test_stats_window_modal.py -q
"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def _pet():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(sys.argv)
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p.balance_watch = False
    return p


def _cleanup(p):
    try:
        if getattr(p, '_api_stats_win', None) is not None:
            p._api_stats_win.close()
            p._api_stats_win = None
    except Exception:
        pass


def test_attached_to_active_modal_and_released(monkeypatch):
    """模态开着 → 挂到模态窗；模态结束 → 解放且仍可见"""
    from PySide6.QtWidgets import QApplication, QDialog

    p = _pet()
    dlg = QDialog(p)
    dlg.setModal(True)
    monkeypatch.setattr(QApplication, 'activeModalWidget',
                        staticmethod(lambda: dlg))
    try:
        p._toggle_api_stats_window()
        w = p._api_stats_win
        assert w is not None, '统计窗没建出来'
        assert w.parent() is dlg, '模态开着时必须挂到模态窗下（否则被阻塞、点不动）'

        dlg.accept()                      # 触发 finished
        assert w.parent() is None, '设置关闭后统计窗应脱离父关系（否则随之消失）'
        assert w.isVisible(), '设置关闭后统计窗应继续显示'

        p._toggle_api_stats_window()      # 再点一次应能关闭
        assert p._api_stats_win is None, '再次 toggle 应能关掉统计窗'
    finally:
        _cleanup(p)
        dlg.close()


def test_no_modal_keeps_no_parent(monkeypatch):
    """没有模态时（右键菜单路径）不设 parent —— 不引入新副作用"""
    from PySide6.QtWidgets import QApplication

    p = _pet()
    monkeypatch.setattr(QApplication, 'activeModalWidget', staticmethod(lambda: None))
    try:
        p._toggle_api_stats_window()
        w = p._api_stats_win
        assert w is not None
        assert w.parent() is None, '无模态时不该凭空挂父（会被误当成子窗口随父销毁）'
    finally:
        _cleanup(p)


def test_is_toggleable_twice(monkeypatch):
    """连开两次 = 一次开一次关（toggle 语义不能被破坏）"""
    from PySide6.QtWidgets import QApplication, QDialog

    p = _pet()
    dlg = QDialog(p)
    monkeypatch.setattr(QApplication, 'activeModalWidget', staticmethod(lambda: dlg))
    try:
        p._toggle_api_stats_window()
        assert p._api_stats_win is not None
        p._toggle_api_stats_window()
        assert p._api_stats_win is None, '第二次 toggle 应关闭'
    finally:
        _cleanup(p)
        dlg.close()


# ---------- 源码护栏：防止有人改回「建完再 setParent」 ----------

def test_source_guard_parent_at_construction():
    """统计窗必须在**构造时**传 parent（运行时 setParent 实测无效）"""
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    assert 'win = QWidget(_modal) if _modal is not None else QWidget()' in src, \
        '统计窗构造未按模态传 parent（会回到「看得见点不动」的老 bug）'
    assert '_QA.activeModalWidget()' in src, '应探测 activeModalWidget'
    # 不允许出现"建完再 setParent(_modal)"这种无效写法
    assert 'win.setParent(_modal)' not in src, \
        '运行时 setParent 对模态无效（实测 A/B/C 对照），不许用'
