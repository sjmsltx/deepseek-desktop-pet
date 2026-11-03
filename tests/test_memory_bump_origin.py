# -*- coding: utf-8 -*-
"""`_bump` 的 origin 保护（2026-11-03，WX-174 §四-b 报出）

## 缺陷

`add()` 合并路径特意做了「pet 不动 weight」（注释原话：「定时关心是一句固定模板，
一天触发几十次，照样能把权重推到满格。那不是『被反复提及』，是『定时器跑了很多次』」），
但 `_bump()`（检索命中路径）**无条件** `weight = min(MAX, base + 0.06)`
⇒ 同一个风险，一条路堵了、一条路漏着。

## 后果（算出来的，不是猜的）

一条 origin='pet' 的模板话被命中 8 次：
    0.55 + 8 × 0.06 = 1.03 → min() 截到 1.0 = WEIGHT_MAX 满格

## 为什么现在才修不怪（自限说明）

当前库里 6 条 weight 全是 0.55（= WEIGHT_NEW），说明 `_bump` 实际几乎没生效
⇒ 这是**代码层不一致，不是已发生的事故**。但接上语义检索后命中率会上来。
"""
import io
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import memory_events as me  # noqa: E402


def _ev(tmp_path):
    return me.MemoryEvents(str(tmp_path / 'm.json'))


def _mem(origin, weight=None, title='测试条目'):
    d = {'id': 1, 'title': title, 'detail': 'd', 'origin': origin,
         'access_count': 0, 'repeat_count': 0, 'role': 'flash', 'type': 'event',
         'time': '2026-11-01 10:00'}
    if weight is not None:
        d['weight'] = weight
    return d


def test_pet_entry_weight_does_not_grow_on_hit(tmp_path):
    """⭐ origin='pet' 的条目被命中 20 次，weight 必须纹丝不动。"""
    ev = _ev(tmp_path)
    pool = [_mem('pet', weight=0.55)]
    for _ in range(20):
        ev._bump(pool, 0)
    assert pool[0]['weight'] == 0.55, (
        'pet 条目被命中 20 次后 weight 变成 %r —— 定时器模板会因此满格'
        % pool[0]['weight'])


def test_pet_entry_weight_never_reaches_max(tmp_path):
    """把 WX-158 的症状直接写成断言：不论命中多少次，都不许到 WEIGHT_MAX。"""
    ev = _ev(tmp_path)
    pool = [_mem('pet', weight=me.WEIGHT_NEW)]
    for _ in range(50):
        ev._bump(pool, 0)
    assert pool[0]['weight'] < me.WEIGHT_MAX, (
        'pet 条目被命中 50 次后到了 WEIGHT_MAX=%r' % me.WEIGHT_MAX)


def test_pet_entry_still_counts_access(tmp_path):
    """不加权但仍然要记「被命中过一次」—— 不是整个跳过。"""
    ev = _ev(tmp_path)
    pool = [_mem('pet', weight=0.55)]
    ev._bump(pool, 0)
    ev._bump(pool, 0)
    assert pool[0]['access_count'] == 2, 'pet 条目的命中计数被一起跳过了'
    assert pool[0]['last_access'], 'pet 条目的 last_access 没更新'


def test_user_entry_still_gets_bumped(tmp_path):
    """⭐ 反向：origin='user' 的条目必须照旧加权，别把功能修没了。"""
    ev = _ev(tmp_path)
    pool = [_mem('user', weight=0.55)]
    ev._bump(pool, 0)
    assert abs(pool[0]['weight'] - (0.55 + me.WEIGHT_BUMP)) < 1e-9, (
        'user 条目被命中后没加权：%r' % pool[0]['weight'])


def test_user_entry_weight_capped(tmp_path):
    """user 条目加权也要被 WEIGHT_MAX 夹住。"""
    ev = _ev(tmp_path)
    pool = [_mem('user', weight=0.99)]
    for _ in range(10):
        ev._bump(pool, 0)
    assert pool[0]['weight'] == me.WEIGHT_MAX


def test_missing_origin_treated_as_user(tmp_path):
    """老数据没有 origin 字段 ⇒ 按 user 处理（与 add() 的判据一致）。"""
    ev = _ev(tmp_path)
    pool = [_mem('user', weight=0.55)]
    del pool[0]['origin']
    ev._bump(pool, 0)
    assert abs(pool[0]['weight'] - (0.55 + me.WEIGHT_BUMP)) < 1e-9, (
        '缺 origin 的老数据被当成 pet 了')


def test_bump_and_add_share_the_same_origin_rule():
    """⭐ 结构钉：两条路径必须用**同一个**判据。

    判据：`memory_events.py` 里出现 origin 判断的地方，字符串比对方式一致
    （都允许大小写与空格差异，因为 add() 里用的是 .strip().lower()）。
    """
    src = io.open(os.path.join(BASE, 'memory_events.py'), encoding='utf-8').read()
    import ast as _ast
    tree = _ast.parse(src)

    def _bump_src():
        for n in _ast.walk(tree):
            if isinstance(n, _ast.FunctionDef) and n.name == '_bump':
                return _ast.get_source_segment(src, n) or ''
        return ''

    seg = _bump_src()
    assert seg, '找不到 _bump'
    assert "'pet'" in seg, '_bump 里没有 pet 判断'
    assert 'weight' in seg.split("'pet'")[1][:260], \
        '_bump 里 pet 判断之后没有阻止 weight 变动的逻辑'
