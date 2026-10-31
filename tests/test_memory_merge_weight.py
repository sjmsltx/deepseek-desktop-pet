# -*- coding: utf-8 -*-
"""归并权重：区分「主人反复提及」与「桌宠自己重复推送」

WX-桌宠-20261031-158 的反对（我认）：
    305 归并把 weight 直接打满 1.00，那是「定时器触发了 26 次」，
    不是「被反复提及」。

而 305 注释里引的 Owner 原话「被反复提及的记忆权重上升」指的是：
    **主人**反复说到同一件事 → 这条对关系越重要 → 权重该涨。

两者被混成一件事了。修法：给 add() 加 origin 区分来源。
    origin='user'（默认）  主人说的 / 从对话里提取的 → 合并时涨权重（保留原行为）
    origin='pet'           桌宠自己推送的（定时关心/提醒）→ 合并只记次数，**不动权重**

本文件锁五件事：
A. 桌宠自推的重复合并 → 次数涨、权重不变
B. 主人反复提及 → 权重仍按原规则涨（不破坏既有语义）
C. 两种来源各自计数，不互相污染
D. 老数据没有 origin 字段时按 user 处理（向后兼容）
E. 合并出来的条目能看出「这条被重复推送了多少次」
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import memory_events as me  # noqa: E402


@pytest.fixture
def ev(tmp_path):
    return me.MemoryEvents(str(tmp_path / 'm.json'))


TITLE = '关心：记得站起来活动一下'


# ---------- A. 桌宠自推：只记次数，不动权重 ----------
def test_pet_push_does_not_inflate_weight(ev):
    ev.add('flash', 'event', TITLE, '记得站起来活动一下', origin='pet')
    w0 = ev.all('flash')[0]['weight']
    for _ in range(30):
        ev.add('flash', 'event', TITLE, '记得站起来活动一下', origin='pet')
    e = ev.all('flash')[0]
    assert e['weight'] == pytest.approx(w0, abs=1e-9), (
        '桌宠自推 30 次把权重从 %r 推到 %r —— 这正是 158 反对的那件事' % (w0, e['weight']))


def test_pet_push_still_counts_repeats(ev):
    ev.add('flash', 'event', TITLE, '记得站起来活动一下', origin='pet')
    for _ in range(5):
        ev.add('flash', 'event', TITLE, '记得站起来活动一下', origin='pet')
    e = ev.all('flash')[0]
    assert int(e.get('repeat_count') or 0) == 5, \
        '重复推送次数没记下来：%r' % (e.get('repeat_count'),)


def test_pet_push_does_not_hit_weight_max(ev):
    """158 的具体症状：权重打满 1.00"""
    ev.add('flash', 'event', TITLE, 'd', origin='pet')
    for _ in range(60):
        ev.add('flash', 'event', TITLE, 'd', origin='pet')
    e = ev.all('flash')[0]
    assert e['weight'] < me.WEIGHT_MAX, '权重仍被打满：%r' % (e['weight'],)


# ---------- B. 主人反复提及：权重仍该涨 ----------
def test_user_mention_still_bumps_weight(ev):
    ev.add('flash', 'event', '用户爱吃桃片', '偏好甜味', origin='user')
    w0 = ev.all('flash')[0]['weight']
    ev.add('flash', 'event', '用户爱吃桃片', '偏好甜味', origin='user')
    w1 = ev.all('flash')[0]['weight']
    assert w1 > w0, '主人再次提到，权重该涨：%r → %r' % (w0, w1)


def test_default_origin_is_user(ev):
    """不传 origin 时必须还是老行为（不给调用方添负担）"""
    ev.add('flash', 'event', '默认来源测试', '')
    w0 = ev.all('flash')[0]['weight']
    ev.add('flash', 'event', '默认来源测试', '')
    assert ev.all('flash')[0]['weight'] > w0, '默认 origin 应为 user（保持旧行为）'


# ---------- C. 两种来源不互相污染 ----------
def test_origins_counted_separately(ev):
    ev.add('flash', 'event', TITLE, 'd', origin='pet')
    for _ in range(3):
        ev.add('flash', 'event', TITLE, 'd', origin='pet')
    w_after_pet = ev.all('flash')[0]['weight']
    ev.add('flash', 'event', TITLE, 'd', origin='user')      # 主人主动说起
    e = ev.all('flash')[0]
    # repeat_count = 「这条被重复写入的总次数」（不分来源）：1 次新建 + 4 次合并 = 4
    assert int(e.get('repeat_count') or 0) == 4, \
        'repeat_count 应是总合并次数 4，实际 %r' % (e.get('repeat_count'),)
    assert e['weight'] > w_after_pet, '主人主动提及仍该涨权重'


# ---------- D. 老数据兼容 ----------
def test_legacy_entry_without_origin_treated_as_user(ev, tmp_path):
    """老库里的条目没有 origin 字段，合并时按 user 处理（不知道就当是主人说的）"""
    import json
    p = str(tmp_path / 'legacy.json')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump([{'id': 7, 'time': '2026-10-01 10:00', 'role': 'flash',
                    'type': 'event', 'title': '老条目', 'detail': '',
                    'weight': 0.55, 'access_count': 0}], f, ensure_ascii=False)
    e2 = me.MemoryEvents(p)
    e2.add('flash', 'event', '老条目', '')
    w = e2.all('flash')[0]['weight']
    assert w > 0.55, '老数据无 origin 时应按 user 涨权重，实际 %r' % w


# ---------- E. 可观测 ----------
def test_merged_entry_exposes_repeat_count_even_if_zero(ev):
    ev.add('flash', 'event', '单次条目', '')
    e = ev.all('flash')[0]
    assert 'repeat_count' in e, '字段缺失会让「这条被推了多少次」无从查起'


# ---------- 真实库回归：那条模板不该是满格 ----------
def test_real_library_template_not_at_max():
    """真实 memories.json 里那条定时关心的权重不应是 WEIGHT_MAX

    本条是「症状回归」：158 报的就是它 weight=1.00。
    """
    real = os.path.join(BASE, 'memories.json')
    if not os.path.exists(real):
        pytest.skip('无真实 memories.json')
    ev2 = me.MemoryEvents(real)
    items = ev2.all('flash')
    if not items:
        pytest.skip('真实库为空')
    for e in items:
        w = e.get('weight')
        if w is None:
            continue
        assert float(w) < me.WEIGHT_MAX, (
            '真实库里还有条目权重打满 %r：%r（%s）'
            % (w, (e.get('title') or '')[:30], e.get('origin')))
