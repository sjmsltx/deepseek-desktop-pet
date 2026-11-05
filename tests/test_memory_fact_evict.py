# -*- coding: utf-8 -*-
"""facts 权重与淘汰测试（2026-11-04）

锁六件事：
1. base 权重真的用 importance 兜底（否则淘汰退化成按时间）
2. 身份条目 / pinned 永不淘汰
3. 淘汰挑的是「低权重 + 旧」的，不是单纯最旧的
4. 淘汰只改 status，不物理删除（原件保留）
5. 台账先记账、字段齐全、缺字段不崩
6. bump 真的累积（weight / access_count / last_access）
"""
import io
import json
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import memory_events as mev          # noqa: E402
import memory_fact_evict as mfe      # noqa: E402


def _f(fid, content, imp=3, days_ago=0, status='active', **kw):
    """造一条事实，时间按「多少天前」倒推（便于测衰减）"""
    import datetime
    t = (datetime.datetime.now() - datetime.timedelta(days=days_ago)).strftime(
        '%Y-%m-%dT%H:%M:%S.%f')
    d = {'id': fid, 'content': content, 'importance': imp,
         'created_at': t, 'updated_at': t, 'status': status, 'roles': 'both'}
    d.update(kw)
    return d


# ---------- 1. base 权重用 importance 兜底 ----------

def test_base_weight_uses_importance_when_no_weight_field():
    """存量 44 条没有 weight ⇒ 必须用 importance/5，否则所有人同分"""
    assert mfe.fact_base_weight(_f('a', 'x', imp=5)) == 1.0
    assert mfe.fact_base_weight(_f('a', 'x', imp=3)) == pytest.approx(0.6)
    assert mfe.fact_base_weight(_f('a', 'x', imp=1)) == pytest.approx(0.2)


def test_explicit_weight_wins_over_importance():
    """有 weight 时以它为准（bump 累积的结果不该被 importance 盖掉）"""
    assert mfe.fact_base_weight(_f('a', 'x', imp=1, weight=0.9)) == pytest.approx(0.9)


def test_base_weight_tolerates_bad_values():
    for bad in (('importance', 'abc'), ('importance', None), ('importance', 99),
                ('importance', -5)):
        f = _f('a', 'x')
        f[bad[0]] = bad[1]
        v = mfe.fact_base_weight(f)
        assert 0.0 <= v <= 1.0, '越界值没夹住：%r -> %r' % (bad, v)


def test_importance_not_uniform():
    """★ 若所有人都同分，说明兜底没生效 —— 这是本模块最容易白做的地方"""
    ws = {mfe.fact_base_weight(_f('x', 'x', imp=i)) for i in (1, 3, 5)}
    assert len(ws) == 3, '不同 importance 得到了相同权重：%r' % ws


# ---------- 2. 身份 / pinned 豁免 ----------

def test_identity_never_decays():
    ident = _f('i1', '我的名字叫小蓝', imp=3, days_ago=400)
    normal = _f('n1', '用户爱吃桃片', imp=3, days_ago=400)
    assert mfe.fact_effective_weight(ident) == pytest.approx(
        mfe.fact_base_weight(ident)), '身份条目被衰减了'
    assert mfe.fact_effective_weight(normal) < 0.1, '普通条目不该免疫衰减'


def test_pinned_and_identity_are_protected():
    assert mfe.protected(_f('a', '我的名字叫小蓝'))
    assert mfe.protected(_f('a', '随便一条', pinned=True))
    assert not mfe.protected(_f('a', '随便一条'))


def test_protected_survive_even_when_over_capacity():
    """保护条目占满名额时，不许被淘汰（宁可超容）"""
    facts = [_f('i%d' % i, '我的名字叫小蓝%d' % i) for i in range(3)]
    facts += [_f('n%d' % i, '噪声%d' % i, days_ago=100) for i in range(5)]
    evicted, kept = mfe.plan_eviction(facts, cap=2)
    # cap=2 但 3 条受保护 ⇒ 一个都不能动
    assert evicted == [], '保护条目超容时却淘汰了东西'
    assert kept == 8


# ---------- 3. 淘汰挑「低权重 + 旧」，不是单纯最旧 ----------

def test_evicts_low_weight_before_old_high_weight():
    """高重要度的老条目，应比低重要度的新条目更晚被淘汰"""
    facts = [
        _f('old_high', '考研目标 数学二 复习计划', imp=5, days_ago=200),
        _f('new_low', '随口一提的小事', imp=1, days_ago=1),
        _f('mid', '中等重要', imp=3, days_ago=50),
    ]
    evicted, _ = mfe.plan_eviction(facts, cap=2)
    ids = {f['id'] for f in evicted}
    assert 'new_low' in ids, '低权重新条目反而被留下了（退化成按时间淘汰）'
    assert 'old_high' not in ids, '高重要度的老条目被淘汰了'


def test_tie_breaks_by_time():
    """权重相同时，旧的先走"""
    facts = [
        _f('older', '同级', imp=3, days_ago=100),
        _f('newer', '同级', imp=3, days_ago=1),
    ]
    evicted, _ = mfe.plan_eviction(facts, cap=1)
    assert [f['id'] for f in evicted] == ['older']


def test_non_active_status_does_not_take_quota():
    """superseded / evicted 不占名额"""
    facts = [_f('a%d' % i, 'x%d' % i) for i in range(3)]
    facts += [_f('s%d' % i, 'y%d' % i, status='superseded') for i in range(10)]
    evicted, kept = mfe.plan_eviction(facts, cap=3)
    assert evicted == [], '被推翻的条目算了名额'
    assert kept == 3


def test_no_eviction_below_cap():
    facts = [_f('a%d' % i, 'x%d' % i) for i in range(3)]
    evicted, kept = mfe.plan_eviction(facts, cap=10)
    assert evicted == [] and kept == 3


# ---------- 4. 只改 status，不物理删除 ----------

def test_eviction_marks_status_not_removes():
    facts = [_f('a%d' % i, 'x%d' % i, imp=1, days_ago=200) for i in range(5)]
    n, kept = mfe.evict_facts(facts, cap=2)
    assert n == 3 and kept == 2
    assert len(facts) == 5, '物理删除了 —— 原件必须保留'
    evicted = [f for f in facts if f['status'] == 'evicted']
    assert len(evicted) == 3
    for f in evicted:
        assert f['evicted_at'], '缺 evicted_at'
        assert f['evicted_reason'] == 'overflow'


# ---------- 5. 台账 ----------

def test_ledger_written_before_marking(tmp_path):
    """先记账、再标记：台账里的 id 必须在库里已被标 evicted"""
    lp = str(tmp_path / mfe.LEDGER_NAME)
    facts = [_f('a%d' % i, '内容%d' % i, imp=1, days_ago=200) for i in range(5)]
    mfe.evict_facts(facts, cap=2, ledger_path=lp)
    rows = [json.loads(t) for t in io.open(lp, encoding='utf-8').read().splitlines() if t.strip()]
    assert rows, '没写台账'
    for r in rows:
        assert r['v'] == 2 and r['reason'] == 'overflow'
        for k in ('t', 'id', 'title', 'content_hash', 'kept'):
            assert k in r, '台账缺字段 %s' % k
        assert len(r['content_hash']) == 16
    ids_in_ledger = {r['id'] for r in rows}
    now_evicted = {f['id'] for f in facts if f['status'] == 'evicted'}
    assert ids_in_ledger == now_evicted, '台账与库里被淘汰的对不上'


def test_ledger_tolerates_missing_fields(tmp_path):
    """缺 importance / weight / access_count 不许崩"""
    lp = str(tmp_path / mfe.LEDGER_NAME)
    facts = [
        {'id': 'bare1', 'content': '只有内容', 'status': 'active'},
        {'id': 'bare2', 'content': '也是', 'status': 'active'},
        {'id': 'keep', 'content': '留', 'status': 'active', 'importance': 5},
    ]
    mfe.evict_facts(facts, cap=1, ledger_path=lp)
    rows = [json.loads(t) for t in io.open(lp, encoding='utf-8').read().splitlines() if t.strip()]
    assert len(rows) == 2
    assert all(r['weight'] is None for r in rows), '缺 weight 应写 null'


def test_ledger_write_failure_does_not_block_eviction(tmp_path, caplog):
    """台账写不进时淘汰照常，但必须落痕（不静默）

    ⚠ 第一版我用「不存在的深层目录」当失败路径，结果 append_ledger 里的
      makedirs 把它建出来了 ⇒ 根本没失败 ⇒ 测试红在「没落痕」，而落痕代码是对的。
      改用**拿目录冒充文件**：打开目录写必然 IsADirectoryError，是真实失败。
    """
    bad_dir = tmp_path / 'iam_a_directory'
    bad_dir.mkdir()
    bad = str(bad_dir)
    facts = [_f('a%d' % i, 'x%d' % i, imp=1, days_ago=200) for i in range(4)]
    with caplog.at_level('WARNING', logger='pet.fact_evict'):
        n, _ = mfe.evict_facts(facts, cap=1, ledger_path=bad)
    assert n == 3, '台账失败把淘汰也带崩了'
    assert any('台账写入失败' in r.getMessage() for r in caplog.records), '没落痕'


def test_no_ledger_when_no_eviction(tmp_path):
    lp = str(tmp_path / mfe.LEDGER_NAME)
    facts = [_f('a%d' % i, 'x%d' % i) for i in range(3)]
    n, _ = mfe.evict_facts(facts, cap=10, ledger_path=lp)
    assert n == 0
    assert not os.path.exists(lp), '没淘汰却建了台账'


# ---------- 6. bump ----------

def test_bump_accumulates():
    f = _f('a', 'x', imp=3)
    w0 = mfe.fact_base_weight(f)
    assert mfe.bump_fact(f) is True
    assert f['access_count'] == 1
    assert f['weight'] > w0
    assert f['last_access']
    mfe.bump_fact(f)
    assert f['access_count'] == 2
    assert f['weight'] > w0


def test_bump_capped():
    f = _f('a', 'x', imp=3, weight=1.0)
    for _ in range(20):
        mfe.bump_fact(f)
    assert f['weight'] <= mfe.WEIGHT_MAX


def test_bumped_fact_survives_eviction(tmp_path):
    """★ 被反复提及的记忆应该活下来（这是「权重参与淘汰」的意义）"""
    facts = [
        _f('often', '经常被提起的事', imp=1, days_ago=300),
        _f('never', '从没被提起的事', imp=1, days_ago=300),
        _f('filler', '占位', imp=5),
    ]
    # often 被命中 12 次 ⇒ 权重拉满
    for _ in range(12):
        mfe.bump_fact(facts[0])
    evicted, _ = mfe.plan_eviction(facts, cap=2)
    ids = {f['id'] for f in evicted}
    assert 'often' not in ids, '被反复提及的记忆还是被淘汰了'
    assert 'never' in ids, '没被提及的反而留下了'


# ---------- 7. 与 events 的一致性 ----------

def test_decay_reuses_events_formula():
    """两套衰减公式迟早对不上 —— 这里钉住「用的是同一个函数」"""
    f = _f('a', 'x', imp=5, days_ago=90)
    expect = mev.decayed_weight(1.0, mev.entry_age_days(f))
    assert mfe.fact_effective_weight(f) == pytest.approx(expect, rel=1e-6)

# ═══════════ 观测：capacity_status / active_before（2026-11-04）═══════════

def test_capacity_status_below_cap():
    """真实库规模远低于上限时，status 必须说清「还剩多少」"""
    facts = [_f('a%d' % i, 'x%d' % i) for i in range(21)]
    st = mfe.capacity_status(facts, cap=400)
    assert st['active'] == 21 and st['cap'] == 400
    assert st['free'] == 379 and st['need_evict'] is False
    assert 0.0 < st['ratio'] < 0.1, 'ratio 不对：%r' % st['ratio']


def test_capacity_status_counts_only_active():
    """superseded / evicted 不占名额，别把它们算进 ratio"""
    facts = [_f('a%d' % i, 'x%d' % i) for i in range(3)]
    facts += [_f('s%d' % i, 'y%d' % i, status='superseded') for i in range(7)]
    st = mfe.capacity_status(facts, cap=10)
    assert st['active'] == 3, '把非 active 算进去了：%r' % st


def test_capacity_status_over_cap():
    facts = [_f('a%d' % i, 'x%d' % i) for i in range(5)]
    st = mfe.capacity_status(facts, cap=3)
    assert st['need_evict'] is True and st['free'] == -2


def test_ledger_records_active_before(tmp_path):
    """台账必须记「淘汰前多大」—— 容量预算靠这个回答「多大开始需要淘汰」"""
    lp = str(tmp_path / mfe.LEDGER_NAME)
    facts = [_f('a%d' % i, 'x%d' % i, imp=1, days_ago=200) for i in range(8)]
    mfe.evict_facts(facts, cap=3, ledger_path=lp)
    rows = [json.loads(t) for t in io.open(lp, encoding='utf-8').read().splitlines() if t.strip()]
    assert rows and all(r['active_before'] == 8 for r in rows), \
        'active_before 不是淘汰前规模：%r' % [r.get('active_before') for r in rows]
    assert all(r['kept'] == 3 for r in rows)

# ═══════════ 记忆密度（结构化价值前提，2026-11-04）═══════════

def test_density_counts_distinct_entities():
    """同一件事 3 条 ⇒ 密度 3.0（这才是「可归并」的意思）"""
    fs = [_f("a1", "爱吃桃片"), _f("a2", "桃片要现切的"), _f("a3", "桃片吃很多年了")]
    for f in fs:
        f["topic"] = "零食偏好"
    d, n, e = mfe.memory_density(fs)
    assert (d, n, e) == (3.0, 3, 1), (d, n, e)


def test_density_prefers_object_as_key():
    """object 不同 ⇒ 不同实体（即便 topic 相同）"""
    fs = [_f("a1", "x"), _f("a2", "y")]
    fs[0].update(topic="编辑器", object="VS Code")
    fs[1].update(topic="编辑器", object="PyCharm")
    d, n, e = mfe.memory_density(fs)
    assert e == 2 and d == 1.0, (d, n, e)


def test_density_falls_back_to_topic_without_object():
    fs = [_f("a1", "x"), _f("a2", "y")]
    for f in fs:
        f["topic"] = "饮食偏好"
        f["object"] = ""
    d, n, e = mfe.memory_density(fs)
    assert e == 1 and d == 2.0, (d, n, e)


def test_unlabeled_facts_are_not_merged_into_one():
    """★ 无标签不许全落在一个空键上（否则密度被算成「条数」）

    2026-11-04 实测事故：真实库 21 条都没有 topic/object 字段，
    第一版把它们全归到空键 ⇒ density=21.0、structure_worth=True
    ⇒ 得出「21 条记忆属于同一件事，很值得聚合」的假结论。
    """
    fs = [_f("a%d" % i, "内容%d" % i) for i in range(21)]
    d, n, e = mfe.memory_density(fs)
    assert e == 21, "无标签条目被并在一起了：%d 个实体" % e
    assert d == 1.0, "密度应为 1.0（每条自成一件事），实际 %r" % d


def test_capacity_status_says_undecidable_without_labels():
    """标签不足时必须明说「不可判定」，不许给一个数"""
    fs = [_f("a%d" % i, "内容%d" % i) for i in range(10)]
    st = mfe.capacity_status(fs, cap=100)
    assert st["density"] is None, st
    assert st["structure_worth"] is None, st
    assert "不可判定" in st["density_note"], st


def test_capacity_status_decides_when_labeled():
    """21 条 / 18 组 ⇒ 密度 1.17 < 2.0 ⇒ 不值得结构化"""
    fs = []
    for g in range(18):
        n = 2 if g < 3 else 1
        for j in range(n):
            f = _f("g%d_%d" % (g, j), "x")
            f["topic"] = "主题%d" % g
            fs.append(f)
    st = mfe.capacity_status(fs, cap=100)
    assert st["labeled"] == 21, st
    assert st["entities"] == 18, st
    assert abs(st["density"] - 1.17) < 0.02, st
    assert st["structure_worth"] is False, st


def test_structure_worth_true_at_high_density():
    """密度 >= 2.0 时才说值得（合成库那种 5.9 一定为 True）"""
    fs = []
    for j in range(8):
        f = _f("a%d" % j, "x")
        f["topic"] = "一件事"
        fs.append(f)
    st = mfe.capacity_status(fs, cap=100)
    assert st["density"] == 8.0 and st["structure_worth"] is True, st

# ═══ bump 缺陷的回归锁（WX-178 §一，2026-11-04）═══
# 这五条锁住「bump 不许抹平 importance」。
# 缺陷原状：存量条目无 weight ⇒ bump 后一律 0.55+0.06=0.61，与 importance 无关，
# 导致 imp=5 从 1.00 掉到 0.61、一年后「命中过的」反而低于「没命中的」、
# 淘汰时先淘汰重要的。而旧测试用 imp=3（唯一 bump 后仍上升的档位）恰好漏过。


def _ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _dt(y=2026, m=11, d=4, h=18):
    import datetime
    return datetime.datetime(y, m, d, h, 0)


def test_bump_preserves_importance_spread():
    """bump 后 importance 的区分度必须还在 —— 这是「重要的事留下」的前提"""
    ws = []
    for imp in (5, 4, 3, 2, 1):
        f = _f("a", "x", imp=imp)
        mfe.bump_fact(f, _ts(_dt()))
        ws.append(f["weight"])
    assert ws == sorted(ws, reverse=True), ws          # 严格递减
    assert ws[0] > ws[-1], "重要性差异被抹平：%r" % ws


def test_bump_never_lowers_base_for_high_importance():
    """imp=5/4 被命中一次后 base 不许下降（缺陷原状是降 39% / 19%）"""
    for imp in (5, 4):
        f = _f("a", "x", imp=imp)
        before = mfe.fact_base_weight(f)
        mfe.bump_fact(f, _ts(_dt()))
        after = mfe.fact_base_weight(f)
        assert after >= before - 1e-9, (
            "imp=%d 被 bump 后 base 反而下降：%r -> %r" % (imp, before, after))


def test_bumped_never_below_unbumped_long_term():
    """一年后：命中过的条目权重必须 >= 从没命中的同 importance 条目"""
    year = _dt(2027, 11, 4)
    for imp in (5, 4, 3):
        a = _f("a", "x", imp=imp, days_ago=93)
        mfe.bump_fact(a, _ts(_dt()))
        b = _f("b", "x", imp=imp, days_ago=93)
        ea = mfe.fact_effective_weight(a, year)
        eb = mfe.fact_effective_weight(b, year)
        assert ea >= eb - 1e-9, (
            "imp=%d 命中过反而更低：%.4f < %.4f" % (imp, ea, eb))


def test_eviction_prefers_low_importance_over_old_high_importance():
    """两条都被命中过时，淘汰低重要的那条（缺陷原状会淘汰 imp=5）"""
    A = _f("A", "重要且更旧", imp=5, days_ago=300)
    B = _f("B", "低重要且较新", imp=1, days_ago=60)
    for f in (A, B):
        mfe.bump_fact(f, _ts(_dt()))
    year = _dt(2027, 11, 4)
    ev, _kept = mfe.plan_eviction([A, B], cap=1, now=year)
    assert [f["id"] for f in ev] == ["B"], (
        "淘汰了重要的那条：%r（A 有效 %.4f / B 有效 %.4f）"
        % ([f["id"] for f in ev],
           mfe.fact_effective_weight(A, year),
           mfe.fact_effective_weight(B, year)))


def test_bump_accumulates_beyond_first_time():
    """修好 base 之后，多次命中仍要能持续累加（别改坏「权重可变」）"""
    f = _f("a", "x", imp=1)
    ws = []
    for _ in range(4):
        mfe.bump_fact(f, _ts(_dt()))
        ws.append(f["weight"])
    assert ws == sorted(ws), ws
    assert ws[-1] > ws[0] + 0.1, ws

# ═══ 加权写盘节流（2026-11-04）═══
# 背景：命中即加权让「记忆真变化才写盘」变成「每轮都写盘」
# （实测 44 条 0.86ms / 400 条 2.90ms）。节流：攒够 5 次或过 300 秒才落，退出时强制 flush。


class _ThrottleFake(object):
    """最小可测夹具：只提供 _maybe_flush_bumps 依赖的三个属性"""
    from desktop_pet import PetWidget as _PW
    _BUMP_FLUSH_N = _PW._BUMP_FLUSH_N
    _BUMP_FLUSH_SEC = _PW._BUMP_FLUSH_SEC
    _maybe_flush_bumps = _PW._maybe_flush_bumps
    _enforce_memory_cap = lambda self: 0

    def __init__(self, pending=0):
        import time as _t
        self._bump_pending = pending
        # 与产品一致：初始化为「现在」，否则距上次恒 >300 秒 ⇒ 首次立刻落盘
        self._bump_last_save = _t.time()
        self.saves = 0

    def _save_memory(self):
        self.saves += 1


def test_throttle_constants_present():
    """节流参数必须存在且合理（防被悄悄删掉退回每轮写盘）"""
    from desktop_pet import PetWidget as PW
    assert PW._BUMP_FLUSH_N >= 2, PW._BUMP_FLUSH_N
    assert PW._BUMP_FLUSH_SEC >= 60, PW._BUMP_FLUSH_SEC


def test_flush_is_throttled_by_count():
    """只 bump 1~4 次不该写盘；第 5 次才写"""
    f = _ThrottleFake()
    n = f._BUMP_FLUSH_N
    for i in range(1, n):
        f._bump_pending = i
        assert f._maybe_flush_bumps() is False, "第 %d 次就写盘了" % i
    assert f.saves == 0, f.saves
    f._bump_pending = n
    assert f._maybe_flush_bumps() is True
    assert f.saves == 1
    assert f._bump_pending == 0, "落盘后计数没清零"


def test_flush_force_ignores_threshold():
    """退出时 force=True：哪怕只攒了 1 次也要落盘（否则丢加权）"""
    f = _ThrottleFake(pending=1)
    assert f._maybe_flush_bumps(force=True) is True
    assert f.saves == 1


def test_flush_is_noop_when_nothing_pending():
    """没有待落盘时不许白写一次盘"""
    f = _ThrottleFake()
    assert f._maybe_flush_bumps() is False
    assert f._maybe_flush_bumps(force=True) is False
    assert f.saves == 0


def test_injection_point_uses_throttle_not_direct_save():
    """结构钉：注入点不许再直接 _save_memory，必须走节流"""
    import os as _os
    root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    with io.open(_os.path.join(root, "desktop_pet.py"), encoding="utf-8") as fh:
        src = fh.read()
    i = src.find("_bump_fact_hits(rel)")
    assert i > 0, "找不到注入点"
    seg = src[i:i + 300]
    assert "_maybe_flush_bumps" in seg, "注入点没走节流"
    head = [l.strip() for l in seg.splitlines()[:6]]
    assert "self._save_memory()" not in head, \
        "注入点仍在直接 _save_memory：%r" % head


def test_quit_app_flushes_forced():
    """退出路径必须强制 flush（否则最近几次加权丢失）"""
    import os as _os
    root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    with io.open(_os.path.join(root, "desktop_pet.py"), encoding="utf-8") as fh:
        src = fh.read()
    i = src.find("def quit_app(self):")
    assert i > 0, "找不到 quit_app"
    seg = src[i:i + 400]
    assert "_maybe_flush_bumps(force=True)" in seg, \
        "退出时没强制落盘：%r" % seg[:200]

# ═══ 台账不许进仓库（隐私，2026-11-04）═══
# 背景：淘汰台账含**用户真实记忆标题**，一旦被 git 跟踪就是隐私泄露。
# memory_evicted.jsonl（events 层）从 2026-11-02 就漏了，
# 只因 events 从未触发淘汰（6 条 / 上限 200）才没暴露。


def test_ledger_paths_are_gitignored():
    """两种淘汰台账都必须被 .gitignore 覆盖"""
    import os as _os
    root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    with io.open(_os.path.join(root, ".gitignore"), encoding="utf-8") as fh:
        gi = fh.read()
    for name in (mfe.LEDGER_NAME, "memory_evicted.jsonl"):
        assert name in gi, (
            "台账 %s 未被 .gitignore 覆盖 —— 会被误提交，含用户真实记忆标题"
            % name)
    # 轮转后的 .1 也要挡
    assert "memory_evicted_facts.jsonl.*" in gi
    assert "memory_evicted.jsonl.*" in gi


def test_git_check_ignore_confirms(tmp_path):
    """不止看文本，实际问一次 git（防规则写对了但位置在别的 pattern 之后被覆盖）"""
    import subprocess as _sp
    import os as _os
    root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    git = r"D:\Git\cmd\git.exe"
    if not _os.path.exists(git):
        import pytest as _pytest
        _pytest.skip("本机无 git")
    for name in (mfe.LEDGER_NAME, "memory_evicted.jsonl"):
        r = _sp.run([git, "-c", "safe.directory=D:/ai工作站/desktop-pet",
                    "-C", root, "check-ignore", name],
                   capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, (
            "git 认为 %s 未被忽略（check-ignore rc=%d）：%s"
            % (name, r.returncode, (r.stdout + r.stderr)[:120]))


# ═══ 失效代价维度（2026-11-05，源自桌宠的观察）═══
# 桌宠在 chat_memory_flash 里指出：「低频但关键」与「高频但无害」同池竞争，
# 前者失效代价是后者的一百倍，却因命中次数低而被先淘汰。
# 实测坐实：过敏(imp=5, 0 命中) 有效 0.180 vs 周杰伦(20 命中) 1.000 ⇒ 淘汰过敏。


def test_critical_entries_are_protected():
    """丢了有实际后果的条目必须受保护，与 importance / 命中次数无关"""
    cases = [
        '对花生过敏，吃了会呼吸困难',
        '对青霉素过敏',
        '正在服用降压药，不能吃葡萄柚',
        '身份证号后四位 8823',
        '银行卡密码是 ****',
        '紧急联系人是我妈 138xxxxxxxx',
    ]
    for text in cases:
        f = _f('a', text, imp=1)
        assert mfe.protected(f), '未受保护：%s' % text


def test_critical_beats_frequent_competitor():
    """★ 核心回归：过敏 vs 20 次命中的高频条目，必须淘汰高频那条"""
    import datetime
    now = datetime.datetime(2026, 11, 5, 1, 0)
    allergy = _f('A', '对花生过敏，吃了会呼吸困难', imp=3, days_ago=300)
    frequent = _f('F', '用户喜欢听周杰伦', imp=3, days_ago=300)
    for _ in range(20):
        mfe.bump_fact(frequent, now.strftime('%Y-%m-%dT%H:%M:%S'))
    assert mfe.fact_effective_weight(allergy, now) < mfe.fact_effective_weight(
        frequent, now), '前提变了：过敏的有效权重竟高于高频条目'
    ev, _ = mfe.plan_eviction([allergy, frequent], cap=1, now=now)
    assert [f['id'] for f in ev] == ['F'], '淘汰了关键条目：%r' % [f['id'] for f in ev]


def test_normal_entries_still_evictable():
    """别把保护做过头 —— 普通条目仍要能被淘汰（否则库无限长）"""
    for text in ('用户喜欢听周杰伦', '今天想吃火锅', '最近在学 matplotlib'):
        f = _f('a', text, imp=3)
        assert not mfe.protected(f), '普通条目被误保护：%s' % text


def test_critical_not_affected_by_importance():
    """保护与 importance 无关（imp=1 的过敏也要保护）"""
    for imp in (1, 2, 3, 4, 5):
        f = _f('a', '对花生过敏', imp=imp)
        assert mfe.protected(f), 'imp=%d 时未保护' % imp


def test_critical_wordlist_is_deliberately_narrow():
    """词表刻意取窄：不含泛泛的「重要」类词，防止保护膨胀"""
    for word in ('重要', '目标', '喜欢', '习惯'):
        assert word not in mfe._CRITICAL_PATTERNS, \
            '词表里混进了泛词 %r，会让保护范围失控' % word


def test_critical_known_gap_is_documented():
    """已知缺口（写明，不装作覆盖全）

    「考研目标是西南大学」这类长期目标，失效代价也高，但词表没覆盖。
    这是刻意的：词表取窄，宁漏不滥。扩表前要 Owner 确认。
    """
    f = _f('a', '考研目标院校是西南大学 070503', imp=5)
    assert not mfe.protected(f), \
        '若这条被保护了，说明词表扩过头（需同步更新本测试与注释）'

