# -*- coding: utf-8 -*-
"""critical 溢出的容量行为（2026-11-08，外部复核指出的退化边界）

## 这条锁钉的是什么

critical 条目（服药/过敏/输液这类「失效代价高」的事件）**豁免淘汰**，
而词表命中是单向累积的 —— 没有出口。所以当 critical 攒到接近上限时，
`keep = max(0, 上限 - pinned - crit)` 会变成 0，把普通事件全部挤掉。

改前实测：写入 250 条 critical + 10 条普通 ⇒ 库内 200 条全是 critical，普通 0 条，
且最旧的 critical 被 `merged[-上限:]` 从头部静默截掉。

现在给普通留 `RESERVE_NORMAL` 的底线，critical 超出部分单独记台账
reason='critical_overflow'。

## 这些用例的性质

`test_critical_overflow_is_capped` 是**行为锁**（要求新行为）；
`test_reserve_normal_zero_reproduces_old_bug` 保留旧行为作对照 ——
它证明「底线确实在起作用」，而不是「碰巧没溢出」。

⚠ 现库 critical event 为 0 条，今天触发不到。但它是单调的：只会越来越接近。
"""
import os

import memory_events as mev


def _store(tmp_path, cap, reserve):
    old_cap, old_res = mev.MAX_MEMORIES, mev.RESERVE_NORMAL
    mev.MAX_MEMORIES, mev.RESERVE_NORMAL = cap, reserve
    try:
        st = mev.MemoryEvents(str(tmp_path / 'memories.json'))
    finally:
        mev.MAX_MEMORIES, mev.RESERVE_NORMAL = old_cap, old_res
    return st


def _fill(st, n_crit, n_normal):
    for i in range(n_crit):
        st.add('flash', 'event', '用户正在服药第%d次' % i, '每天两次')
    for i in range(n_normal):
        st.add('flash', 'event', '普通事件 %d' % i, '细节')


def _split(items):
    crit = [m for m in items if mev._is_critical_event(m)]
    normal = [m for m in items if not mev._is_critical_event(m)]
    return crit, normal


def test_critical_overflow_is_capped(tmp_path):
    """critical 超出「预算 - 底线」时，普通事件必须仍有位置。

    这是本组的主用例：改前普通剩 0 条，改后必须 > 0 且等于底线名额。
    """
    old_cap, old_res = mev.MAX_MEMORIES, mev.RESERVE_NORMAL
    mev.MAX_MEMORIES, mev.RESERVE_NORMAL = 60, 10
    try:
        st = mev.MemoryEvents(str(tmp_path / 'a.json'))
        _fill(st, 100, 10)
        crit, normal = _split(st.all())
        assert len(normal) > 0, (
            'critical 溢满后普通事件被全灭 —— RESERVE_NORMAL 没生效（普通 %d 条）'
            % len(normal))
        assert len(normal) == min(10, mev.RESERVE_NORMAL), (
            '普通事件应恰好保留底线名额，实保留 %d 条' % len(normal))
        assert len(st.all()) <= mev.MAX_MEMORIES, '总量超上限'
    finally:
        mev.MAX_MEMORIES, mev.RESERVE_NORMAL = old_cap, old_res


def test_reserve_normal_zero_reproduces_old_bug(tmp_path):
    """对照组：把底线设 0，旧缺陷必须重现 —— 证明上面那条是底线在起作用。

    ⚠ 这条**故意断言错误行为**。它存在的意义是：如果哪天有人把底线去掉，
    上面那条会红，但可能有人会去改上面那条的期望；有这条对照在，
    就知道「普通 0 条」是已知的旧行为，不是新期望。
    """
    old_cap, old_res = mev.MAX_MEMORIES, mev.RESERVE_NORMAL
    mev.MAX_MEMORIES, mev.RESERVE_NORMAL = 60, 0
    try:
        st = mev.MemoryEvents(str(tmp_path / 'b.json'))
        _fill(st, 100, 10)
        crit, normal = _split(st.all())
        assert len(normal) == 0, (
            '底线设为 0 时本应重现「普通全灭」，实际还剩 %d 条 —— '
            '说明这条对照已失效，上面那条的结论也就没有参照了' % len(normal))
    finally:
        mev.MAX_MEMORIES, mev.RESERVE_NORMAL = old_cap, old_res


def test_critical_overflow_is_recorded_with_its_own_reason(tmp_path):
    """critical 溢出必须单独记台账，reason 与普通滚动区分开。

    分不开的话，以后查「这条服药记忆去哪了」只会看到 overflow，
    看不出是「保护把容量吃掉了」。
    """
    old_cap, old_res = mev.MAX_MEMORIES, mev.RESERVE_NORMAL
    mev.MAX_MEMORIES, mev.RESERVE_NORMAL = 60, 10
    try:
        st = mev.MemoryEvents(str(tmp_path / 'c.json'))
        _fill(st, 100, 10)
        rows = st.evicted_recent(10000)
        reasons = {r.get('reason') for r in rows}
        assert 'critical_overflow' in reasons, (
            '台账里没有 critical_overflow，实际 reason：%r' % (reasons,))
    finally:
        mev.MAX_MEMORIES, mev.RESERVE_NORMAL = old_cap, old_res


def test_critical_keeps_newest_when_over_capacity(tmp_path):
    """critical 溢出时保留**最新**的，不是最旧的。

    旧实现用 merged[-上限:] 从头部截，丢的是最旧的 —— 静默且方向可疑：
    「最近才发生的急事」比「两年前的」更该留。
    """
    old_cap, old_res = mev.MAX_MEMORIES, mev.RESERVE_NORMAL
    mev.MAX_MEMORIES, mev.RESERVE_NORMAL = 60, 10
    try:
        st = mev.MemoryEvents(str(tmp_path / 'd.json'))
        _fill(st, 100, 0)
        crit, _ = _split(st.all())
        titles = [m.get('title') or '' for m in crit]
        assert '用户正在服药第99次' in titles, (
            '最新那条 critical 被淘汰了，实际保留到：%r' % (titles[-1] if titles else None,))
        assert '用户正在服药第0次' not in titles, (
            '最旧那条 critical 竟然还在 —— 说明截断方向反了')
    finally:
        mev.MAX_MEMORIES, mev.RESERVE_NORMAL = old_cap, old_res


def test_normal_events_unaffected_below_capacity(tmp_path):
    """没到上限时，一切照旧：普通事件不该被新逻辑动到。

    ⚠ 这条防的是「为了修溢出把正常路径改坏」—— 最常见的连带伤害。
    """
    old_cap, old_res = mev.MAX_MEMORIES, mev.RESERVE_NORMAL
    mev.MAX_MEMORIES, mev.RESERVE_NORMAL = 60, 10
    try:
        st = mev.MemoryEvents(str(tmp_path / 'e.json'))
        _fill(st, 5, 10)
        crit, normal = _split(st.all())
        assert len(crit) == 5, 'critical 条数被动了：%d' % len(crit)
        assert len(normal) == 10, '普通条数被动了：%d' % len(normal)
        assert len(st.all()) == 15
    finally:
        mev.MAX_MEMORIES, mev.RESERVE_NORMAL = old_cap, old_res


def test_reserve_normal_is_positive_by_default():
    """产品默认值必须是正的 —— 设 0 等于把这条修复关掉。"""
    assert mev.RESERVE_NORMAL > 0, '默认 RESERVE_NORMAL=%r，修复等于没开' % (mev.RESERVE_NORMAL,)
    assert mev.RESERVE_NORMAL < mev.MAX_MEMORIES, '底线不该吃满整个上限'
