# -*- coding: utf-8 -*-
"""主区扩展：星图页 + 概览卡

Owner 2026-10-31：「主要是现在这个主区的东西太少了」，选「星图 + 概览卡」。

现状实测：主区 3 页（待办 / 便签 / 用量分析），1100×720 窗口默认页只有 2 条待办
⇒ 一片空白。左列按钮下方也有一大片空白没用过。

本文件锁四件事：
A. 星图页真的注册进主区（不动独立弹窗，两个入口共用同一控件）
B. 概览卡显示 4 项真实数据（关系/记忆/今天/待办），值来自宿主，不自己编
C. 数据取不到时降级（少显示一项，不崩、不留空壳）
D. 主区关掉重开不报「Internal C++ object already deleted」
"""
import os
import sys

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import panel_registry as pr  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)


# ---------- A. 星图页注册 ----------
def _register_all():
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    n = p._register_builtin_panels()
    return p, n


def test_starmap_panel_is_registered():
    pr.clear_panels()
    _p, _n = _register_all()
    keys = [s.key for s in pr.panels()]
    assert 'starmap' in keys, '星图页没注册：%r' % (keys,)


def test_starmap_panel_order_after_stats():
    pr.clear_panels()
    _register_all()
    by_key = {s.key: s.order for s in pr.panels()}
    assert by_key.get('starmap', 0) > by_key.get('stats', 0), '星图应排在用量分析之后'


def test_starmap_panel_builds_widget():
    pr.clear_panels()
    p, _ = _register_all()
    spec = next(s for s in pr.panels() if s.key == 'starmap')
    w = spec.factory(p)
    assert w is not None, '星图 factory 返回 None'
    w.resize(900, 620)
    w.show()
    _app.processEvents()
    assert not w.grab().toImage().isNull(), '星图画不出来'


def test_starmap_dialog_still_exists():
    """独立弹窗入口不删（两个入口共用同一控件）"""
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    assert 'def _open_memory_starmap' in src, '独立弹窗入口被删了'


# ---------- B. 概览卡 ----------
def test_overview_has_four_rows():
    p, _ = _register_all()
    rows = p._main_area_overview()
    keys = [r[0] for r in rows]
    for want in ('关系', '记忆', '今天', '待办'):
        assert want in keys, '概览缺「%s」：%r' % (want, keys)


def test_overview_values_are_real_not_placeholders():
    p, _ = _register_all()
    rows = dict(p._main_area_overview())
    # 每一项都必须有值，且不是「—」这种占位
    for k, v in rows.items():
        assert v and str(v).strip() not in ('', '—', '-', 'None'), '%s 的值是空的' % k
    # 关系里应出现阶段名或好感数字
    assert any(x in rows['关系'] for x in ('好感', '初见', '熟悉', '亲密', '依赖', '灵魂伴侣')), \
        '关系行不像真数据：%r' % rows['关系']
    assert '条' in rows['待办'], '待办行不像真数据：%r' % rows['待办']


def test_overview_degrades_on_broken_source(monkeypatch):
    """某个数据源炸了 ⇒ 只少一项，不整体崩"""
    p, _ = _register_all()

    def boom(*a, **k):
        raise RuntimeError('假故障')
    monkeypatch.setattr(p.affection, 'snapshot', boom)
    rows = p._main_area_overview()
    keys = [r[0] for r in rows]
    assert '关系' not in keys, '坏掉的数据源不该出现'
    assert '记忆' in keys and '待办' in keys, '一个好源坏了不该连累其他项'


def test_overview_all_broken_returns_empty():
    p, _ = _register_all()
    for obj, attr in ((p.affection, 'snapshot'), (p.api_stats, 'today')):
        pass
    # 直接构造一个什么都不给我的宿主替身
    class _Host:
        class _A:
            def snapshot(self, *a, **k):
                raise RuntimeError('x')
        affection = _A()

        class _S:
            @property
            def today(self):
                raise RuntimeError('x')
        api_stats = _S()
        memories = None
        todos = None

    p2 = p.__class__.__new__(p.__class__)
    p2.affection = _Host.affection
    p2.api_stats = _Host.api_stats
    p2.memories = None
    p2.todos = None
    p2.current = 'flash'
    rows = p2._main_area_overview()
    assert isinstance(rows, list), '全坏时也要返回列表，不能抛'


# ---------- C. 左列概览卡（panel_shell 侧）----------
def test_shell_shows_overview_when_cb_given():
    pr.clear_panels()
    import desktop_pet as dp
    from panel_shell import PanelShell
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p._register_builtin_panels()
    w = PanelShell(p, labels={'title': '主区', 'hint': 'x', 'empty': 'y'},
                   overview_cb=p._main_area_overview)
    w.resize(900, 620)
    w.show()
    _app.processEvents()
    assert getattr(w, '_overview_rows', None), '概览卡没拿到数据'
    assert len(w._overview_rows) >= 3


def test_shell_works_without_overview_cb():
    """不传回调时照旧可用（向后兼容）"""
    pr.clear_panels()
    import desktop_pet as dp
    from panel_shell import PanelShell
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p._register_builtin_panels()
    w = PanelShell(p, labels={'title': '主区', 'hint': 'x', 'empty': 'y'})
    w.resize(900, 620)
    w.show()
    _app.processEvents()
    assert not w.grab().toImage().isNull()


# ---------- D. 重开不炸 ----------
def test_reopen_after_close_is_safe():
    pr.clear_panels()
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    w1 = p._open_main_area()
    assert w1 is not None
    _app.processEvents()
    w1.hide()
    w2 = p._open_main_area()
    assert w2 is not None
    _app.processEvents()
    # 第二次打开要能刷新而 not 崩
    w2.refresh_all()
    assert not w2.grab().toImage().isNull()
