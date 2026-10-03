# -*- coding: utf-8 -*-
"""门槛第 1 件（Owner 2026-10-02 批「成本上限默认值 → 自定义」）护栏。

口径：
  · ⛔ 不预先塞死数 —— 未配置时不覆盖 DEFAULT_LIMITS（0 = 不限 ✓）
  · ✅ 用户可配置 —— config.json 的 `roundtable_limits` 对象 或 扁平键 roundtable_max_* ✓
  · ⛔ 非法值**不静默** ✗ —— 跳过并回调 warn ✓
  · ⭐ GUI 入口存在（桌宠设置 → 用量与计费）且**不新增 HTTP 写面** ✗
"""
import io
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import relay_log  # noqa: E402


def _cfg(tmp_path, payload, name='config.json'):
    p = tmp_path / name
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return str(p)


# ── 1. 未配置 = 不覆盖默认（仍是不限 ✓）───────────────────────────────
def test_unset_keeps_default_unlimited(tmp_path):
    assert relay_log.load_limits(str(tmp_path / 'nope.json')) == {}
    cfg = _cfg(tmp_path, {'city': '重庆'})          # 有配置文件但没有圆桌键 ✓
    assert relay_log.load_limits(cfg) == {}
    # ⭐ 默认值本身仍是 0 = 不限（不许塞死数 ✗）
    assert relay_log.DEFAULT_LIMITS['max_tokens'] == 0
    assert relay_log.DEFAULT_LIMITS['max_cost_micro'] == 0
    # 且未配置时 RelayLog 行为与从前**完全一致** ✓
    lg = relay_log.RelayLog(str(tmp_path / 'r.jsonl'), limits=relay_log.load_limits(cfg))
    assert lg.limits['max_tokens'] == 0 and lg.limits['max_cost_micro'] == 0


# ── 2. 嵌套对象 / 3. 扁平键 / 4. JSON 字符串 三种写法都要认 ────────────
def test_nested_object_form(tmp_path):
    cfg = _cfg(tmp_path, {'roundtable_limits': {'max_tokens': 200000, 'max_cost_micro': 5000000}})
    got = relay_log.load_limits(cfg)
    assert got == {'max_tokens': 200000, 'max_cost_micro': 5000000}


def test_flat_keys_form(tmp_path):
    cfg = _cfg(tmp_path, {'roundtable_max_tokens': 120000, 'roundtable_max_cost_micro': 3000000})
    got = relay_log.load_limits(cfg)
    assert got == {'max_tokens': 120000, 'max_cost_micro': 3000000}


def test_json_string_form(tmp_path):
    cfg = _cfg(tmp_path, {'roundtable_limits': json.dumps({'max_tokens': 7})})
    assert relay_log.load_limits(cfg) == {'max_tokens': 7}


def test_partial_config_leaves_other_keys_default(tmp_path):
    cfg = _cfg(tmp_path, {'roundtable_max_cost_micro': 1000000})
    got = relay_log.load_limits(cfg)
    assert got == {'max_cost_micro': 1000000}       # 未给的键**不出现** ✓ → 仍走默认 ✓
    lg = relay_log.RelayLog(str(tmp_path / 'r.jsonl'), limits=got)
    assert lg.limits['max_tokens'] == 0             # token 上限仍不限 ✓


# ── 5. 非法值不静默（跳过 + 明报 ✓）─────────────────────────────────
@pytest.mark.parametrize('bad', [
    {'max_tokens': -1},
    {'max_tokens': '200000'},
    {'max_tokens': True},
    {'max_cost_micro': -5},
])
def test_invalid_values_are_reported_not_silent(tmp_path, bad):
    cfg = _cfg(tmp_path, {'roundtable_limits': bad})
    seen = []
    got = relay_log.load_limits(cfg, warn=seen.append)
    assert got == {}, '非法值不得写入生效上限 ✗'
    assert seen, '非法值必须明报（不静默 ✗）'


def test_wrong_type_for_limits_key_is_reported(tmp_path):
    cfg = _cfg(tmp_path, {'roundtable_limits': [1, 2, 3]})
    seen = []
    assert relay_log.load_limits(cfg, warn=seen.append) == {}
    assert any('应为对象' in m for m in seen)


def test_limits_configured_helper(tmp_path):
    assert relay_log.limits_configured(str(tmp_path / 'x.json')) is False
    cfg = _cfg(tmp_path, {'roundtable_max_tokens': 1})
    assert relay_log.limits_configured(cfg) is True


# ── 6. 两个真实构造点必须传入（源头护栏 ✓）─────────────────────────
def test_both_construction_sites_pass_limits():
    # ⭐ 用 with 关句柄 ✓（不给自己造 ResourceWarning ✗）
    with io.open(os.path.join(ROOT, 'collab', 'relay_server.py'), encoding='utf-8') as fh:
        srv = fh.read()
    assert 'relay.load_limits()' in srv, '协作台必须读自定义额度 ✓'
    assert 'limits=_limits' in srv, '协作台必须把额度传给内核 ✓'
    assert '未设置' in srv, '未设置时要明报一次（不静默 ✗）'
    with io.open(os.path.join(ROOT, 'rt_remote.py'), encoding='utf-8') as fh:
        rem = fh.read()
    assert 'limits=relay_log.load_limits()' in rem, '桌宠侧构造点也要读额度 ✓'


# ── 7. GUI 入口存在，且**不新增 HTTP 写面** ✗ ──────────────────────
def test_gui_entry_exists_and_writes_config_not_http():
    with io.open(os.path.join(ROOT, 'settings_ui.py'), encoding='utf-8') as fh:
        src = fh.read()
    assert 'def _apply_roundtable_limits' in src
    assert "roundtable_max_tokens" in src and "roundtable_max_cost_micro" in src
    assert '圆桌额度' in src, '设置界面必须有可见入口 ✓'
    # ⭐ 守「写面只走文件通道」：GUI 保存只落配置文件 ✓ 不许调 HTTP ✗
    seg = src[src.index('def _apply_roundtable_limits'):]
    seg = seg[:seg.index('def ', 10)]
    assert '_save_cfg_value' in seg
    assert 'requests' not in seg and 'urlopen' not in seg and 'httpx' not in seg
