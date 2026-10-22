# -*- coding: utf-8 -*-
"""B4 护栏：`rt_relay`（投递适配）+ `rt_gate`（人工确认闸门 / 额度 / 审计）

设计 v1.1 §4/§5 要盯死（缺一即视为未完成 ✗）：
  ① 幂等键 = `轮次id|角色` ✓ 重复 → `duplicate` ✓ **不重发** ✗
  ② 投递失败 → 回执含**失败 + 原因** ✓ **不静默** ✗
  ③ ⛔ **不出网** ✗（默认传输 = 文件通道 ✓）
  ④ ⭐ **未确认不进 L0** ✗；`confirm()` → L0 + `ptr` ✓；`reject()` **不留 L0** ✗
  ⑤ 额度拒绝 → **写审计** ✓ 不静默 ✗；审计**可注入** ✓（可断言 ✓）
"""
from __future__ import annotations

import ast
import io
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _mods():
    import rt_gate
    import rt_relay
    import rt_store
    return rt_store, rt_relay, rt_gate


def _setup(tmp_path):
    rt_store, rt_relay, rt_gate = _mods()
    st = rt_store.Store(str(tmp_path / 'rt'))
    rl = rt_relay.Relay(str(tmp_path / 'rel'))
    return st, rl, rt_gate


# ── ① 幂等：重复投递 → duplicate ✓ 不重发 ✗ ─────────────────────────
def test_deliver_idempotent(tmp_path):
    _st, rl, _g = _setup(tmp_path)
    r1 = rl.deliver('r-1', 'flash', '内容')
    r2 = rl.deliver('r-1', 'flash', '内容')
    assert r1['state'] == 'sent', r1
    assert r2['state'] == 'duplicate', r2
    assert rl.idem_key('r-1', 'flash') == 'r-1|flash'
    # 只落了一份文件 ✓（不重发 ✗）
    p = os.path.join(rl.outbox, 'r-1', 'flash.md')
    assert os.path.isfile(p) and io.open(p, encoding='utf-8').read() == '内容'


# ── ② 失败回执（不静默）──────────────────────────────────────────────
def test_deliver_failure_receipt(tmp_path):
    _st, rl, _g = _setup(tmp_path)

    def _boom(*a, **k):
        raise RuntimeError('通道不可写')
    rl._transport = _boom
    r = rl.deliver('r-2', 'pro', 'x')
    assert r['state'] == 'failed', r
    assert 'RuntimeError' in r['reason'] and '通道不可写' in r['reason'], r


# ── ③ 不出网（AST ✓）────────────────────────────────────────────────
def test_no_network_in_relay_and_gate():
    for name in ('rt_relay.py', 'rt_gate.py'):
        src = Path(ROOT / name).read_text(encoding='utf-8')
        tree = ast.parse(src)
        bad = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                nm = getattr(node.func, 'id', None) or getattr(node.func, 'attr', None)
                if nm in ('urlopen', 'request', 'system'):
                    bad.append('%s@%d' % (nm, node.lineno))
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.split('.')[0] in ('requests', 'http', 'socket', 'urllib'):
                        bad.append('import:%s@%d' % (a.name, node.lineno))
            if isinstance(node, ast.ImportFrom) and (node.module or '').split('.')[0] in ('requests', 'http', 'socket', 'urllib'):
                bad.append('from:%s@%d' % (node.module, node.lineno))
        assert not bad, f'{name} 不得出网 ✗：{bad}'


# ── ④ 闸门：未确认不进 L0 ✓ confirm → L0+ptr ✓ reject 不留 L0 ✓ ──────
def test_draft_not_in_l0_until_confirmed(tmp_path):
    st, rl, rt_gate = _setup(tmp_path)
    g = rt_gate.Gate(st, str(tmp_path / 'rt'), relay=rl)
    did = g.draft('r-1', 'flash', '@flash 你好')
    assert g.latest_draft(did)['state'] == 'pending'
    assert st.list_day('flash', __import__('rt_store').Store.__module__ and _today()) == [], \
        '⭐ 未确认**不得**进 L0 ✗'
    out = g.confirm(did)
    assert out['ok'] is True and out['ptr'], out
    recs = st.list_day('flash', out['ptr'].split('|')[1])
    assert len(recs) == 1 and recs[0]['text'] == '@flash 你好', '确认后应写入 L0 ✓'
    assert g.latest_draft(did)['state'] == 'confirmed'
    assert out['receipt']['state'] == 'sent', '确认后应投递 ✓'


def test_reject_leaves_no_l0(tmp_path):
    st, _rl, rt_gate = _setup(tmp_path)
    g = rt_gate.Gate(st, str(tmp_path / 'rt'))
    did = g.draft('r-2', 'flash', '不该进 L0')
    g.reject(did, reason='不合适')
    assert g.latest_draft(did)['state'] == 'rejected'
    assert st.list_day('flash', _today()) == [], '⛔ reject 不得留 L0 ✗'


def test_confirm_twice_blocked(tmp_path):
    st, _rl, rt_gate = _setup(tmp_path)
    g = rt_gate.Gate(st, str(tmp_path / 'rt'))
    did = g.draft('r-3', 'flash', 'x')
    g.confirm(did)
    try:
        g.confirm(did)
        raise AssertionError('重复确认应被拒 ✗')
    except ValueError:
        pass


# ── ⑤ 额度：拒绝 → 写审计 ✓ 不静默 ✗ ────────────────────────────────
def test_budget_deny_writes_audit(tmp_path):
    st, _rl, rt_gate = _setup(tmp_path)
    calls = []
    g = rt_gate.Gate(st, str(tmp_path / 'rt'),
                     audit=lambda kind, actor, action, detail='': calls.append((kind, actor, detail)),
                     check_budget=lambda role='': (False, '当日额度已用尽'))
    did = g.draft('r-4', 'flash', 'x')
    out = g.confirm(did)
    assert out['ok'] is False and '额度' in out['reason'], out
    assert st.list_day('flash', _today()) == [], '额度拒绝 → 不得进 L0 ✗'
    kinds = [c[0] for c in calls]
    assert 'budget_deny' in kinds, f'额度拒绝必须写审计 ✗ 实际 {kinds}'
    assert g.latest_draft(did)['state'] == 'rejected'


def test_audit_records_key_actions(tmp_path):
    st, _rl, rt_gate = _setup(tmp_path)
    calls = []
    g = rt_gate.Gate(st, str(tmp_path / 'rt'),
                     audit=lambda kind, actor, action, detail='': calls.append(kind))
    d1 = g.draft('r-5', 'flash', 'a')
    g.confirm(d1)
    d2 = g.draft('r-6', 'flash', 'b')
    g.reject(d2, reason='no')
    for k in ('draft', 'confirm', 'reject'):
        assert k in calls, f'关键动作 {k} 必须写审计 ✗ 实际 {calls}'


# ── 草稿序号：重启后续号（不撞号 ✓）──────────────────────────────────
def test_draft_id_continues_after_restart(tmp_path):
    st, _rl, rt_gate = _setup(tmp_path)
    g1 = rt_gate.Gate(st, str(tmp_path / 'rt'))
    d1 = g1.draft('r-7', 'flash', 'a')
    g2 = rt_gate.Gate(st, str(tmp_path / 'rt'))          # 模拟重启 ✓
    d2 = g2.draft('r-8', 'flash', 'b')
    assert d1 != d2, '⭐ 重启后 draft_id 不得撞号 ✗'
    assert g2.latest_draft(d1)['state'] == 'pending', '旧草稿状态仍可读 ✓'


def test_pending_reads_state_directly(tmp_path):
    st, _rl, rt_gate = _setup(tmp_path)
    g = rt_gate.Gate(st, str(tmp_path / 'rt'))
    d1 = g.draft('r-9', 'flash', 'a')
    g.draft('r-10', 'flash', 'b')
    g.reject(d1)
    ids = [r['draft_id'] for r in g.pending(role='flash')]
    assert d1 not in ids and len(ids) == 1, ids
    for r in g.pending(role='flash'):
        assert r['state'] == 'pending', '界面直读 state ✓ 不靠推断 ✗'


def _today():
    import datetime
    return datetime.date.today().isoformat()
