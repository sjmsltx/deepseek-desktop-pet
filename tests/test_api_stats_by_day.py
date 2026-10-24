# -*- coding: utf-8 -*-
"""按天存档 by_day（v3.2，2026-10-24 Owner 需求 3）

为什么要有它（已核实的事实）：
    api_stats.json 原来只有 today + total + 最近 200 条 calls，
    实测 200 条只覆盖 10 天，9-27~10-01 已经丢了。
    ⇒ 「按时间统计」无从做起，且晚一天少一天、过去补不回。

锁四类行为：
1. 记账后 by_day[今天] 与 today **同口径**（不另立第二套计价）
2. 落盘后重开仍在（不是只在内存里）
3. 跨天先结算旧 today 再重置（旧实现直接丢）
4. 旧档无 by_day → 返回 [] + day_legacy，不炸不编
5. KEEP_DAYS 裁剪只保留最近 N 天

运行：python -m pytest tests/test_api_stats_by_day.py -q
"""
import datetime
import json
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import api_stats as _as  # noqa: E402

TODAY = datetime.date.today().isoformat()
YESTERDAY = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()


def _usage(p=100, c=10):
    return {'prompt_tokens': p, 'completion_tokens': c}


def _stats(tmp_path, name='s.json'):
    return _as.ApiStats(str(tmp_path / name))


# ---------- 1. 同口径 ----------

def test_by_day_matches_today(tmp_path):
    """by_day[今天] 必须与 today 完全同口径（cost / count / token）"""
    st = _stats(tmp_path)
    st.record(_usage(), 'deepseek-flash', purpose='chat')
    st.record(_usage(200, 20), 'deepseek-flash', purpose='care')

    d = st.by_day.get(TODAY)
    assert d, '记账后 by_day 里没有今天'
    assert abs(float(d['cost']) - float(st.today['cost'])) < 1e-9, '费用与 today 不一致'
    assert int(d['count']) == int(st.today['count']), '次数与 today 不一致'
    assert int(d['total']) == int(st.today['total']), 'token 与 today 不一致'


def test_by_day_mirrors_purpose(tmp_path):
    """用途分项也要镜像（否则按天看不了"花到哪个模块"）"""
    st = _stats(tmp_path)
    st.record(_usage(), 'deepseek-flash', purpose='chat')
    st.record(_usage(), 'deepseek-flash', purpose='tools')
    bp = (st.by_day.get(TODAY) or {}).get('by_purpose') or {}
    assert set(bp.keys()) == {'chat', 'tools'}, '用途分项没镜像过去：%s' % bp
    assert int(bp['chat']['count']) == 1


def test_by_day_is_a_copy_not_a_reference(tmp_path):
    """必须是拷贝：跨天 today 被整体替换时，历史条目不能跟着变"""
    st = _stats(tmp_path)
    st.record(_usage(), 'deepseek-flash')
    snapshot = st.by_day[TODAY]
    assert snapshot is not st.today, 'by_day 存的是 today 的引用（跨天会变味）'
    assert snapshot.get('by_purpose') is not st.today.get('by_purpose'), \
        'by_purpose 没深拷贝（二层 dict 共享引用）'


# ---------- 2. 落盘 ----------

def test_by_day_persisted(tmp_path):
    """重开文件后 by_day 仍在（真的写了盘，不是只在内存）"""
    st = _stats(tmp_path)
    st.record(_usage(), 'deepseek-flash')
    raw = json.load(open(str(tmp_path / 's.json'), encoding='utf-8'))
    assert isinstance(raw.get('by_day'), dict) and TODAY in raw['by_day'], \
        '落盘文件里没有 by_day'

    st2 = _stats(tmp_path)
    assert TODAY in st2.by_day, '重开后 by_day 丢了'
    assert st2.day_breakdown(), 'day_breakdown 返回空'


# ---------- 3. 跨天结算 ----------

def test_cross_day_flushes_old_today(tmp_path):
    """跨天：旧 today 必须先结算进 by_day 再重置（旧实现直接丢）"""
    legacy = {'date': YESTERDAY,
              'today': {'count': 3, 'prompt': 300, 'completion': 30, 'total': 330,
                        'cost': 0.05, 'cache_hit': 0, 'cache_miss': 300, 'date': YESTERDAY},
              'total': {'count': 3, 'prompt': 300, 'completion': 30, 'total': 330,
                        'cost': 0.05, 'cache_hit': 0, 'cache_miss': 300},
              'calls': []}
    json.dump(legacy, open(str(tmp_path / 's.json'), 'w', encoding='utf-8'), ensure_ascii=False)

    st = _stats(tmp_path)
    assert YESTERDAY in st.by_day, '跨天没把昨天的数据结算进 by_day（会永久丢失）'
    assert abs(float(st.by_day[YESTERDAY]['cost']) - 0.05) < 1e-9
    assert int(st.today.get('count') or 0) == 0, '今天应归零'


def test_record_crosses_midnight_without_losing(tmp_path):
    """运行中跨天：record 里也要先结算再重置"""
    st = _stats(tmp_path)
    # 手动把 today 伪造成"昨天有 2 次"
    st.today = {'count': 2, 'prompt': 200, 'completion': 20, 'total': 220,
                'cost': 0.02, 'cache_hit': 0, 'cache_miss': 200,
                'date': YESTERDAY, 'unknown': 0, 'by_purpose': {}}
    st.record(_usage(), 'deepseek-flash')
    assert YESTERDAY in st.by_day, '运行中跨天没结算旧 today'
    assert abs(float(st.by_day[YESTERDAY]['cost']) - 0.02) < 1e-9
    assert TODAY in st.by_day


# ---------- 4. 旧档兼容 ----------

def test_legacy_file_no_crash(tmp_path):
    """旧档无 by_day → 返回 [] + day_legacy，且 today 照旧可读（不丢账）"""
    json.dump({'date': TODAY,
               'today': _full_agg(TODAY, count=1, cost=0.01),
               'total': _full_agg('', count=1, cost=0.01), 'calls': []},
              open(str(tmp_path / 's.json'), 'w', encoding='utf-8'), ensure_ascii=False)

    st = _stats(tmp_path)
    assert st.day_breakdown() == [], '旧档应返回空列表（不编数字）'
    assert st.day_legacy is True, '旧档应标 day_legacy'
    assert abs(float(st.today['cost']) - 0.01) < 1e-9, 'today 必须仍可读（不丢账）'


def _full_agg(date, **over):
    """真实写入器产出的字段集（实测 api_stats.json 的 today 键：9 个）

    ⚠ 不能图省事只写 count/cost：record() 会做 `agg['prompt'] += prompt`，
      缺键会 KeyError。夹具必须用真实字段集，否则红的不是产品是夹具。
    """
    agg = {'count': 0, 'prompt': 0, 'completion': 0, 'total': 0, 'cost': 0.0,
           'cache_hit': 0, 'cache_miss': 0, 'date': date}
    agg.update(over)
    return agg


def test_legacy_flag_clears_after_first_record(tmp_path):
    """记一笔之后 day_legacy 应转 False（已有按天数据了）"""
    json.dump({'date': TODAY, 'today': _full_agg(TODAY),
               'total': _full_agg(''), 'calls': []},
              open(str(tmp_path / 's.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    st = _stats(tmp_path)
    st.record(_usage(), 'deepseek-flash')
    st.day_breakdown()
    assert st.day_legacy is False


# ---------- 5. 裁剪 ----------

def test_prune_keeps_recent_days(tmp_path):
    """超过 KEEP_DAYS → 只留最近那批，且今天一定在"""
    st = _stats(tmp_path)
    base = datetime.date.today()
    st.by_day = {(base - datetime.timedelta(days=i)).isoformat():
                 {'count': 1, 'cost': 0.001, 'prompt': 1, 'completion': 1, 'by_purpose': {}}
                 for i in range(130)}
    st._prune_by_day()
    assert len(st.by_day) == st.KEEP_DAYS, '裁剪后应正好 %d 天，实际 %d' % (st.KEEP_DAYS, len(st.by_day))
    assert TODAY in st.by_day, '今天被裁掉了'
    assert (base - datetime.timedelta(days=129)).isoformat() not in st.by_day, '最旧的一天没被裁掉'


def test_prune_noop_under_limit(tmp_path):
    """没超上限时裁剪不该动数据"""
    st = _stats(tmp_path)
    st.by_day = {TODAY: {'count': 1, 'cost': 0.001}}
    st._prune_by_day()
    assert len(st.by_day) == 1


# ---------- 6. day_breakdown 排序与截断 ----------

def test_day_breakdown_sorted_desc_and_limit(tmp_path):
    st = _stats(tmp_path)
    st.by_day = {'2026-10-20': {'cost': 0.01, 'count': 1},
                 '2026-10-22': {'cost': 0.02, 'count': 2},
                 '2026-10-21': {'cost': 0.03, 'count': 3}}
    rows = st.day_breakdown()
    assert [r['date'] for r in rows] == ['2026-10-22', '2026-10-21', '2026-10-20'], \
        '应按日期降序'
    assert len(st.day_breakdown(limit=2)) == 2, 'limit 未生效'
    assert len(st.by_day) == 3, 'limit 不该删数据'


# ---------- 7. 源码护栏：today/total 语义不许被改 ----------

def test_source_guard_does_not_change_today_semantics():
    """ratchet：by_day 只能是"镜像"，不许成为第二套计价来源"""
    src = open(os.path.join(BASE, 'api_stats.py'), encoding='utf-8').read()
    assert "_copy_agg(self.today)" in src, 'by_day 应镜像 today（同口径）'
    # 闸门读的仍是 today.cost —— 这句不能被改成 by_day
    gov = open(os.path.join(BASE, 'governance.py'), encoding='utf-8').read()
    assert "today" in gov, 'governance 读今天花费的方式被动了，请确认闸门口径未变'
    assert "'cost'" in gov
