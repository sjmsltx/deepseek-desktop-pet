# -*- coding: utf-8 -*-
"""C1 护栏：`rt_view`（接线批次 · **只读导出面**）

微信侧委托（`WX-桌宠-20260926-11` §四 ③）：**C1 新用例 = 只读面数据正确 + 隔离** ✓
另盯硬约束：④ `near_limit` 落地 ✓ · ⑤ 隔离在**数据层**强制 ✓ · ⑥ 口径 6000/4000 + **估算**标注 ✓
"""
from __future__ import annotations

import ast
import hashlib
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOD = ROOT / 'rt_view.py'


def _store(tmp_path):
    import rt_store
    return rt_store.Store(str(tmp_path / 'rt'))


def _seed(store, *, role='flash', n=2, rounds=None):
    """造 2 轮：每轮 append L0 + add_summary L1 ✓（返回 ptr 列表 ✓）"""
    rounds = rounds or ['r-001', 'r-002']
    ptrs = []
    for i, rid in enumerate(rounds, start=1):
        p = store.append(role, 'chat', '第%d轮全文内容%s' % (i, '甲' * 20), round_id=rid, turn_no=i)
        store.add_summary(p, '@%s 第%d轮摘要一句。' % (role, i), round_id=rid, turn_no=i, kind='chat')
        ptrs.append(p)
    return ptrs


def _sha(p):
    return hashlib.sha256(io.open(p, 'rb').read()).hexdigest()


# ── ① 大厅视图：每轮一条卡 ✓ ────────────────────────────────────────
def test_hall_cards_fields_and_order(tmp_path):
    import rt_view
    st = _store(tmp_path)
    _seed(st)
    cards = rt_view.hall_cards(store=st, role='flash')
    assert len(cards) == 2, cards
    assert [c['round_id'] for c in cards] == ['r-001', 'r-002']       # 顺序=写入顺序 ✓
    c = cards[0]
    for k in ('ptr', 'role', 'day', 'seq', 'round_id', 'turn_no', 'kind', 'summary', 'ts', 'expired'):
        assert k in c, k
    assert c['turn_no'] == 1 and c['round_id'] == 'r-001'
    info = rt_view.parse_ptr(c['ptr'])
    assert info == {'role': 'flash', 'day': info['day'], 'seq': info['seq']}   # 指针可解析 ✓
    assert '摘要一句' in c['summary']


def test_hall_cards_is_read_only(tmp_path):
    """⭐ 只读：读卡前后 **L0 + L1 文件 sha 不变** ✓（不产新行 ✗）"""
    import rt_view
    st = _store(tmp_path)
    _seed(st)
    before = {str(p): _sha(p) for p in Path(tmp_path).rglob('*') if p.is_file()}
    rt_view.hall_cards(store=st, role='flash')
    rt_view.hall_cards(store=st)
    after = {str(p): _sha(p) for p in Path(tmp_path).rglob('*') if p.is_file()}
    assert before and before == after, '只读面**不得**改动任何文件 ✗'


# ── ② 通道视图：五优先级构成 + trace ✓ + 预算口径 ✓ ─────────────────
def test_channel_view_priorities_trace_and_budget(tmp_path):
    import rt_view
    out = rt_view.channel_view(
        role='flash',
        my_recent=[{'role': 'flash', 'ptr': 'flash|2026-09-26|0001', 'text': '本角色近段' * 10}],
        hall_summaries=[{'role': 'nova', 'ptr': 'nova|2026-09-26|0002', 'text': '大厅一条' * 20}],
        mentions=[{'role': 'nova', 'ptr': 'nova|2026-09-26|0003', 'text': '@flash 点名' * 5}],
    )
    assert out['view'] == 'channel' and out['role'] == 'flash'
    whys = [t['why'] for t in out['trace']]
    assert any('优先级①' in w for w in whys), whys                       # @点名（①）✓
    assert any('优先级②' in w for w in whys), whys                       # 本角色近段（②）✓
    assert all(('ptr' in t and 'kept' in t and 'why' in t) for t in out['trace'])
    bd = out['budget_display']
    assert bd['limit'] == 6000 and bd['near_limit_line'] == 4000, bd      # 口径 6000/4000 ✓
    assert bd['estimated'] is True and '估算' in bd['note']               # ⭐ 必须标估算 ✓


def test_budget_display_boundaries():
    """⭐ 提示线四点：3999 False / 4000 True / 5999 True / 6000 False（与 B3 一致 ✓ 不混用 ✗）"""
    import rt_view
    for used, want in ((3999, False), (4000, True), (5999, True), (6000, False)):
        got = rt_view.budget_display({'used': used, 'limit': 6000})['near_limit']
        assert got is want, (used, got, want)
    assert rt_view.budget_display()['unit'].startswith('token')          # 单位口径 ✓
    assert rt_view.budget_display({'used': 10, 'near_limit': False})['near_limit'] is False


# ── ⑤ 归属隔离（数据层强制 ✓）───────────────────────────────────────
def test_channel_view_denies_other_role_by_default(tmp_path):
    """⭐ 隔离（数据层 ✓）：① `my_recent` 内**他人条目直接不装** ✗
    ② `hall_summaries` 里 `private=True` 的他人类 → 不装 ✗ 且 trace 记 `deny 需显式索取` ✓"""
    import rt_view
    out = rt_view.channel_view(
        role='flash',
        my_recent=[{'role': 'nova', 'ptr': 'nova|2026-09-26|0009', 'text': '他人私聊内容' * 5},
                   {'role': 'flash', 'ptr': 'flash|2026-09-26|0001', 'text': '自己的近段' * 5}],
        hall_summaries=[{'role': 'nova', 'ptr': 'nova|2026-09-26|0010', 'text': '他人私文' * 5,
                         'private': True}],
    )
    ptrs = [m.get('ptr') for m in out['messages']]
    assert 'nova|2026-09-26|0009' not in ptrs, '他人条目不得混进 my_recent ✗'
    assert 'flash|2026-09-26|0001' in ptrs, '本角色近段应当装入 ✓'
    assert 'nova|2026-09-26|0010' not in ptrs, '他人私文**默认不得装** ✗'
    assert any('显式索取' in (t.get('why') or '') or '显式索取' in (t.get('drop_reason') or '')
               for t in out['trace']), out['trace']
    assert out['isolation']['cross_requested'] == []


def test_channel_view_allows_explicit_cross_request():
    import rt_view
    out = rt_view.channel_view(
        role='flash',
        hall_summaries=[{'role': 'nova', 'ptr': 'nova|2026-09-26|0010', 'text': '他人私文' * 5,
                         'private': True}],
        cross_requested=['nova|2026-09-26|0010'],
    )
    ptrs = [m.get('ptr') for m in out['messages']]
    assert 'nova|2026-09-26|0010' in ptrs, '显式索取后**应当**装入 ✓'
    assert out['isolation']['cross_requested'] == ['nova|2026-09-26|0010']
    assert not any(t.get('drop_reason') == 'deny 需显式索取' for t in out['trace']), out['trace']


# ── ③ 原文按需读取：同角色 ✓ / 跨角色拒 ✓ + 审计 ✓ / 缺失不静默 ✓ ──
def test_read_original_same_role_ok(tmp_path):
    import rt_view
    st = _store(tmp_path)
    ptrs = _seed(st)
    got = rt_view.read_original(requester='flash', store=st, ptr=ptrs[0])
    assert got['ok'] is True and got['denied'] is False and got['cross'] is False
    assert '全文内容' in str(got['rec'].get('text'))


def test_read_original_cross_role_denied_with_audit(tmp_path):
    import rt_view
    st = _store(tmp_path)
    ptrs = _seed(st, role='nova')
    seen = []
    got = rt_view.read_original(requester='flash', store=st, ptr=ptrs[0], audit=seen.append)
    assert got['ok'] is False and got['denied'] is True and got['cross'] is True
    assert '显式索取' in got['reason']
    assert seen and seen[-1]['kind'] == 'cross_read_denied' and seen[-1]['target'] == ptrs[0]


def test_read_original_cross_role_explicit_allowed_with_audit(tmp_path):
    import rt_view
    st = _store(tmp_path)
    ptrs = _seed(st, role='nova')
    seen = []
    got = rt_view.read_original(requester='flash', store=st, ptr=ptrs[0], explicit=True, audit=seen.append)
    assert got['ok'] is True and got['cross'] is True
    assert seen and seen[-1]['kind'] == 'cross_read_allowed' and seen[-1]['explicit'] is True


def test_read_original_missing_reports_reason(tmp_path):
    """缺失/已滚 → `ok=False` + **原因**（不抛 ✗ 不静默 ✓）+ 审计 ✓"""
    import rt_view
    st = _store(tmp_path)
    _seed(st)
    seen = []
    got = rt_view.read_original(requester='flash', store=st, role='flash', day='2026-09-26', seq=9999,
                                audit=seen.append)
    assert got['ok'] is False and got['denied'] is False
    assert '原文缺失' in got['reason'] or '原文已过期' in got['reason'], got
    assert seen and seen[-1]['kind'] == 'original_missing'


def test_audit_rejects_bad_object():
    import rt_view
    try:
        rt_view._audit(object(), {'k': 1})
    except TypeError:
        return
    raise AssertionError('审计出口类型错应当报错 ✗')


# ── 硬约束：只读 + 不出网（AST 级 ✓）───────────────────────────────
def test_module_has_no_write_or_network(tmp_path):
    src = io.open(MOD, encoding='utf-8').read()
    tree = ast.parse(src)
    banned_mods = {'urllib', 'requests', 'socket', 'http', 'subprocess'}
    got_mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            got_mods |= {a.name.split('.')[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            got_mods.add(n.module.split('.')[0])
    assert not (got_mods & banned_mods), got_mods & banned_mods
    # 无**写模式** open ✗（只读导出面不得写盘 ✓）
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and getattr(n.func, 'id', '') == 'open':
            modes = [a for a in n.args[1:3] if isinstance(a, ast.Constant)]
            for m in modes:
                assert not any(c in str(m.value) for c in 'wxa+'), m.value
            for kw in n.keywords:
                if kw.arg == 'mode':
                    assert not any(c in str(getattr(kw.value, 'value', '')) for c in 'wxa+')
    for bad in ('remove', 'unlink', 'rmtree', 'rmdir'):
        assert ('os.' + bad) not in src and ('shutil.' + bad) not in src
