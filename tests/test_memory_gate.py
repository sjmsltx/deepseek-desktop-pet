# -*- coding: utf-8 -*-
"""v6.53 新增：记忆检索闸门（治"记忆过拟合"）回归测试

覆盖：
  - memory_engine.search_memory 默认行为保持兼容（不过闸）
  - search_memory_for_injection 的闸门：勉强相关的记忆不再注入
  - desktop_pet 注入点的「记忆只作背景、不做话题」硬约束
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import memory_engine as me  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FACTS = [
    {'id': 'f1', 'content': '用户的考研目标是西南大学地图学与地理信息系统 数学二 复习计划',
     'importance': 5, 'status': 'active'},
    {'id': 'f2', 'content': '用户喜欢在桌宠里玩扫雷和 Farkle 骰子', 'importance': 3, 'status': 'active'},
]


def test_default_is_backward_compatible():
    """默认（不过闸）行为不变：能命中就返回，带分数统计"""
    hits = me.search_memory(FACTS, '考研数学二复习计划怎么安排')
    assert hits, '默认检索不应为空'
    assert 'score' in hits[0] and 'matched' in hits[0]


def test_strong_query_passes_gate():
    """强相关查询：过闸且命中目标记忆"""
    hits = me.search_memory_for_injection(FACTS, '考研数学二复习计划怎么安排')
    assert hits, '强相关查询被错误地闸掉了'
    assert hits[0]['id'] == 'f1', '最强命中不是目标记忆'


def test_weak_query_is_gated_out():
    """只共享一个 2-gram 的“泛问句” → 过闸失败 → 不注入
    （例：“扫雷是什么”只是在问概念，并非问用户的偏好，不该把记忆抬出来）"""
    assert me.search_memory_for_injection(FACTS, '扫雷是什么') == []
    assert me.search_memory_for_injection(FACTS, '介绍一下骰子') == []


def test_unrelated_query_empty():
    assert me.search_memory_for_injection(FACTS, '今天天气怎么样') == []


def test_gate_is_not_dead():
    """闸门不能把检索功能闸死：日常短记忆 + 多词强查询仍应能命中"""
    facts = [
        {'id': 's1', 'content': '用户下午上课', 'importance': 3, 'status': 'active'},
        {'id': 's2', 'content': '用户爱喝冰美式咖啡', 'importance': 5, 'status': 'active'},
    ]
    assert me.search_memory_for_injection(facts, '咖啡', top_k=2), '短记忆被闸死了'
    assert me.search_memory_for_injection(facts, '我下午上课安排', top_k=2), '二字命中被闸死了'


def test_source_guards():
    """源码级护栏：闸门常量 + 注入点约束句 + 注入点改用带闸门入口"""
    eng = open(os.path.join(ROOT, 'memory_engine.py'), encoding='utf-8-sig').read()
    pet = open(os.path.join(ROOT, 'desktop_pet.py'), encoding='utf-8-sig').read()
    for k in ('GATE_MIN_MATCHED', 'GATE_MIN_COVERAGE', 'GATE_KEEP_RATIO', 'def search_memory_for_injection'):
        assert k in eng, 'memory_engine 缺少：%s' % k
    assert '记忆的使用方式' in pet, '注入点缺少「记忆只作背景」约束句'
    assert '不要主动把话题引向记忆' in pet, '约束句内容缺失'
    assert 'search_memory_for_injection(' in pet, '注入点未改用带闸门入口'


if __name__ == '__main__':
    test_default_is_backward_compatible()
    test_strong_query_passes_gate()
    test_weak_query_is_gated_out()
    test_unrelated_query_empty()
    test_gate_is_not_dead()
    test_source_guards()
    print('✅ 记忆闸门 6 项断言通过')
