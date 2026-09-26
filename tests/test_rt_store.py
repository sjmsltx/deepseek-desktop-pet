# -*- coding: utf-8 -*-
"""B1 护栏：`rt_store`（第 3 批 · 圆桌 L0/L1 存储）

设计 v1.1 四条**不变口径**（微信侧复核确认 ✓）：
  - L0 **永不替换为摘要** ✓
  - 回放**只读不产新行** ✓
  - 滚动**只动 L0** ✓
  - 缺失/已滚**必报错不静默** ✓
另盯：指针格式 ✓ · L1 append-only 幂等 ✓ · `round_id` ✓ · `schema_version` ✓ · **不出网** ✗
"""
from __future__ import annotations

import ast
import io
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MOD = ROOT / 'rt_store.py'


def _store(tmp_path):
    import rt_store
    return rt_store.Store(str(tmp_path / 'rt'))


# ── 指针：格式 + 纯函数往返 ✓ ─────────────────────────────────────────
def test_ptr_format_and_roundtrip():
    import rt_store
    p = rt_store.make_ptr('flash', '2026-09-26', 42)
    assert p == 'flash|2026-09-26|0042', p
    assert rt_store.parse_ptr(p) == {'role': 'flash', 'day': '2026-09-26', 'seq': 42}


def test_ptr_rejects_bad_format():
    import rt_store
    for bad in ('', 'flash|2026-9-26|0042', 'flash|2026-09-26|42', 'no-pipes', None):
        with pytest.raises(ValueError):
            rt_store.parse_ptr(bad)


# ── L0：全文追加 + 读回 ✓ ────────────────────────────────────────────
def test_append_and_read_full_text(tmp_path):
    st = _store(tmp_path)
    ptr = st.append('flash', 'role', '这是一段很长的原文' * 10, round_id='r-1', turn_no=2)
    assert ptr.endswith('|0001'), ptr
    rec = st.read('flash', '2026-09-26'.replace('2026-09-26', ptr.split('|')[1]), int(ptr.split('|')[2]))
    assert rec['text'] == '这是一段很长的原文' * 10, '⭐ L0 必须是**全文** ✗ 不能被摘要替换'
    assert rec['round_id'] == 'r-1' and rec['turn_no'] == 2
    # 序号自增 ✓
    p2 = st.append('flash', 'user', '第二条')
    assert p2.endswith('|0002'), p2


# ── ⭐ 缺失 / 已滚 → **必报错**（不静默 ✗）────────────────────────────
def test_missing_reports_loudly(tmp_path):
    import rt_store
    st = _store(tmp_path)
    with pytest.raises(rt_store.MissingOriginal):
        st.read('flash', '2026-01-01', 1)              # 从没写过 → 报错 ✓
    st.append('flash', 'role', 'x', day='2026-01-02')
    with pytest.raises(rt_store.MissingOriginal):
        st.read('flash', '2026-01-02', 99)             # 序号不存在 → 报错 ✓


# ── L1：append-only + 幂等 + round_id ✓ ──────────────────────────────
def test_l1_append_only_and_idempotent(tmp_path):
    st = _store(tmp_path)
    ptr = st.append('flash', 'role', 'hi', day='2026-01-03')
    assert st.add_summary(ptr, '摘要A', round_id='r-9', turn_no=1, kind='role') is True
    assert st.add_summary(ptr, '摘要A', round_id='r-9') is False, '同 ptr 同摘要应幂等跳过 ✓'
    assert st.add_summary(ptr, '摘要B') is True, '改摘要 → 允许追加新行 ✓（append-only ✓）'
    # ⭐ 文件行数 = 3 ✓（append-only 看**文件** ✗ 不看视图 ✓）
    lines = [l for l in io.open(st.summaries_path, encoding='utf-8').read().splitlines() if l.strip()]
    assert len(lines) == 2, lines   # 首次 1 行 + 改摘要追加 1 行 ✓（幂等那次未写 ✓）
    # ⭐ 视图 `summaries()` 按 ptr **取最后一条** ✓（幂等那次未写新行 ✓）
    rows = st.summaries(limit=None)
    assert len(rows) == 1, rows
    assert rows[0]['summary'] == '摘要B', '按 ptr 取**最后一条** ✓'
    # 行数只增不减 ✓
    n1 = len(io.open(st.summaries_path, encoding='utf-8').read().splitlines())
    st.add_summary(ptr, '摘要B')
    n2 = len(io.open(st.summaries_path, encoding='utf-8').read().splitlines())
    assert n1 == n2, 'append-only：幂等时不得写新行 ✓'


def test_summaries_filter_by_round(tmp_path):
    st = _store(tmp_path)
    a = st.append('flash', 'role', 'A', day='2026-01-04')
    b = st.append('pro', 'role', 'B', day='2026-01-04')
    st.add_summary(a, 'sa', round_id='r-1')
    st.add_summary(b, 'sb', round_id='r-2')
    assert [r['ptr'] for r in st.summaries(round_id='r-1')] == [a]
    assert [r['ptr'] for r in st.summaries(role='pro')] == [b]


# ── ⭐ 滚动：**只动 L0**（L1/meta/rolled 不动 ✗）──────────────────────
def test_roll_only_touches_l0(tmp_path):
    st = _store(tmp_path)
    ptrs = []
    for i in range(3):
        day = '2026-01-0%d' % (i + 1)
        p = st.append('flash', 'role', 'x' * 200, day=day)
        st.add_summary(p, '摘要%d' % i)
        ptrs.append(p)
    l1_before = Path(st.summaries_path).read_text(encoding='utf-8')
    assert st.l0_total_bytes() > 0
    rolled = st.roll(max_bytes=1)                       # 强制滚 ✓
    assert rolled, '应滚掉最旧的整天 ✓'
    assert rolled[0] == '2026-01-01', '必须从**最旧**开始 ✓'
    assert st.l0_total_bytes() < 3 * 200, st.l0_total_bytes()
    # ⭐ L1 只增加"标记行" ✓ 既有摘要行**一字未改** ✓
    l1_after = Path(st.summaries_path).read_text(encoding='utf-8')
    for line in l1_before.strip().splitlines():
        assert line in l1_after, '⭐ L1 既有行不得被改动 ✗'
    assert st.is_expired(ptrs[0]) is True, '被滚的 ptr 应标 expired ✓'
    assert os.path.isfile(st.rolled_path), 'rolled.jsonl 应记录 ✓'
    assert st.meta().get('schema_version') == 1, 'meta 带 schema_version ✓'


def test_rolled_readout_says_expired_not_silent(tmp_path):
    import rt_store
    st = _store(tmp_path)
    p = st.append('flash', 'role', '原文', day='2026-02-01')
    st.add_summary(p, '摘要', round_id='r-x')
    st.roll(max_bytes=1)
    with pytest.raises(rt_store.MissingOriginal):
        st.read('flash', '2026-02-01', 1)              # 已滚 → **报错** ✗ 不返回空 ✓


# ── 回放：**只读不产新行** ✓ ─────────────────────────────────────────
def test_replay_is_read_only(tmp_path):
    st = _store(tmp_path)
    st.append('flash', 'role', '内容一', day='2026-03-01')
    st.append('flash', 'user', '内容二', day='2026-03-01')
    before = Path(st.day_path('flash', '2026-03-01')).read_text(encoding='utf-8')
    rows = st.replay('flash', '2026-03-01')
    assert [r['source'] for r in rows] == ['L0', 'L0'] and len(rows) == 2
    after = Path(st.day_path('flash', '2026-03-01')).read_text(encoding='utf-8')
    assert before == after, '⭐ 回放只读 ✓ 不得产生新行 ✗'
    # 已滚 → 走 L1 摘要视图且带 expired ✓
    st.roll(max_bytes=1)
    rows2 = st.replay('flash', '2026-03-01')
    assert rows2 and rows2[0]['source'] == 'L1' and rows2[0]['expired'] is True, rows2


# ── 边界：**不出网** ✗ + 纯函数边界 ✓ ───────────────────────────────
def test_store_has_no_network_and_pure_parsers():
    tree = ast.parse(io.open(MOD, encoding='utf-8').read())
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split('.')[0] in ('requests', 'http') or 'request' in a.name:
                    bad.append('import:%s@%d' % (a.name, node.lineno))
        if isinstance(node, ast.ImportFrom) and (node.module or '').split('.')[0] in ('requests', 'http', 'urllib'):
            bad.append('from:%s@%d' % (node.module, node.lineno))
    assert not bad, f'rt_store 不得出网 ✗：{bad}'
    # make_ptr / parse_ptr 必须是**纯函数**（体内无 open/IO ✓）
    for fn in ('make_ptr', 'parse_ptr'):
        f = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == fn)
        for node in ast.walk(f):
            if isinstance(node, ast.Call):
                nm = getattr(node.func, 'id', None) or getattr(node.func, 'attr', None)
                assert nm not in ('open', 'write', 'urlopen'), f'{fn} 必须纯 ✓（出现 {nm} ✗）'
