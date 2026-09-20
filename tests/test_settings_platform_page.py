# -*- coding: utf-8 -*-
"""设置窗「平台能力」只读区块（v6.74 批次 5）。

约束（与 webchat 侧商定）：**不新增导航页** —— 那会破掉 `regression_test.py` H21
断言的"正好 10 分类 + 固定名字"。所以能力报告做成「系统」页里的一个只读区块。
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import platform_layer as pl  # noqa: E402


@pytest.fixture
def dlg():
    from PySide6.QtWidgets import QApplication
    import desktop_pet as dp
    import settings_ui as su
    app = QApplication.instance() or QApplication([])
    pet = dp.PetWidget()
    pet._save_cfg_value = lambda *a, **k: True        # 不落盘（沿用既有测试做法）
    d = su.SettingsDialog(pet)
    yield d, su, app
    d.close()


def test_navigation_still_ten_pages(dlg):
    """区块不能以"新增页"的方式实现（H21 断言 10 分类）"""
    d, su, _app = dlg
    assert d.nav.count() == 10 == len(su.PAGES)
    assert su.PAGES[-1] == '系统'


def test_capability_block_renders_report(dlg):
    d, su, app = dlg
    d.nav.setCurrentRow(len(su.PAGES) - 1)            # 系统页
    app.processEvents()
    txt = d.lb_platform.text()
    assert '平台抽象层' in txt and pl.platform_name() in txt
    for key in pl.capabilities():
        assert key in txt, f'能力报告里少了 {key}'


def test_refresh_button_rerenders(dlg, monkeypatch):
    from PySide6.QtWidgets import QPushButton
    d, su, app = dlg
    d.nav.setCurrentRow(len(su.PAGES) - 1)
    app.processEvents()
    monkeypatch.setattr(pl, 'report', lambda: '哨兵报告内容')
    btns = [b for b in d.findChildren(QPushButton) if '重新检测' in b.text()]
    assert btns, '系统页里应有"重新检测"按钮'
    btns[0].click()
    app.processEvents()
    assert d.lb_platform.text() == '哨兵报告内容'


def test_refresh_is_called_when_dialog_refreshes(dlg, monkeypatch):
    calls = []
    d, su, app = dlg
    monkeypatch.setattr(pl, 'report', lambda: calls.append(1) or '再次渲染')
    d._refresh()
    assert calls and d.lb_platform.text() == '再次渲染'


def test_block_is_read_only(dlg):
    """只读：不能编辑（可选可复制，方便使用者贴给我们排查）"""
    from PySide6.QtCore import Qt
    d, _su, _app = dlg
    assert d.lb_platform.textInteractionFlags() & Qt.TextSelectableByMouse
    assert not d.lb_platform.isEnabled() or d.lb_platform.isEnabled()   # 不禁用，只是不可编辑
    assert not hasattr(d.lb_platform, 'setPlainText')                   # QLabel 本来就不给编辑


def test_failure_is_shown_not_raised(dlg, monkeypatch):
    """pl.report() 抛错时界面给提示，不把设置窗带崩"""
    d, _su, _app = dlg

    def boom():
        raise RuntimeError('模拟探测失败')

    monkeypatch.setattr(pl, 'report', boom)
    d._refresh_platform()
    assert '能力检测失败' in d.lb_platform.text()
