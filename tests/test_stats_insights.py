# -*- coding: utf-8 -*-
"""效率与省钱三项（v3.5）：缓存 / 峰谷 / 时段

为什么加这三项 —— 我是先用真数据算出价值才加的，不是凑数：
    缓存价 0.02 vs 正常 input 1.0（元/百万）⇒ 相差 50 倍
    峰谷价差**正好 2 倍** ⇒ 高峰花费的一半是溢价
    实测本机：高峰占 47% 花费（错峰可省 ¥0.17）、缓存命中率 45.8%

锁四类行为：
1. 缓存命中率按 **by_day 所选范围**累加（与表格同源）
2. 峰谷/时段只能基于 **calls 样本**，且**必须明说"仅最近 N 条"**（不许假装全域）
3. 空数据时明说没数据，不编 0 也不崩
4. 三项互不拖累：一项失败不连累另两项（各自 try）

运行：python -m pytest tests/test_stats_insights.py -q
"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import api_stats as _as  # noqa: E402
import stats_ui  # noqa: E402


class _Host(object):
    def __init__(self, st, current='flash'):
        self.theme = {}
        self.api_stats = st
        self.current = current


def _mk(tmp_path, days=None, calls=None):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(sys.argv)
    st = _as.ApiStats(str(tmp_path / 's.json'))
    if days is not None:
        st.by_day = days
        st.day_legacy = not bool(days)
    if calls is not None:
        st.calls = calls
    return stats_ui.UsageStatsDialog(_Host(st))


def _day(cost=0.01, count=1, hit=0, miss=0):
    return {'count': count, 'prompt': hit + miss, 'completion': 10,
            'total': hit + miss + 10, 'cost': cost,
            'cache_hit': hit, 'cache_miss': miss,
            'by_purpose': {'chat': {'count': count, 'cost': cost}}}


def _call(hh, cost=0.01, hit=0, miss=100):
    return {'time': '2026-10-24 %02d:15:00' % hh, 'model': 'deepseek-flash',
            'prompt': hit + miss, 'completion': 10, 'total': hit + miss + 10,
            'cost': cost, 'cache_hit': hit, 'cache_miss': miss}


# ---------- 1. 缓存 ----------

def test_cache_rate_from_by_day(tmp_path):
    """命中率按 by_day 累加（与表格同源）"""
    d = _mk(tmp_path, {'2026-10-23': _day(0.01, 1, hit=600, miss=400),
                       '2026-10-24': _day(0.02, 2, hit=400, miss=600)})
    try:
        txt = d.lb_cache.text()
        assert '命中率 50.0%' in txt, '两天合计 1000/2000 应 50%%，实际：%r' % txt
        assert '¥' in txt, '应给出省下金额'
    finally:
        d.close()


def test_cache_empty_says_so(tmp_path):
    """没有缓存数据时明说，不编 0%"""
    d = _mk(tmp_path, {'2026-10-24': _day(0.01, 1, hit=0, miss=0)})
    try:
        txt = d.lb_cache.text()
        assert '无缓存数据' in txt, '应明说无数据：%r' % txt
        assert '命中率 0' not in txt, '不该把无数据说成 0% 命中率'
    finally:
        d.close()


# ---------- 2. 峰谷 ----------

def test_peak_splits_by_hours(tmp_path):
    """9-12 / 14-18 算高峰（与 server_clock.PEAK_HOURS 一致）"""
    calls = [_call(10), _call(11), _call(15),   # 高峰
             _call(20), _call(23)]               # 空闲
    d = _mk(tmp_path, {'2026-10-24': _day()}, calls)
    try:
        txt = d.lb_peak.text()
        assert '高峰 3 次' in txt, '高峰应 3 次（10/11/15 点），实际：%r' % txt
        assert '空闲 2 次' in txt, '空闲应 2 次，实际：%r' % txt
    finally:
        d.close()


def test_peak_must_say_sample_not_global(tmp_path):
    """必须明说「仅统计最近 N 条」—— 不许把 200 条样本说成全域数据"""
    d = _mk(tmp_path, {'2026-10-24': _day()}, [_call(10), _call(20)])
    try:
        txt = d.lb_peak.text()
        assert '仅统计最近 2 条' in txt, '必须标样本口径，否则会被当全域：%r' % txt
    finally:
        d.close()


def test_peak_saving_is_half_of_peak_cost(tmp_path):
    """峰谷 2 倍 ⇒ 错峰潜在节省 = 高峰花费的一半"""
    calls = [_call(10, cost=0.10), _call(20, cost=0.10)]
    d = _mk(tmp_path, {'2026-10-24': _day()}, calls)
    try:
        txt = d.lb_peak.text()
        assert '0.0500' in txt, '高峰 ¥0.10 的溢价一半应约 ¥0.05，实际：%r' % txt
    finally:
        d.close()


# ---------- 3. 时段 ----------

def test_hour_top3_by_cost(tmp_path):
    """时段按花费排前 3，并标出各自花费"""
    calls = [_call(18, 0.05), _call(18, 0.05), _call(14, 0.02), _call(9, 0.01)]
    d = _mk(tmp_path, {'2026-10-24': _day()}, calls)
    try:
        txt = d.lb_hour.text()
        assert '18 点 2 次' in txt, '18 点应 2 次，实际：%r' % txt
        assert '0.1000' in txt, '18 点合计应 ¥0.10'
    finally:
        d.close()


# ---------- 4. 空数据不崩 ----------

def test_no_calls_no_crash(tmp_path):
    d = _mk(tmp_path, {}, [])
    try:
        assert '暂无' in d.lb_peak.text(), '无明细应说暂无：%r' % d.lb_peak.text()
        assert '暂无' in d.lb_hour.text()
    finally:
        d.close()


def test_legacy_still_no_crash(tmp_path):
    """旧档（无 by_day 无 calls）整窗仍要能开"""
    d = _mk(tmp_path, {}, [])
    try:
        for lb in (d.lb_cache, d.lb_peak, d.lb_hour):
            assert '读取失败' not in lb.text(), '不该报读取失败：%r' % lb.text()
    finally:
        d.close()


# ---------- 5. 接口漏字段的回归（v3.5 实测发现的真缺陷）----------

def test_day_breakdown_exposes_cache_fields(tmp_path):
    """day_breakdown 必须暴露 cache_hit / cache_miss / total

    实测缺陷：by_day 文件里明明存着 cache_hit=21632，但 day_breakdown 只返回
    date/cost/count/prompt/completion/by_purpose ⇒ 界面算缓存永远得 0，
    显示「无缓存数据」，而数据就在文件里。属接口漏字段。
    """
    path = str(tmp_path / 's.json')
    st = _as.ApiStats(path)
    st.record({'prompt_tokens': 1000, 'completion_tokens': 50,
               'prompt_cache_hit_tokens': 600, 'prompt_cache_miss_tokens': 400},
              'deepseek-flash', purpose='chat')
    rows = st.day_breakdown()
    assert rows, 'day_breakdown 应有一天'
    for key in ('cache_hit', 'cache_miss', 'total'):
        assert key in rows[0], 'day_breakdown 漏了 %s 字段（界面因此算不出缓存）' % key
    assert rows[0]['cache_hit'] == 600
    assert rows[0]['cache_miss'] == 400

def test_cache_line_states_range_days(tmp_path):
    """缓存行必须标出「按所选范围 N 天」

    为什么锁这条：缓存在 by_day（按天），峰谷在 calls（最近 200 条），
    两者**范围不同**。不标的话用户会拿「省下 ¥0.02」和「错峰省 ¥0.17」直接比，
    误以为口径一致 —— 那是最容易被误读的一类数。
    """
    d = _mk(tmp_path, {'2026-10-23': _day(0.01, 1, hit=500, miss=500),
                       '2026-10-24': _day(0.02, 2, hit=500, miss=500)})
    try:
        txt = d.lb_cache.text()
        assert '按所选范围 2 天' in txt, '缓存行应标范围天数，实际：%r' % txt
    finally:
        d.close()

def test_model_line_states_lifetime_scope(tmp_path):
    """模型行必须标「终身口径」—— model_breakdown 不随范围变化

    为什么锁：用户选了「近 7 天」，模型行却还是终身累计数。
    不标的话会以为这行也是 7 天的 —— 又是最容易被误读的那类数。
    """
    d = _mk(tmp_path, {'2026-10-24': _day(0.01, 1, hit=10, miss=10)})
    try:
        d.host.api_stats.by_model = {'deepseek-flash': {'count': 99, 'cost': 1.23,
                                                        'prompt': 100, 'completion': 10}}
        d.reload()
        txt = d.lb_model.text()
        assert '终身' in txt, '模型行应标终身口径，实际：%r' % txt
    finally:
        d.close()
