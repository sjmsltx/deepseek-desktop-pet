# -*- coding: utf-8 -*-
"""B3 护栏：`rt_assembler`（L2 工作集 · 五优先级 / 预算 / trace / 归属隔离）

设计 v1.1 §3 + §F 要盯死（缺一即视为未完成 ✗）：
  ① **①② 永不砍** ✗ · ② 裁剪顺序：**先 ④ 相关性 → 再 ③ 时效窗口（最旧优先）** ✗
  ③ **归属隔离**：他人私聊全文**默认不装** ✗（显式索取才装 ✓ 并留 `deny` 痕迹 ✓）
  ④ `estimated` 恒为 true ✓（界面须显示"估算" ✓）
  ⑤ **上限 6000 / 提示线 4000**：`4000 ≤ used < 6000` → `near_limit=true` ✓；`used ≥ 6000` **不在此处理** ✗
  ⑥ `k=8` 预算吃紧 → **8→4** ✓ 且**必写 `drop_reason`** ✗（不静默）
  ⑦ trace 每条带 `why` ✓ · 纯函数 ✓（无 IO/网 ✗）
"""
from __future__ import annotations

import ast
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOD = ROOT / 'rt_assembler.py'


def _a():
    import rt_assembler
    return rt_assembler


def _txt(n):
    return 'x' * int(n)


def _it(ptr, n, **kw):
    d = {'ptr': ptr, 'text': _txt(n)}
    d.update(kw)
    return d


# ── ① ①② 永不砍（极小预算也保留 ✓）──────────────────────────────────
def test_priority_1_2_never_dropped():
    m = _a()
    r = m.build(role='flash', budget=10,
                mentions=[_it('m1', 50)],
                my_recent=[{'ptr': 'r1', 'role': 'flash', 'text': _txt(50)}],
                hall_summaries=[_it('h1', 4000, ts='2026-09-26T10:00:00')],
                related=[_it('q1', 4000)])
    prios = {x['priority'] for x in r['messages']}
    assert 1 in prios and 2 in prios, '①② 必须保留 ✗'
    assert 3 not in prios and 4 not in prios, '预算极小 → ③④ 应被砍 ✓'
    assert r['budget']['used'] > r['budget']['limit'], '①② 可超预算（永不砍 ✓）'


# ── ② 裁剪顺序：先 ④ 后 ③ ───────────────────────────────────────────
def test_drop_order_related_before_window():
    m = _a()
    r = m.build(role='flash', budget=120,
                hall_summaries=[_it('h1', 200, ts='2026-09-26T09:00:00'),
                                _it('h2', 200, ts='2026-09-26T11:00:00')],
                related=[_it('q1', 200)])
    order = [t['ptr'] for t in r['trace'] if not t['kept']]
    assert order and order[0] == 'q1', f'⭐ 必须先砍 ④ 相关性 ✗ 实际顺序 {order}'


def test_window_drops_oldest_first():
    m = _a()
    # 200 字符 → est 100 tok ✓（÷2 保守估 ✓）；两条共 200 tok ✓ → budget=150 迫使砍 1 条
    r = m.build(role='flash', budget=150,
                hall_summaries=[_it('old', 200, ts='2026-09-26T08:00:00'),
                                _it('new', 200, ts='2026-09-26T12:00:00')])
    dropped = [t['ptr'] for t in r['trace'] if not t['kept']]
    assert dropped and dropped[0] == 'old', f'③ 应先砍最旧 ✗ 实际 {dropped}'
    assert 'new' in [x.get('ptr') for x in r['messages']], '较新的应保留 ✓'


# ── ③ 归属隔离（他人私聊默认不装 ✗）───────────────────────────────────
def test_privacy_isolation_denies_by_default():
    m = _a()
    r = m.build(role='flash',
                hall_summaries=[{'ptr': 'p1', 'text': _txt(20), 'role': 'pro', 'private': True}])
    assert all(x.get('ptr') != 'p1' for x in r['messages']), '他人私聊默认**不得装** ✗'
    deny = [t for t in r['trace'] if not t['kept']]
    assert deny and 'deny' in str(deny[0].get('drop_reason', '')), deny


def test_privacy_isolation_allows_explicit_request():
    m = _a()
    r = m.build(role='flash', cross_requested=['p1'],
                hall_summaries=[{'ptr': 'p1', 'text': _txt(20), 'role': 'pro', 'private': True}])
    assert any(x.get('ptr') == 'p1' for x in r['messages']), '显式索取后应可装 ✓'


def test_my_recent_filters_other_roles():
    m = _a()
    r = m.build(role='flash',
                my_recent=[{'ptr': 'a', 'role': 'flash', 'text': _txt(20)},
                           {'ptr': 'b', 'role': 'pro', 'text': _txt(20)}])
    assert {x.get('ptr') for x in r['messages'] if x['priority'] == 2} == {'a'}, '② 只收自己的 ✓'


# ── ④ estimated 恒 true ✓ ────────────────────────────────────────────
def test_estimated_always_true():
    m = _a()
    for budget in (1, 6000, 99999):
        r = m.build(role='flash', budget=budget, mentions=[_it('m', 10)])
        assert r['budget']['estimated'] is True
        assert r['budget']['unit'] == 'token(估)', '界面须能显示"估算" ✓'


# ── ⑤ near_limit 阈值四点 ────────────────────────────────────────────
def test_near_limit_thresholds():
    m = _a()
    # used = est_tokens(mention) + est_tokens(related) ✓（mentions 1 字符 → 1 tok ✓）
    def used_for(related_chars):
        r = m.build(role='flash', budget=6000, mentions=[_it('m', 1)],
                    related=[_it('q', related_chars)])
        return r['budget']['used'], r['budget']['near_limit']
    u1, n1 = used_for(7996)      # 1 + 3998 = 3999 → False ✓
    u2, n2 = used_for(7998)      # 1 + 3999 = 4000 → True  ✓
    assert (u1, n1) == (3999, False), (u1, n1)
    assert (u2, n2) == (4000, True), (u2, n2)


def test_near_limit_false_at_or_above_limit():
    """`used ≥ 6000` → **不在此处理** ✗（走拦截路径 ✓）→ near_limit 为 False ✓"""
    m = _a()
    r = m.build(role='flash', budget=6000, mentions=[_it('m', 20000)])   # 10000 tok ✓
    assert r['budget']['used'] >= 6000
    assert r['budget']['near_limit'] is False, '≥上限应由拦截路径处理 ✗ 此处不得置 true ✗'


# ── ⑥ k 联动：8→4 且**必写 drop_reason** ✗ ───────────────────────────
def test_k_downgrade_writes_drop_reason():
    m = _a()
    mine = [{'ptr': 'r%d' % i, 'role': 'flash', 'text': _txt(400)} for i in range(10)]  # 每条 200 tok
    r = m.build(role='flash', budget=6000, k=8, my_recent=mine,
                hall_summaries=[_it('h', 9000, ts='2026-09-26T10:00:00')])              # 4500 tok
    p2 = [x for x in r['messages'] if x['priority'] == 2]
    assert len(p2) == 4, f'⭐ 预算吃紧应降到 K_TIGHT=4 ✗ 实际 {len(p2)}'
    reasons = [str(t.get('drop_reason') or '') for t in r['trace'] if not t['kept']]
    assert any('k 降级' in x for x in reasons), f'降级必须写 drop_reason ✗ 实际 {reasons}'


# ── ⑦ trace 每条带 why ✓ · 纯函数 ✓ ─────────────────────────────────
def test_trace_every_entry_has_why():
    m = _a()
    r = m.build(role='flash', mentions=[_it('m', 10)], my_recent=[{'ptr': 'r', 'role': 'flash', 'text': 'x' * 10}],
                hall_summaries=[_it('h', 10)], related=[_it('q', 10)])
    assert r['trace'], 'trace 不得为空 ✓'
    for t in r['trace']:
        assert str(t.get('why') or '').strip(), f'每条 trace 必须带 why ✗：{t}'


def test_pure_no_io_no_network():
    src = Path(MOD).read_text(encoding='utf-8')
    tree = ast.parse(src)
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            nm = getattr(node.func, 'id', None) or getattr(node.func, 'attr', None)
            if nm in ('open', 'urlopen', 'request', 'system'):
                bad.append('%s@%d' % (nm, node.lineno))
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split('.')[0] in ('requests', 'http', 'socket', 'urllib', 'os', 'random', 'time'):
                    bad.append('import:%s@%d' % (a.name, node.lineno))
        if isinstance(node, ast.ImportFrom) and (node.module or '').split('.')[0] in ('requests', 'http', 'socket', 'urllib', 'os', 'random', 'time'):
            bad.append('from:%s@%d' % (node.module, node.lineno))
    assert not bad, f'rt_assembler 必须纯 ✓（无 IO/网/随机/时间 ✗）：{bad}'
