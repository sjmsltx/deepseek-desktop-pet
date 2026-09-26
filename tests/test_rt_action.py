# -*- coding: utf-8 -*-
"""C2a 护栏：`rt_action`（接线批次 · **动作面 投递 + 回执 + 额度**）

微信侧委托（`WX-桌宠-20260926-13` §三）：投递（幂等回执 ✓）+ 额度（超额即停并说明 ✓ 拒绝写审计 ✓）
+ ⭐ **回执可被界面读到** ✓ + ⭐ **闸门「未确认不进 L0」在数据层成立** ✓
"""
from __future__ import annotations

import ast
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOD = ROOT / 'rt_action.py'


def _relay(tmp_path, transport=None):
    import rt_relay
    return rt_relay.Relay(str(tmp_path / 'relay'), transport=transport)


# ── ① 投递：成功 ✓ 幂等 ✓ 失败不静默 ✓ ────────────────────────────
def test_deliver_sent_writes_channel_file(tmp_path):
    import rt_action
    rl = _relay(tmp_path)
    out = rt_action.deliver(relay=rl, round_id='r-001', role='flash', content='正文甲')
    assert out['ok'] is True and out['state'] == 'sent', out
    p = Path(tmp_path) / 'relay' / 'outbox' / 'r-001' / 'flash.md'
    assert p.is_file() and io.open(p, encoding='utf-8').read() == '正文甲'
    assert out['idem_key'] == 'r-001|flash'


def test_deliver_duplicate_does_not_resend(tmp_path):
    """⭐ 幂等：同 `轮次id|角色` 再投 → `duplicate` ✓ 且**传输不被二次调用** ✗"""
    import rt_action
    calls = []

    def spy(round_id, role, content):
        calls.append((round_id, role))
        return True

    rl = _relay(tmp_path, transport=spy)
    a = rt_action.deliver(relay=rl, round_id='r-001', role='flash', content='x')
    b = rt_action.deliver(relay=rl, round_id='r-001', role='flash', content='x')
    assert a['state'] == 'sent' and b['state'] == 'duplicate'
    assert b['ok'] is True, 'duplicate 属**幂等成功** ✓'
    assert len(calls) == 1, calls


def test_deliver_failed_reports_reason(tmp_path):
    import rt_action

    def boom(*_a):
        raise RuntimeError('通道写失败')

    rl = _relay(tmp_path, transport=boom)
    out = rt_action.deliver(relay=rl, round_id='r-002', role='nova', content='y')
    assert out['ok'] is False and out['state'] == 'failed'
    assert 'RuntimeError' in out['reason'] and '通道写失败' in out['reason']


# ── ② 回执视图：⭐ append-only → 先归一再筛 ✓ ──────────────────────
def test_receipts_view_normalizes_to_latest_per_key(tmp_path):
    """⭐ 同一 `idem_key` 先 `sent` 后 `failed` → 视图必须取**最新** = `failed` ✓（不回落 ✗）"""
    import rt_action
    rl = _relay(tmp_path)
    rt_action.deliver(relay=rl, round_id='r-003', role='flash', content='z')
    # 手工追加一行"同 key 但状态变更"（模拟事后失败 ✗）
    import json
    with io.open(rl.receipts_path, 'a', encoding='utf-8') as f:
        f.write(json.dumps({'idem_key': 'r-003|flash', 'round_id': 'r-003', 'role': 'flash',
                            'state': 'failed', 'reason': '事后失败'}, ensure_ascii=False) + '\n')
    rows = rt_action.receipts_for_ui(relay=rl)
    hit = [r for r in rows if r['idem_key'] == 'r-003|flash']
    assert len(hit) == 1, hit
    assert hit[0]['state'] == 'failed' and hit[0]['ok'] is False, hit


def test_receipts_view_filters_and_limit(tmp_path):
    import rt_action
    rl = _relay(tmp_path)
    for i, rid in enumerate(('r-010', 'r-011', 'r-012'), start=1):
        rt_action.deliver(relay=rl, round_id=rid, role='flash', content='c%d' % i)
    assert len(rt_action.receipts_for_ui(relay=rl)) == 3
    assert [r['round_id'] for r in rt_action.receipts_for_ui(relay=rl, round_id='r-011')] == ['r-011']
    assert len(rt_action.receipts_for_ui(relay=rl, limit=2)) == 2
    assert rt_action.receipts_for_ui(relay=rl, only='failed') == []


# ── ③ 额度：放行 ✓ / 超额即停并说明 ✓ / 拒绝写审计 ✓ ───────────────
def test_budget_gate_allow_and_deny_with_audit():
    import rt_action
    seen = []
    ok = rt_action.budget_gate(estimate=0.01, check=lambda e: (True, '未超限', 1.23),
                               audit=seen.append, role='flash', round_id='r-020')
    assert ok['ok'] is True and '未超限' in ok['reason'] and seen == []
    deny = rt_action.budget_gate(estimate=0.9, check=lambda e: (False, '超额：已达今日上限', 20.0),
                                 audit=seen.append, role='flash', round_id='r-020')
    assert deny['ok'] is False and '超额' in deny['reason'] and deny['note']
    assert seen and seen[-1]['action'] == 'budget_deny', seen
    assert seen[-1]['role'] == 'flash' and seen[-1]['round_id'] == 'r-020'
    assert seen[-1]['used'] == 20.0 and seen[-1]['estimate'] == 0.9


def test_budget_gate_uses_governance_and_never_writes_config(monkeypatch):
    """⭐ 默认走 `governance.check_cost` ✓ 且**只读** ✗ 不写 config ✗"""
    import rt_action
    import governance
    calls = []

    def fake(estimate=0.0):
        calls.append(estimate)
        return (True, 'ok', 0.5)

    monkeypatch.setattr(governance, 'check_cost', fake)
    out = rt_action.budget_gate(estimate=0.01)
    assert calls == [0.01] and out['ok'] is True
    src = io.open(MOD, encoding='utf-8').read()
    for bad in ('config.json', 'save_config', 'check_cost_raise'):
        assert bad not in src, bad


def test_audit_rejects_bad_object():
    import rt_action
    try:
        rt_action._audit(object(), {'a': 1})
    except TypeError:
        return
    raise AssertionError('审计出口类型错应当报错 ✗')


# ── ⭐ 数据层：「未确认不进 L0」✓（界面读的是 pending ✓）────────────
def test_gate_draft_not_in_l0_until_confirmed(tmp_path):
    import rt_action
    import rt_gate
    import rt_store
    st = rt_store.Store(str(tmp_path / 'rt'))
    gt = rt_gate.Gate(st, str(tmp_path / 'gate'))
    did = gt.draft('r-030', 'flash', '草稿正文', turn_no=1)
    # 未确认：L0 无该轮 ✗；界面视图里能看到 pending ✓
    assert st.list_day('flash', rt_store._today()) == []
    rows = rt_action.pending_for_ui(gate=gt)
    assert [r['draft_id'] for r in rows] == [did] and rows[0]['state'] == 'pending'
    # 确认后：才写 L0 ✓
    res = gt.confirm(did)
    assert res['ok'] is True and res['ptr']
    assert len(st.list_day('flash', rt_store._today())) == 1
    assert rt_action.pending_for_ui(gate=gt) == []


def test_pending_for_ui_excludes_rejected(tmp_path):
    """⭐ 视图归一：已否决草稿**不得**留在待确认列表 ✓（与 `rt_gate.pending()` 一致 ✓）"""
    import rt_action
    import rt_gate
    import rt_store
    st = rt_store.Store(str(tmp_path / 'rt'))
    gt = rt_gate.Gate(st, str(tmp_path / 'gate'))
    a = gt.draft('r-031', 'flash', 'α')
    b = gt.draft('r-031', 'flash', 'β')
    gt.reject(a, reason='不要')
    ids = [r['draft_id'] for r in rt_action.pending_for_ui(gate=gt)]
    assert b in ids and a not in ids, ids


# ── 硬约束：不出网（AST 级 ✓）─────────────────────────────────────
def test_module_has_no_network():
    src = io.open(MOD, encoding='utf-8').read()
    mods = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            mods |= {a.name.split('.')[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            mods.add(n.module.split('.')[0])
    assert not (mods & {'urllib', 'requests', 'socket', 'http', 'subprocess'}), mods
