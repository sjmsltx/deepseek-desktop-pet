# -*- coding: utf-8 -*-
"""减分三档的接线层：配置 / GUI / 行为信号 / 模型工具

本文件锁「接线真的通」，引擎本身的逻辑在 test_affection_mode.py。

A. 配置：config.json 的 affection_mode 能读进引擎；坏值安全兜底
B. GUI：设置界面有档位下拉，切换会调 host 方法并落盘
C. 行为信号：点停止的扣分判据（出过字才扣 / 没出字不扣）
D. 模型工具：affection_penalty 在工具表里、能被调用、受档位闸
E. 红线：affection_mode 不在 AI 可改的配置白名单里
"""
import json
import os
import sys

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)


def _pet(tmp_path):
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p._append_chat = lambda *a, **k: None
    # 每个测试用独立好感度库，别碰真实 affection.json
    import affection_engine as ae
    p.affection = ae.AffectionEngine(str(tmp_path / 'aff.json'))
    return p


# ---------- A. 配置 ----------
def test_config_mode_reaches_engine(monkeypatch):
    import desktop_pet as dp
    import affection_engine as ae
    monkeypatch.setattr(dp, 'CONFIG_PATH', '')
    # 直接验引擎构造参数路径
    e = ae.AffectionEngine.__init__.__defaults__
    assert e is not None
    eng = ae.AffectionEngine('x.json', mode='off')
    assert eng.mode == 'off', '构造时传的档位没生效'


def test_bad_mode_in_config_falls_back_to_full():
    import affection_engine as ae
    eng = ae.AffectionEngine('x.json', mode='nonsense')
    assert eng.mode == 'full', '配置写错应回退默认 full，实际 %r' % eng.mode


def test_config_key_exists_in_loader():
    """_load_ai_config 里必须真的读 affection_mode"""
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    assert "cfg.get('affection_mode'" in src, '配置读取里没有 affection_mode'


# ---------- B. GUI ----------
def test_settings_has_mode_combobox(tmp_path):
    import settings_ui as su
    p = _pet(tmp_path)
    w = su.SettingsDialog(p)
    assert hasattr(w, 'cb_affmode'), '设置界面没有档位下拉'
    vals = [w.cb_affmode.itemData(i) for i in range(w.cb_affmode.count())]
    assert vals == ['off', 'gentle', 'full'], '下拉选项不对：%r' % vals


def test_combobox_reflects_current_mode(tmp_path):
    import settings_ui as su
    p = _pet(tmp_path)
    p.affection.set_mode('gentle')
    p.affection_mode = 'gentle'
    w = su.SettingsDialog(p)
    w._refresh()
    assert w.cb_affmode.currentData() == 'gentle', \
        '下拉没反映当前档位：%r' % w.cb_affmode.currentData()


def test_set_affection_mode_saves_and_applies(tmp_path):
    p = _pet(tmp_path)
    saved = {}
    p._save_cfg_value = lambda k, v: saved.setdefault(k, v)
    assert p._set_affection_mode('off') is True
    assert p.affection.mode == 'off', '引擎档位没跟着变'
    assert saved.get('affection_mode') == 'off', '没落盘：%r' % saved


def test_set_affection_mode_rejects_bad_value(tmp_path):
    p = _pet(tmp_path)
    p.affection.set_mode('gentle')
    assert p._set_affection_mode('whatever') is False
    assert p.affection.mode == 'gentle', '坏值不该改档位'


# ---------- C. 行为信号：点停止 ----------
def test_stop_penalized_only_after_content(tmp_path):
    p = _pet(tmp_path)
    with p.affection._lock:
        st = p.affection._state('flash')
        st['affection'] = 150
        p.affection._save()

    p._round_has_content = True          # 主人已经看到字了
    p._penalize_interrupt()
    with p.affection._lock:
        assert p.affection._state('flash')['affection'] == 149, '出过字后停止应扣 1'

    p._round_has_content = False         # 还没出字就停（自救）
    p._penalize_interrupt()
    with p.affection._lock:
        assert p.affection._state('flash')['affection'] == 149, '没出字就停止不该扣'


def test_stop_penalty_blocked_in_gentle_mode(tmp_path):
    p = _pet(tmp_path)
    p.affection.set_mode('gentle')
    with p.affection._lock:
        st = p.affection._state('flash')
        st['affection'] = 150
        p.affection._save()
    p._round_has_content = True
    p._penalize_interrupt()
    with p.affection._lock:
        assert p.affection._state('flash')['affection'] == 150, \
            'gentle 档不该接行为信号'


def test_stop_penalty_blocked_in_off_mode(tmp_path):
    p = _pet(tmp_path)
    p.affection.set_mode('off')
    with p.affection._lock:
        st = p.affection._state('flash')
        st['affection'] = 150
        p.affection._save()
    p._round_has_content = True
    p._penalize_interrupt()
    with p.affection._lock:
        assert p.affection._state('flash')['affection'] == 150, 'off 档不该扣分'


def test_round_flag_reset_at_round_start():
    """_ai_worker 每轮开始要把标记清掉，否则上一轮的 True 会污染下一轮"""
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    assert 'self._round_has_content = False' in src, '轮次开始没清标记'
    assert 'self._round_has_content = True' in src, '出字时没置标记'


# ---------- D. 模型工具 ----------
def test_tool_registered_in_registry():
    import tools_registry as tr
    names = [t['function']['name'] for t in tr.AI_TOOLS]
    assert 'affection_penalty' in names, '工具表里没有 affection_penalty'


def test_tool_in_core_tools():
    import tools_registry as tr
    assert 'affection_penalty' in tr.CORE_TOOLS, \
        '不在 CORE_TOOLS 的话，默认对话模式拿不到它，gentle 档永远不扣'


def test_tool_handler_exists():
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    assert "'affection_penalty': '_tool_affection_penalty'" in src, '处理器没登记'
    assert 'def _tool_affection_penalty' in src, '处理器没实现'


def test_tool_penalizes_in_full_mode(tmp_path):
    p = _pet(tmp_path)
    with p.affection._lock:
        st = p.affection._state('flash')
        st['affection'] = 150
        p.affection._save()
    msg = p._tool_affection_penalty({'reason': '主人说别烦我', 'severity': 2})
    with p.affection._lock:
        assert p.affection._state('flash')['affection'] == 148, '工具没扣到 2 分：%r' % msg


def test_tool_requires_reason(tmp_path):
    """不给理由就不扣 —— 扣分必须留痕，否则事后无法解释"""
    p = _pet(tmp_path)
    with p.affection._lock:
        st = p.affection._state('flash')
        st['affection'] = 150
        p.affection._save()
    p._tool_affection_penalty({'severity': 2})
    with p.affection._lock:
        assert p.affection._state('flash')['affection'] == 150


def test_tool_clamps_severity(tmp_path):
    """模型想扣 9 分也只能扣 2（引擎闸 + 工具自限）"""
    p = _pet(tmp_path)
    with p.affection._lock:
        st = p.affection._state('flash')
        st['affection'] = 150
        p.affection._save()
    p._tool_affection_penalty({'reason': 'try', 'severity': 9})
    with p.affection._lock:
        assert p.affection._state('flash')['affection'] >= 148, '扣超过 2 分了'


def test_tool_blocked_in_off_mode(tmp_path):
    p = _pet(tmp_path)
    p.affection.set_mode('off')
    with p.affection._lock:
        st = p.affection._state('flash')
        st['affection'] = 150
        p.affection._save()
    msg = p._tool_affection_penalty({'reason': '测试', 'severity': 2})
    with p.affection._lock:
        assert p.affection._state('flash')['affection'] == 150, 'off 档却被工具扣了'
    assert '没有扣' in msg or '没有' in msg, '应告诉模型没扣成，实际 %r' % msg


# ---------- E. 红线 ----------
def test_mode_not_in_ai_writable_whitelist():
    """⛔ 模型不能改自己的减分档位 —— 否则它可以关掉扣分来保分"""
    import desktop_pet as dp
    assert 'affection_mode' not in dp.PetWidget.CONFIG_WHITELIST, \
        'affection_mode 不该在 AI 可写白名单里'
