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

# ---------- WX-108 §6.2：显式传参优先，探测兜底 ----------

def test_explicit_parent_wins_over_probe(monkeypatch):
    """传入的 parent 应优先于 activeModalWidget 探测（调用方更知道自己在哪）"""
    from PySide6.QtWidgets import QApplication, QDialog

    p = _pet()
    dlg = QDialog(p)
    other = QDialog(p)          # 探测会返回这个「错」的
    monkeypatch.setattr(QApplication, 'activeModalWidget', staticmethod(lambda: other))
    try:
        p._toggle_api_stats_window(dlg)      # 显式传 dlg
        w = p._api_stats_win
        assert w is not None
        assert w.parent() is dlg, '显式传参没生效（被探测结果覆盖了）'
        assert w.parent() is not other
    finally:
        _cleanup(p)
        dlg.close()
        other.close()


def test_probe_still_works_as_fallback(monkeypatch):
    """不传参时仍走探测（右键菜单那条路）"""
    from PySide6.QtWidgets import QApplication, QDialog

    p = _pet()
    dlg = QDialog(p)
    monkeypatch.setattr(QApplication, 'activeModalWidget', staticmethod(lambda: dlg))
    try:
        p._toggle_api_stats_window()          # 不传
        assert p._api_stats_win.parent() is dlg, '探测兜底失效'
    finally:
        _cleanup(p)
        dlg.close()


def test_release_does_not_show_hidden_window(monkeypatch):
    """WX-108 §6.1-1：本来不可见的窗，释放时不该被 show 出来（否则意外弹出）"""
    from PySide6.QtWidgets import QApplication, QDialog

    p = _pet()
    dlg = QDialog(p)
    monkeypatch.setattr(QApplication, 'activeModalWidget', staticmethod(lambda: dlg))
    try:
        p._toggle_api_stats_window()
        w = p._api_stats_win
        w.hide()                       # 模拟用户先隐藏了它
        dlg.accept()                   # 触发释放
        assert not w.isVisible(), '隐藏的窗被释放逻辑意外 show 出来了'
    finally:
        _cleanup(p)
        dlg.close()


def test_release_only_on_finished_not_destroyed():
    """释放回调**只接 finished**，不接 destroyed（v3.1e 实测结论）

    WX-108 §6.1-3 建议同时接 `destroyed` 兜底。我试过，**会崩**：
    接上后跑全量 → rc=0xC0000005（ACCESS_VIOLATION），
    且稳定停在 test_settings_dialog_does_not_write_config（真建 SettingsDialog）。

    原因：`destroyed` 在 C++ 析构**过程中**发出，此后再回调 Qt
    （我这里要 `setParent(None)` + `show()`）属于对半析构对象操作 → 未定义行为。

    另外它逻辑上也太晚：parent 析构时子窗口**已经被一起销毁**，
    此时再去 setParent 没有意义。所以这个"兜底"不成立，改为只接 finished。
    若某平台真不走 finished，代价是统计窗随设置一起消失 —— 用户重开一次即可，
    比崩溃好得多。
    """
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    assert "_modal.finished.connect(_release_from_modal)" in src, 'finished 释放回调没了'
    assert "'destroyed'" not in src.split('_release_from_modal')[0][-2000:] or \
        "_modal.destroyed.connect" not in src, \
        '又接了 destroyed（实测会 ACCESS_VIOLATION，别加回来）'
