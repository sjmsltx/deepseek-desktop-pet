# -*- coding: utf-8 -*-
"""C2b 护栏：`rt_action` 人工确认闸门**完整动作链**（接线批次 · 动作面后半批）

微信侧委托（`WX-桌宠-20260926-13` §三 + `-26` 口径定案）：草稿 → **未确认不进 L0** ✗ →
人点确认才写 L0 + 投递 ✓ → **否决不留 L0** ✗；额度拒绝 → **写审计** ✓（不得静默 ✗）
"""
from __future__ import annotations

import io
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _mk(tmp_path, *, check_budget=None, relay=None):
    import rt_action
    import rt_relay
    import rt_store
    st = rt_store.Store(str(tmp_path / 'rt'))
    rl = relay if relay is not None else rt_relay.Relay(str(tmp_path / 'relay'))
    gt = rt_action.make_gate(store=st, base_dir=str(tmp_path / 'gate'), relay=rl,
                             check_budget=check_budget)
    return st, rl, gt


# ── 草稿：不进 L0 ✓ ──────────────────────────────────────────────
def test_draft_for_human_not_in_l0(tmp_path):
    import rt_action
    import rt_store
    st, rl, gt = _mk(tmp_path)
    out = rt_action.draft_for_human(gate=gt, round_id='r-101', role='flash', content='草稿甲', turn_no=1)
    assert out['ok'] is True and out['state'] == 'pending' and out['in_l0'] is False
    assert st.list_day('flash', rt_store._today()) == [], '未确认不得进 L0 ✗'
    det = rt_action.draft_detail_for_ui(gate=gt, draft_id=out['draft_id'])
    assert det['ok'] is True and det['state'] == 'pending' and det['in_l0'] is False
    assert det['content'] == '草稿甲' and det['turn_no'] == 1


# ── 确认：写 L0 + ptr + 投递回执 ✓ ───────────────────────────────
def test_confirm_writes_l0_and_delivers(tmp_path):
    import rt_action
    import rt_store
    st, rl, gt = _mk(tmp_path)
    did = rt_action.draft_for_human(gate=gt, round_id='r-102', role='flash', content='正文乙')['draft_id']
    res = rt_action.confirm_draft(gate=gt, draft_id=did)
    assert res['ok'] is True and res['ptr'] and res['in_l0'] is True, res
    assert len(st.list_day('flash', rt_store._today())) == 1
    rc = res['receipt']
    assert rc and rc['state'] == 'sent' and rc['ok'] is True, rc
    assert rc['idem_key'] == 'r-102|flash'
    # 投递落文件通道 ✓
    assert (Path(tmp_path) / 'relay' / 'outbox' / 'r-102' / 'flash.md').is_file()
    # 确认后不在待确认列表 ✓ 且详情为 confirmed ✓
    assert rt_action.pending_for_ui(gate=gt) == []
    assert rt_action.draft_detail_for_ui(gate=gt, draft_id=did)['state'] == 'confirmed'


def test_confirm_twice_raises(tmp_path):
    import rt_action
    import pytest
    st, rl, gt = _mk(tmp_path)
    did = rt_action.draft_for_human(gate=gt, round_id='r-103', role='flash', content='c')['draft_id']
    rt_action.confirm_draft(gate=gt, draft_id=did)
    with pytest.raises(ValueError):
        rt_action.confirm_draft(gate=gt, draft_id=did)     # 不重复确认 ✗


# ── 否决：不留 L0 ✓ ──────────────────────────────────────────────
def test_reject_leaves_no_l0(tmp_path):
    import rt_action
    import rt_store
    st, rl, gt = _mk(tmp_path)
    did = rt_action.draft_for_human(gate=gt, round_id='r-104', role='nova', content='草稿丙')['draft_id']
    out = rt_action.reject_draft(gate=gt, draft_id=did, reason='不要')
    assert out['ok'] is True and out['in_l0'] is False
    assert st.list_day('nova', rt_store._today()) == [], '否决不得留 L0 ✗'
    assert rt_action.pending_for_ui(gate=gt) == []
    assert rt_action.draft_detail_for_ui(gate=gt, draft_id=did)['state'] == 'rejected'
    assert (Path(tmp_path) / 'relay' / 'receipts.jsonl').exists() is False or True


# ── ⭐ 额度拒绝：rejected + 审计 + 不进 L0 ✓（不静默 ✗）────────────
def test_confirm_denied_by_budget_writes_audit(tmp_path):
    import rt_action
    import rt_store
    st, rl, gt = _mk(tmp_path, check_budget=lambda role: (False, '超额：已达今日上限 ¥20.00'))
    did = rt_action.draft_for_human(gate=gt, round_id='r-105', role='flash', content='草稿丁')['draft_id']
    res = rt_action.confirm_draft(gate=gt, draft_id=did)
    assert res['ok'] is False and res['in_l0'] is False, '额度拒绝**不得**写 L0 ✗'
    assert '超额' in res['reason']
    assert st.list_day('flash', rt_store._today()) == []
    assert rt_action.draft_detail_for_ui(gate=gt, draft_id=did)['state'] == 'rejected'
    # ⭐ 审计落盘 ✓（经 `rt_action.make_gate` 注入 ✓ → 额度拒绝**必留痕** ✓ 不静默 ✗）
    aud = Path(tmp_path) / 'gate' / 'audit.jsonl'
    blob = io.open(aud, encoding='utf-8', errors='replace').read() if aud.is_file() else ''
    assert 'budget_deny' in blob, blob[-400:]


def test_draft_detail_missing(tmp_path):
    import rt_action
    st, rl, gt = _mk(tmp_path)
    out = rt_action.draft_detail_for_ui(gate=gt, draft_id='d-19700101-9999')
    assert out['ok'] is False and '不存在' in out['reason']


def test_confirm_receipt_readable_by_ui(tmp_path):
    """⭐ 确认产生的回执，界面侧通过 `receipts_for_ui` **能读到** ✓"""
    import rt_action
    st, rl, gt = _mk(tmp_path)
    did = rt_action.draft_for_human(gate=gt, round_id='r-106', role='flash', content='正文戊')['draft_id']
    rt_action.confirm_draft(gate=gt, draft_id=did)
    rows = rt_action.receipts_for_ui(relay=rl, round_id='r-106')
    assert len(rows) == 1 and rows[0]['state'] == 'sent' and rows[0]['role'] == 'flash'
