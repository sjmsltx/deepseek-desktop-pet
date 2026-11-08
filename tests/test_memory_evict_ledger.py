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
    """老数据有 3 种字段集（评审-172 发现 D）⇒ 缺字段不许崩，写成 null"""
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
    """结构钉：台账调用只许出现在**淘汰 if 块**内。

    ⚠ 判据演进（2026-11-08，外部复核用 AST 变异实测指出我上一版改松了）：
      旧版：`record_evicted` 调用次数 == 1
            问题：区分 critical 溢出与普通滚动必须两个调用点 ⇒ 误报
      我上一版：都在同一个函数内、且是 add、总数 ≤ 3
            问题：**放过「在 add 内、淘汰块之前无条件记一笔」这种变异** ——
                  而那条正是本钉 docstring 说要防的（每次写入都记一行台账）
      现行：每个调用点必须落在 `if len(self._memories) > MAX_MEMORIES:` 的区间内
            比次数精确，且不受调用点数量变化影响

    变异实测（三种变异 × 三版判据）：
        V0 现状                        旧判据 红 / 我上一版 过 / 现行 过
        V1 add 内、淘汰块之前无条件记     旧判据 红 / 我上一版 **过** / 现行 红
        V3 add 之外新函数里记            旧判据 红 / 我上一版 红 / 现行 红
    """
    src = io.open(os.path.join(BASE, 'memory_events.py'), encoding='utf-8').read()
    import ast as _ast
    tree = _ast.parse(src)

    evict_ranges = []
    for node in _ast.walk(tree):
        if isinstance(node, _ast.If) and isinstance(node.test, _ast.Compare):
            seg = _ast.get_source_segment(src, node.test) or ''
            if '_memories' in seg and 'MAX_MEMORIES' in seg:
                evict_ranges.append((node.lineno, node.end_lineno or node.lineno))

    assert evict_ranges, (
        '找不到淘汰 if 块（`if len(self._memories) > MAX_MEMORIES:`）——'
        '淘汰逻辑被重构了？这条钉需要同步更新，而不是删掉')

    calls = []
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Call) and isinstance(node.func, _ast.Attribute):
            if node.func.attr == 'record_evicted':
                calls.append(node.lineno)

    assert calls, '台账一次都没记 —— 淘汰路径上的调用被删了？'

    outside = [c for c in calls
               if not any(lo <= c <= hi for lo, hi in evict_ranges)]
    assert not outside, (
        'record_evicted 出现在淘汰 if 块之外（行 %r）；淘汰块区间 %r。'
        '台账只许在「算完哪些要淘汰」之后记 —— 放在块外会导致每次写入都记一行、'
        '记的还是没被淘汰的条目' % (outside, evict_ranges))

# ══════════ content_hash / committed（2026-11-03，评审-174 §六 第 3 条）══════════

def test_ledger_has_content_hash(tmp_path):
    """⭐ content_hash 必须存在且格式对 —— 库删了 id 之后靠它认出删的是什么。

    微信原话：「只记 id 的话，库里删了 id 就再也查不出当时删的是什么。」

    ⚠ 第一版我在这个函数里留了两段没用上的代码（`m2`/`o2` 建了不跑、`h1` 算了不用），
      自查时删掉 —— 测试里的死代码比产品里的更危险，会让人以为「这里验过了」。
    """
    m, old = _mk(tmp_path, cap=2)
    try:
        m._memories = [
            {'id': 1, 'title': '唯一标题甲', 'detail': '细节甲', 'time': '2026-10-01 10:00'},
            {'id': 2, 'title': '唯一标题乙', 'detail': '细节乙', 'time': '2026-10-02 10:00'},
            {'id': 3, 'title': '新的', 'time': '2026-10-03 10:00'},
        ]
        m.add('flash', 'event', '触发', 'x')
        rows = m.evicted_recent(50)
        assert rows, '没有台账'
        for r in rows:
            assert 'content_hash' in r, '台账缺 content_hash'
            ch = r['content_hash']
            assert isinstance(ch, str) and len(ch) == 16, \
                'content_hash 应为 16 位十六进制串，实际 %r' % (ch,)
            assert all(c in '0123456789abcdef' for c in ch), \
                'content_hash 含非十六进制字符：%r' % (ch,)
    finally:
        me.MAX_MEMORIES = old


def test_ledger_content_hash_differs_for_different_content(tmp_path):
    """不同内容的 content_hash 必须不同（否则认不出「是哪一版」）。"""
    m, old = _mk(tmp_path, cap=2)
    try:
        m._memories = [
            {'id': 1, 'title': '标题甲', 'detail': '细节甲', 'time': '2026-10-01 10:00'},
            {'id': 2, 'title': '标题乙', 'detail': '细节乙', 'time': '2026-10-02 10:00'},
            {'id': 3, 'title': '新的', 'time': '2026-10-03 10:00'},
        ]
        m.add('flash', 'event', '触发', 'x')
        rows = m.evicted_recent(50)
        hashes = [r['content_hash'] for r in rows]
        assert len(set(hashes)) == len(hashes), '不同内容的 content_hash 撞了：%r' % hashes
    finally:
        me.MAX_MEMORIES = old


def test_ledger_committed_flips_after_delete(tmp_path):
    """⭐ 淘汰成功后 committed 必须是 True（对账时靠它分辨「记了但没删成」）。"""
    m, old = _mk(tmp_path, cap=2)
    try:
        for i in range(5):
            m.add('flash', 'event', 'T%d' % i, 'D%d' % i)
        rows = m.evicted_recent(50)
        assert rows, '没有台账'
        assert all(r.get('committed') is True for r in rows), (
            '删除已生效但 committed 不是 True：%r'
            % [(r.get('id'), r.get('committed')) for r in rows])
    finally:
        me.MAX_MEMORIES = old


def test_update_committed_works(tmp_path):
    """update_evicted_committed 能把 false 改回 true，且不碰别的行。"""
    m, old = _mk(tmp_path, cap=2)
    try:
        for i in range(4):
            m.add('flash', 'event', 'T%d' % i, 'D%d' % i)
        rows = m.evicted_recent(50)
        ids = [r['id'] for r in rows]
        # 人为全部改回 False（模拟「记账后被杀」）
        n = m.update_evicted_committed(ids, False)
        assert n == len(ids), '改了 %d 条，应为 %d' % (n, len(ids))
        assert all(r.get('committed') is False for r in m.evicted_recent(50))
        # 再改回 True
        n2 = m.update_evicted_committed(ids, True)
        assert n2 == len(ids)
        assert all(r.get('committed') is True for r in m.evicted_recent(50))
        # 不存在的 id 不该报错
        assert m.update_evicted_committed([999999], True) == 0
    finally:
        me.MAX_MEMORIES = old


def test_ledger_version_marked(tmp_path):
    """v=2 标记存在 —— 老台账没这两个字段，靠它区分格式代。"""
    m, old = _mk(tmp_path, cap=2)
    try:
        for i in range(4):
            m.add('flash', 'event', 'T%d' % i, 'D%d' % i)
        rows = m.evicted_recent(50)
        assert rows and all(r.get('v') == 2 for r in rows), '台账缺 v=2 标记'
    finally:
        me.MAX_MEMORIES = old

