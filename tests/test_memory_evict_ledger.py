# -*- coding: utf-8 -*-
"""淘汰台账测试（2026-11-02）

## 锁什么

1. **先记后删**：台账里的条目必须在淘汰后真的不在库里（证明顺序对）
2. **内容齐全**：时间/原因/标题/weight/access_count 都在，且字段缺失不崩
3. **pinned 不进台账**（它没被淘汰）
4. **写失败不阻断淘汰**，但要落痕（不是静默）
5. **轮转**：超 EVICTED_MAX_LINES 后旧文件变成 .1，台账本身不无限长
6. **只动淘汰路径**：不淘汰时不写台账（防每写一条都记一笔废账）
"""
import io
import json
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import memory_events as me  # noqa: E402


def _mk(tmp_path, cap=5):
    """造一个上限很小的事件库，方便触发淘汰"""
    p = str(tmp_path / 'memories.json')
    old = me.MAX_MEMORIES
    me.MAX_MEMORIES = cap
    m = me.MemoryEvents(p)
    return m, old


def test_evicted_entries_are_recorded(tmp_path):
    """淘汰了就必须留下账：谁、何时、为何"""
    m, old = _mk(tmp_path, cap=3)
    try:
        for i in range(6):
            m.add('flash', 'event', '标题%d' % i, '细节%d' % i)
        rows = m.evicted_recent(50)
        assert rows, '淘汰了 3 条却一条台账都没有'
        assert len(rows) >= 3, '台账条数少于淘汰条数：%d' % len(rows)
        for r in rows:
            for k in ('t', 'reason', 'title', 'kept'):
                assert k in r, '台账缺字段 %s：%r' % (k, r)
            assert r['reason'] == 'overflow'
        # 台账里的标题必须是**真的被删掉的**
        alive = {(x.get('title') or '') for x in m.all()}
        for r in rows:
            assert r['title'] not in alive, '台账里的 %r 其实还在库里（顺序反了？）' % r['title']
    finally:
        me.MAX_MEMORIES = old


def test_record_before_delete(tmp_path):
    """⭐ 顺序：台账里出现的，必须在库里已经不在（先记后删）"""
    m, old = _mk(tmp_path, cap=2)
    try:
        for i in range(5):
            m.add('flash', 'event', 'T%d' % i, 'D%d' % i)
        alive = {(x.get('title') or '') for x in m.all()}
        recorded = {r['title'] for r in m.evicted_recent(100)}
        assert recorded, '没有台账'
        assert not (recorded & alive), '有条目既在台账又在库里 —— 先记后删的顺序错了'
        assert len(alive) == 2, '库里应剩 2 条，实剩 %d' % len(alive)
    finally:
        me.MAX_MEMORIES = old


def test_ledger_tolerates_missing_fields(tmp_path):
    """老数据有 3 种字段集（WX-172 发现 D）⇒ 缺字段不许崩，写成 null"""
    m, old = _mk(tmp_path, cap=2)
    try:
        m._memories = [
            {'id': 1, 'title': '完整', 'time': '2026-10-01 10:00', 'weight': 0.6,
             'access_count': 3, 'origin': 'user', 'repeat_count': 1},
            {'id': 2, 'title': '无计数', 'time': '2026-10-02 10:00'},          # 缺 weight 等
            {'id': 3, 'title': '中间态', 'time': '2026-10-03 10:00',
             'access_count': 1, 'weight': 0.5},                                # 缺 pinned/origin
        ]
        m._memories.append({'id': 4, 'title': '新的', 'time': '2026-10-04 10:00'})
        m.add('flash', 'event', '触发淘汰', 'x')
        rows = m.evicted_recent(50)
        assert rows, '缺字段的数据把台账搞崩了'
        got = {r['title'] for r in rows}
        assert '完整' in got and '无计数' in got
        for r in rows:
            if r['title'] == '无计数':
                assert r['weight'] is None, '缺字段应写 null，实际 %r' % r['weight']
    finally:
        me.MAX_MEMORIES = old


def test_pinned_not_in_ledger(tmp_path):
    """pinned 条目不会被淘汰 ⇒ 台账里不该出现"""
    m, old = _mk(tmp_path, cap=3)
    try:
        a = m.add('flash', 'event', '钉住的', 'import')
        m.pin(a.get('id'))
        for i in range(8):
            m.add('flash', 'event', '普通%d' % i, 'd%d' % i)
        rows = m.evicted_recent(100)
        titles = {r['title'] for r in rows}
        assert '钉住的' not in titles, 'pinned 条目出现在台账里，说明它被淘汰了'
        assert '钉住的' in {(x.get('title') or '') for x in m.all()}, 'pinned 条目被删了'
    finally:
        me.MAX_MEMORIES = old


def test_no_ledger_when_no_eviction(tmp_path):
    """没触发淘汰就不许写台账 —— 否则每写一条都记一笔废账"""
    m, old = _mk(tmp_path, cap=100)
    try:
        for i in range(5):
            m.add('flash', 'event', 'T%d' % i, 'D%d' % i)
        assert m.evicted_recent(10) == [], '没淘汰却写了台账'
        assert not os.path.exists(m.evicted_path), '台账文件不该被创建'
    finally:
        me.MAX_MEMORIES = old


def test_ledger_write_failure_does_not_block_eviction(tmp_path, monkeypatch, caplog):
    """台账写不进去时：淘汰照常（否则库无限长），但必须落痕

    ⚠ 用**真实失败路径**（把台账路径指到一个不存在的目录），不用 mock 掉 open ——
       mock 掉 open 会连 _save 一起打坏，测的就不是「台账失败」而是「整库失败」了。
    """
    m, old = _mk(tmp_path, cap=2)
    try:
        # 让台账写到一个不存在的深层目录 ⇒ 真实 OSError
        bad = str(tmp_path / 'no_such_dir' / 'deeper' / me.EVICTED_NAME)
        m.evicted_path = bad
        with caplog.at_level('WARNING', logger='pet.memory_events'):
            for i in range(5):
                m.add('flash', 'event', 'T%d' % i, 'D%d' % i)
        # 淘汰照常发生
        assert len(m.all()) == 2, '台账写失败把淘汰也带崩了'
        # 且必须落痕（不是静默）
        assert any('淘汰台账写入失败' in r.getMessage() for r in caplog.records), \
            '台账失败没有任何痕迹'
        # 库文件本身完好
        assert os.path.exists(m.path)
    finally:
        me.MAX_MEMORIES = old


def test_ledger_rotation(tmp_path, monkeypatch):
    """台账超 EVICTED_MAX_LINES 就轮转，不许无限长"""
    m, old = _mk(tmp_path, cap=2)
    try:
        monkeypatch.setattr(me, 'EVICTED_MAX_LINES', 3)
        # 先塞满 3 行
        io.open(m.evicted_path, 'w', encoding='utf-8').write(
            '\n'.join(json.dumps({'t': 'x', 'reason': 'seed', 'title': 'S%d' % i})
                      for i in range(3)) + '\n')
        m.add('flash', 'event', 'A', 'a')
        m.add('flash', 'event', 'B', 'b')
        m.add('flash', 'event', 'C', 'c')      # 触发淘汰 → 写台账 → 应先轮转
        bak = m.evicted_path + '.1'
        assert os.path.exists(bak), '超上限后没有轮转出 .1'
        with io.open(m.evicted_path, encoding='utf-8') as fh:
            now = [t for t in fh.read().splitlines() if t.strip()]
        assert len(now) < 10, '轮转后台账仍有 %d 行' % len(now)
    finally:
        me.MAX_MEMORIES = old


def test_evicted_recent_empty_when_no_file(tmp_path):
    """台账不存在时返回空表，不抛"""
    m = me.MemoryEvents(str(tmp_path / 'm.json'))
    assert m.evicted_recent(5) == []


def test_only_eviction_path_is_touched():
    """结构钉：台账逻辑只许出现在淘汰路径上（防有人顺手在检索/写入里也记一笔）"""
    src = io.open(os.path.join(BASE, 'memory_events.py'), encoding='utf-8').read()
    import ast as _ast
    tree = _ast.parse(src)
    hits = []
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Call) and isinstance(node.func, _ast.Attribute):
            if node.func.attr == 'record_evicted':
                hits.append(node.lineno)
    assert len(hits) == 1, 'record_evicted 被调用 %d 次，只该在淘汰处调一次：%r' % (len(hits), hits)
