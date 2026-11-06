# -*- coding: utf-8 -*-
"""「注入但未引用」埋点（2026-11-06）

## 为什么有这份测试

Owner 把这一层列为记忆线第三件（「最少人做的第三层」）：
需要知道**取出来的记忆到底有没有被用上**，否则"提高相关性"只能拿 R@3 自证。

## 口径（本文件锁住）

· 判定是**词面代理**：记忆里的"针"（专名/数字/英文/书名号/非泛用 2-gram）出现在回复里
· 但**必须不在用户这条消息里** —— 否则只是复述用户刚说的，不算"记得"
· 无针记忆单列（`no_needle`），不混进引用率分母
· 埋点失败绝不影响对话
"""
import io
import json
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import memory_ledger as ledger      # noqa: E402
import memory_usage as mu           # noqa: E402


@pytest.fixture(autouse=True)
def _tmp_ledger(tmp_path):
    ledger.set_path(str(tmp_path / 'ledger.jsonl'))
    yield
    ledger.set_path(None)


# ---------- A. 取针 ----------
def test_needles_extract_strong_tokens():
    strong, weak = mu.needles('用户爱看《定风波》，也在学 Python 3.14')
    assert '定风波' in strong, '书名号内容没被当成强针'
    assert any('Python' in x for x in strong)
    assert '3.14' in strong
    assert '风波' in weak, '定风波的 2-gram 应同时进弱针'


def test_needles_drop_generic_words():
    nd = mu.needles_flat('用户会做的事情很重要')
    for w in ('用户', '会做', '情的'):
        assert w not in nd, '泛用词被当成针：%r（%r）' % (w, nd)


def test_needles_split_strong_weak():
    strong, weak = mu.needles('用户爱看《定风波》，也在学 Python 3.14')
    assert '定风波' in strong
    assert any('Python' in x for x in strong)
    assert '3.14' in strong
    assert all(x not in strong for x in weak)


def test_needles_empty_for_vague_memory():
    assert mu.needles('好的') == [] or all(len(x) <= 2 for x in mu.needles('好的'))


# ---------- B. 判定 ----------
def test_reference_by_fact_needle():
    v = mu.judge('用户爱吃重庆合川桃片，偏好甜味', reply='记得你爱桃片，甜甜的那种',
                 user_text='我爱吃啥')
    assert v['referenced'] is True, v
    assert '桃片' in v['hit']


def test_not_reference_when_only_echoing_user():
    """用户自己说了「桃片」，模型重复一遍 —— 不算"记得" """
    v = mu.judge('用户爱吃重庆合川桃片', reply='你说桃片，好的',
                 user_text='我想吃桃片')
    assert v['referenced'] is False
    assert v['echoed_only'] is True


def test_not_reference_when_absent():
    v = mu.judge('用户爱吃重庆合川桃片', reply='今天天气不错', user_text='天气')
    assert v['referenced'] is False
    assert v['why'] == 'not_in_reply'


def test_no_needle_is_flagged():
    v = mu.judge('好的', reply='好的', user_text='')
    assert v['referenced'] is False, '单 2-gram 碰巧命中就被当成引用了：%r' % (v,)
    assert v['why'] in ('no_needle', 'weak_only', 'not_in_reply')


def test_single_weak_gram_is_not_enough():
    """只命中一个 2-gram 不算引用（实测误判：「好的」↔「好的」）"""
    v = mu.judge('用户爱吃重庆合川桃片', reply='吃点东西', user_text='')
    assert v['referenced'] is False, v


# ---------- C. 台账与汇总 ----------
def test_record_roundtrip_and_stats():
    facts = [{'id': 'f1', 'text': '用户爱吃重庆合川桃片', 'via': 'vector', 'score': 0.7},
             {'id': 'f2', 'text': '用户在学习 Python', 'via': 'bm25', 'score': 3.2}]
    turn = mu.record_injection(facts, '我爱吃啥', role='flash')
    assert turn['turn']
    out = mu.record_reply(turn, '记得你爱桃片')
    assert out['n'] == 2
    assert out['referenced'] == 1, out

    rows = ledger.read_all()
    assert [r['kind'] for r in rows] == ['inject', 'usage']
    s = mu.stats(rows)
    assert s['turns_injected'] == 1
    assert s['turns_with_use'] == 1
    assert s['facts_injected'] == 2
    assert s['facts_used'] == 1


def test_record_reply_without_turn_is_noop():
    assert mu.record_reply(None, '随便说说') is None
    assert ledger.read_all() == []


def test_report_tool_runs(tmp_path, capsys):
    facts = [{'id': 'f1', 'text': '用户爱吃重庆合川桃片', 'via': 'vector'}]
    for _ in range(3):
        turn = mu.record_injection(facts, '我爱吃啥')
        mu.record_reply(turn, '今天天气不错')
    sys.path.insert(0, os.path.join(BASE, 'tools', 'eval'))
    import memory_usage_report as rep
    rc = rep.main([])
    assert rc == 0
    text = capsys.readouterr().out
    assert '注入条目总数' in text
    assert '从未被引用' in text, '从未被引用的条目没有单列出来'


# ---------- D. 接线护栏 ----------
def test_pet_wires_both_sides():
    src = io.open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    assert 'musage.record_injection(' in src, '注入侧没埋点'
    assert 'musage.record_reply(' in src, '回复侧没埋点'
    # 新一轮要清空，否则上一轮的注入记录会串到这一轮
    assert '_mem_usage_turn = None' in src


def test_ledger_failure_never_breaks_chat(monkeypatch):
    """台账写不进去 ⇒ 埋点返回 None，不抛异常（对话不能因观测设施坍掉）"""
    def boom(*a, **k):
        raise RuntimeError('ledger down')
    monkeypatch.setattr(ledger, 'append', boom)
    turn = mu.record_injection([{'id': 'f1', 'text': '用户爱吃桃片'}], '我爱吃啥')
    assert turn is None
    assert mu.record_reply({'turn': 'x', 'facts': [], 'user': ''}, '回复') is None
