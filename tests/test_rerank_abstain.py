# -*- coding: utf-8 -*-
"""rerank 的三道锁（2026-11-12）

## 锁什么

1. **候选 ≤1 条不发 LLM 调用** —— 1 条时「挑」与「不挑」必然相同，
   实测 35 次调用里 25 次（71%）是这种情况；78 条查询对比，注入结果逐条相同。
2. **模型弃权 ⇒ 这一轮不注入** —— 原来 `picked or candidates[:3]` 会硬塞前三条，
   加上 `search_memory`/`search_memory_vector` 两层兜底，「空列表 = 不注入」的语义
   在四层里全被吃掉，弃权信号根本传不上去。
3. **关掉开关（rerank=None）行为不变** —— 仍按重要度+新旧排序。

## 桩的注意点

`_parse_rerank_ids` 是 `@staticmethod`，**不许用 `__get__` 绑定** ——
绑了会多传 self，调用即 TypeError，被 `except` 吞成兜底返回 `[]`。
（2026-11-12 我在这个坑里栽过一次，误以为产品代码坏了。）
"""
import json

import pytest

import desktop_pet as dp
import memory_engine as me

FACTS = [
    {'id': 'A', 'content': '桃片桃片桃片，用户爱吃桃片', 'status': 'active',
     'importance': 1, 'updated_at': '2020-01-01'},
    {'id': 'B', 'content': '用户爱吃桃片', 'status': 'active',
     'importance': 5, 'updated_at': '2026-11-01'},
]
Q = '桃片'


class _Resp(object):
    def __init__(self, content):
        self._c = content

    def __getitem__(self, k):
        if k == 'choices':
            return [{'message': {'content': self._c}, 'finish_reason': 'stop'}]
        if k == 'usage':
            return {'total_tokens': 1}
        return {}


@pytest.fixture
def widget(monkeypatch):
    """空壳 PetWidget（无 GUI 时构造会静默退出，所以不跑 __init__）"""
    calls = []

    def fake_chat(key, data):
        calls.append(json.loads(data.decode()))
        return _Resp('{"ids": [1]}')

    monkeypatch.setattr(dp, 'chat_completions', fake_chat)
    p = dp.PetWidget.__new__(dp.PetWidget)
    p._current_model = lambda: 'stub'
    p._current_api_key = lambda: 'k'
    p._record_api_usage = lambda resp: None
    p._parse_rerank_ids = dp.PetWidget._parse_rerank_ids      # staticmethod，不要 __get__
    p.calls = calls
    return p


def _ids(r):
    return [x.get('id') for x in (r or [])]


# ---------- 1. 候选 ≤1 不发调用 ----------

def test_single_candidate_skips_llm(widget):
    got = widget._rerank_memories(Q, [{'id': 'A', 'text': 'x'}])
    assert got == ['A'], '应原样返回那一条，实际 %r' % (got,)
    assert widget.calls == [], '1 条候选竟发了调用 —— 结构上不可能影响结果'


def test_empty_candidates_returns_empty_without_llm(widget):
    got = widget._rerank_memories(Q, [])
    assert got == [], '空候选应返回空，实际 %r' % (got,)
    assert widget.calls == [], '空候选竟发了调用'


def test_two_candidates_still_call_llm(widget):
    """≥2 条必须仍然调用 —— 防「为省调用把功能改没了」。"""
    widget._rerank_memories(Q, [{'id': 'A', 'text': 'x'}, {'id': 'B', 'text': 'y'}])
    assert len(widget.calls) == 1, '2 条候选应发 1 次调用，实际 %d' % len(widget.calls)


# ---------- 2. 弃权贯穿到底 ----------

def test_abstain_bm25_path_injects_nothing(widget):
    """模型说「都不相关」⇒ BM25 路不注入。"""
    got = me.search_memory(FACTS, Q, top_k=3,
                           rerank=lambda q, c: [])
    assert got == [], '弃权却仍返回 %r —— BM25 路兜底把弃权吃了' % (_ids(got),)


def test_abstain_vector_path_injects_nothing():
    """第三层（向量路）同样不许兜底。"""
    got = me.search_memory_vector(FACTS, Q, top_k=3, rerank=lambda q, c: [])
    assert got == [], '弃权却仍返回 %r —— 向量路兜底把弃权吃了' % (_ids(got),)


def test_abstain_end_to_end_through_widget(widget, monkeypatch):
    """走真 _rerank_memories + union 注入路径，模型弃权 ⇒ 最终不注入。

    这是最关键的一条：四个兜底层里任何一层没改，这里就会拿到非空。
    """
    monkeypatch.setattr(dp, 'chat_completions',
                        lambda key, data: _Resp('{"ids": []}'))
    got = me.search_memory_for_injection(FACTS, Q, top_k=3,
                                         rerank=widget._rerank_memories)
    assert got == [], '弃权没贯穿到底，仍注入 %r' % (_ids(got),)


def test_abstain_via_exception_also_injects_nothing():
    """重排抛异常也按弃权处理（宁可这轮不注入）。"""
    def boom(q, c):
        raise RuntimeError('模拟挂掉')

    assert me.search_memory(FACTS, Q, top_k=3, rerank=boom) == []
    assert me.search_memory_vector(FACTS, Q, top_k=3, rerank=boom) == []


# ---------- 3. 关闭开关时行为不变 ----------

def test_rerank_none_orders_by_importance():
    """rerank=None ⇒ 按 importance+新旧 重排（B importance=5 应在前）。

    ⚠ 这条防「修弃权把正常路径改坏」。
    """
    got = me.search_memory(FACTS, Q, top_k=3, rerank=None)
    ids = _ids(got)
    assert 'B' in ids, '正常路径丢了 B：%r' % (ids,)
    assert ids[0] == 'B', '关闭重排时应按重要度，实际首位 %r' % (ids[0] if ids else None,)
