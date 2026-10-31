# -*- coding: utf-8 -*-
"""权重体系：weight / access_count / last_access / pinned

Owner 原话（2026-10-31）：「记忆衰减随着时间增长会逐渐忘记一些细节但是重要的东西会记下来，
相当于说是权重引入并且权重本身还会变化」+「被反复提及/被用户强调的记忆权重上升」。

现状（实测）：两个库 200 + 43 条，weight / access_count / pinned / layer **全部 0 条**。
⇒ 现在只有「读时算」的亮度公式，不能累积、不能回写、无法解释「为什么忘了这条」。

本文件锁四件事：
1. 字段真的落盘（写入即带 weight / access_count / last_access / pinned）
2. 被检索命中 → access_count +1、last_access 更新、weight 上升（这是「权重可变」）
3. 时间衰减：weight 随时间下降（半衰期 30 天，与 score_recency 同口径）
4. pinned 不衰减、不被淘汰（核心事实不能因久不提及而消失）
"""
import json
import os
import sys

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import memory_events as me  # noqa: E402


@pytest.fixture()
def ev(tmp_path):
    return me.MemoryEvents(str(tmp_path / 'memories.json'))


# ---------- 1. 字段落盘 ----------
def test_new_entry_has_weight_fields(ev):
    ev.add('flash', 'event', '一起看了流星雨', '很冷但值得')
    it = ev.all('flash')[0]
    for k in ('weight', 'access_count', 'last_access', 'pinned'):
        assert k in it, '缺字段 %s：%r' % (k, sorted(it))
    assert it['access_count'] == 0
    assert it['pinned'] is False
    assert 0.0 < it['weight'] <= 1.0


def test_weight_fields_survive_reload(tmp_path):
    p = str(tmp_path / 'm.json')
    e1 = me.MemoryEvents(p)
    e1.add('flash', 'event', '一起看了流星雨', '')
    w = e1.all('flash')[0]['weight']
    e2 = me.MemoryEvents(p)
    assert e2.all('flash')[0]['weight'] == w, '重新加载后 weight 丢了'


# ---------- 2. 权重可变：被检索中即加权 ----------
def test_search_bumps_access_count_and_weight(ev):
    ev.add('flash', 'event', '一起玩了扫雷，他连赢三局', '')
    # 取快照值：all() 返回的元素与内部是同一个 dict，直接留着引用会被一起改
    it = ev.all('flash')[0]
    before_count = it['access_count']
    before_weight = it['weight']
    hits = ev.search('扫雷')
    assert hits, '检索没命中，无法测加权'
    it2 = ev.all('flash')[0]
    assert it2['access_count'] == before_count + 1, (
        '命中未计次：%r -> %r' % (before_count, it2['access_count']))
    assert it2['last_access'], 'last_access 未更新'
    assert it2['weight'] > before_weight, '被命中后权重没上升'


def test_repeated_access_raises_weight_monotonically(ev):
    ev.add('flash', 'event', '一起玩了扫雷，他连赢三局', '')
    ws = []
    for _ in range(4):
        ev.search('扫雷')
        ws.append(ev.all('flash')[0]['weight'])
    assert ws == sorted(ws), '权重不单调：%r' % (ws,)
    assert ws[-1] > ws[0], '多次命中后权重没涨'


def test_weight_capped_at_one(ev):
    ev.add('flash', 'event', '一起玩了扫雷', '')
    for _ in range(60):
        ev.search('扫雷')
    assert ev.all('flash')[0]['weight'] <= 1.0, '权重超过上限'


# ---------- 3. 时间衰减 ----------
def test_decay_lowers_weight_with_age():
    """同内容、不同年龄 → 越旧权重越低（读时衰减，不改盘上原值）"""
    fresh = {'decay': 0.0}
    old = {'decay': 90.0}
    assert me.decayed_weight(1.0, 0.0) > me.decayed_weight(1.0, 90.0)
    assert abs(me.decayed_weight(1.0, 0.0) - 1.0) < 0.01
    assert me.decayed_weight(1.0, 30.0) < 0.55, '半衰期不是 30 天'


def test_decay_never_negative():
    assert me.decayed_weight(1.0, 100000.0) >= 0.0


# ---------- 4. pinned 不衰减、不被淘汰 ----------
def test_pin_marks_entry(ev):
    ev.add('flash', 'event', '用户的名字叫小蓝', '')
    it = ev.all('flash')[0]
    assert ev.pin(it['id']) is True, 'pin 失败'
    assert ev.all('flash')[0]['pinned'] is True


def test_pinned_survives_eviction(tmp_path):
    """超上限淘汰时，pinned 必须留下（核心事实不能因条数满被挤掉）"""
    p = str(tmp_path / 'm.json')
    e = me.MemoryEvents(p)
    old_cap = me.MAX_MEMORIES
    me.MAX_MEMORIES = 5
    try:
        e.add('flash', 'event', '用户的名字叫小蓝', '')
        e.pin(e.all('flash')[0]['id'])
        for i in range(10):
            e.add('flash', 'event', '噪声事件 %d' % i, '')
        titles = [m['title'] for m in e.all('flash')]
        assert '用户的名字叫小蓝' in titles, 'pinned 条目被淘汰了：%r' % (titles,)
        assert len(titles) <= 5, '总量未受上限约束：%d' % len(titles)
    finally:
        me.MAX_MEMORIES = old_cap


def test_unpin_restores_normal_decay(ev):
    ev.add('flash', 'event', '一起看了流星雨', '')
    fid = ev.all('flash')[0]['id']
    ev.pin(fid)
    assert ev.unpin(fid) is True
    assert ev.all('flash')[0]['pinned'] is False


# ---------- 5. 旧条目兼容 ----------
def test_legacy_entry_without_fields_still_readable(tmp_path):
    """存量 200 条没有这些字段，不能因此报错"""
    p = str(tmp_path / 'm.json')
    legacy = [{'id': 111, 'time': '2026-10-30 10:00', 'role': 'flash', 'type': 'event',
               'title': '旧条目', 'detail': ''}]
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(legacy, f, ensure_ascii=False)
    e = me.MemoryEvents(p)
    it = e.all('flash')[0]
    assert it['title'] == '旧条目'
    # 缺字段时给默认值，不回写（不回写是为了不擅自改用户数据）
    assert it.get('weight') is None or isinstance(it.get('weight'), float)


def test_effective_weight_handles_legacy():
    """旧条目没有 weight → 计算有效权重时按 1.0 起算，不能崩"""
    legacy = {'title': 'x', 'detail': '', 'time': '2026-10-30 10:00'}
    v = me.effective_weight(legacy)
    assert 0.0 <= v <= 1.0


# ---------- 分流报告暴露的两个设计缺陷（2026-10-31）----------
def test_identity_entry_never_decays():
    """身份事实不能被时间衰减压低。

    实测背景：「我的名字叫小蓝」created_at == updated_at（从没更新过），
    年龄 89.8 天 => 权重 0.069，和「爱吃桃片」一样低，但它每轮都必须在。
    """
    ident = {'title': '我的名字叫小蓝', 'time': '2026-08-02 13:21', 'weight': 0.55,
             'pinned': False}
    normal = {'title': '用户爱吃重庆合川桃片', 'time': '2026-08-02 13:21', 'weight': 0.55,
              'pinned': False}
    assert me.effective_weight(ident) == 0.55, '身份条目被衰减了'
    assert me.effective_weight(normal) < 0.2, '普通条目不该免疫衰减'


def test_is_identity_entry_recognizes_and_rejects():
    assert me.is_identity_entry({'title': '我的名字叫小蓝'})
    assert me.is_identity_entry({'content': 'Pro 模型姐姐的名字叫大蓝'})
    assert not me.is_identity_entry({'title': '用户爱吃重庆合川桃片'})
    assert not me.is_identity_entry({'title': ''})


def test_age_uses_nearest_timestamp():
    """事实是「状态」不是「事件」：updated_at 更新过就说明还在维护。"""
    e_old = {'title': 'x', 'time': '2026-01-01 00:00', 'updated_at': '2026-10-30 00:00'}
    e_new = {'title': 'x', 'time': '2026-01-01 00:00'}
    # 前者取 updated_at（更近）=> 年龄更小
    assert me.entry_age_days(e_old) < me.entry_age_days(e_new)


# ---------- 写入侧去重（2026-10-31 存量清理暴露）----------
def test_same_content_merges_instead_of_duplicating(ev):
    """同一句话反复触达不该攒条目。

    实测背景：删掉 174 条机械播报后剩 26 条，其中 24 条是同一句
    「主动关心：记得站起来活动一下」—— 每 5~20 分钟写一条。
    Owner 要的是「记得有这回事」，不是「记得说过 24 次」。
    """
    for _ in range(5):
        ev.add('flash', 'event', '主动关心：记得站起来活动一下', '记得站起来活动一下')
    items = ev.all('flash')
    assert len(items) == 1, '同一句攒成了 %d 条' % len(items)
    it = items[0]
    assert it['access_count'] == 4, '重复次数没累加：%r' % it['access_count']
    assert it['weight'] > me.WEIGHT_NEW, '反复出现后权重没上升'


def test_merge_updates_last_access_not_first_time(ev):
    """time 语义是「第一次」，last_access 是「最近一次」"""
    ev.add('flash', 'event', '记得站起来活动一下', '')
    t0 = ev.all('flash')[0]['time']
    ev.add('flash', 'event', '记得站起来活动一下', '')
    it = ev.all('flash')[0]
    assert it['time'] == t0, 'time 被改了（它应保持首次时间）'
    assert it['last_access'], 'last_access 未更新'


def test_different_content_stays_separate(ev):
    ev.add('flash', 'event', '一起看了流星雨', '很冷')
    ev.add('flash', 'event', '一起看了流星雨', '很暖')
    assert len(ev.all('flash')) == 2, 'detail 不同却被合并了'
    ev.add('flash', 'event', '另一件事', '')
    assert len(ev.all('flash')) == 3


def test_merge_respects_role(ev):
    ev.add('flash', 'event', '同一句话', '')
    ev.add('pro', 'event', '同一句话', '')
    assert len(ev.all()) == 2, '不同角色被合并了'


def test_merge_keeps_emotion_hint(ev):
    ev.add('flash', 'event', '记得站起来活动一下', '', emotion='')
    ev.add('flash', 'event', '记得站起来活动一下', '', emotion='关心')
    it = ev.all('flash')[0]
    assert it['emotion'] == '关心', '合并时情绪没补上'
