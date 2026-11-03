# -*- coding: utf-8 -*-
"""status 硬过滤是真防线还是测试空气（2026-11-03，WX-173 §七 第 3 条）

## 要证的事

`SUPERSEDED=100%`（失效事实没冒充现状）这条指标，可能是两种完全不同的东西：

| 情况 | 含义 | 测试价值 |
|---|---|---|
| A. `search_memory` 里的 `status=='active'` 过滤挡住的 | **结构保证** | 测试测的是空气（过滤在，永远绿） |
| B. 检索本来就召不回失效事实 | **测试保证** | 有价值 |

微信的判断是 A。**要证 A，就得证明「把过滤去掉，失效事实真的会被召回」。**
本文件用「临时把它标成 active 喂进去」来等价模拟「去掉过滤」，
不改产品代码、不改真实库。
"""
import io
import json
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import memory_engine as me  # noqa: E402


def _facts():
    p = os.path.join(BASE, 'memory.json')
    if not os.path.exists(p):
        pytest.skip('无 memory.json')
    d = json.loads(io.open(p, encoding='utf-8').read())
    fs = d.get('facts') if isinstance(d, dict) else d
    if not fs:
        pytest.skip('memory.json 为空')
    return fs


def _superseded(_facts):
    """找一条 status != active 且能被「我喜欢喝什么咖啡」召回的"""
    out = []
    for f in _facts:
        if f.get('status', 'active') == 'active':
            continue
        hits = me.search_memory(_facts, str(f.get('content') or ''), top_k=8)
        if hits:
            out.append((f, hits))
    return out


def test_superseded_facts_are_actually_filtered_out():
    """⭐ 主判据：真实库里存在 status!=active 的事实，且**不会被注入入口召回**。"""
    fs = _facts()
    sup = [f for f in fs if f.get('status', 'active') != 'active']
    assert sup, '库里没有 superseded 事实，这条测试无从谈起'
    # 逐条用它自己的内容去问：注入入口必须一条都返回不出来
    leaked = []
    for f in sup:
        q = str(f.get('content') or '')[:40]
        hits = me.search_memory_for_injection(fs, q, top_k=3)
        texts = [str(h.get('text') or '') for h in hits]
        if any(str(f.get('content') or '')[:20] in t for t in texts):
            leaked.append((q, texts[:1]))
    assert not leaked, '失效事实被注入入口召回了：%r' % leaked


def test_without_status_filter_superseded_would_be_recalled():
    """⭐⭐ 核心：把失效事实临时标成 active（等价于「去掉过滤」），它**会**被召回。

    这一条证明 `SUPERSEDED=100%` 是**结构保证**（靠 L147 那行过滤），
    不是「检索本来就不会召回到它」。

    如果这条测试失败了（即：标成 active 也召不回），
    说明 `test_superseded_never_recalled` 在测空气 —— 那时该重新设计那个指标。
    """
    fs = _facts()
    sup = [f for f in fs if f.get('status', 'active') != 'active']
    if not sup:
        pytest.skip('库里没有 superseded 事实')

    recalled_before = 0
    recalled_after = 0
    for f in sup:
        q = str(f.get('content') or '')[:40]
        if not q:
            continue
        needle = q[:12]
        # 过滤在：应 0 条
        hits0 = me.search_memory_for_injection(fs, q, top_k=3)
        if any(needle in str(h.get('text') or '') for h in hits0):
            recalled_before += 1
        # 过滤被绕过（临时标 active）：应能召回
        fs2 = [dict(x) for x in fs]
        for x in fs2:
            if x.get('id') == f.get('id'):
                x['status'] = 'active'
        hits1 = me.search_memory_for_injection(fs2, q, top_k=3)
        if any(needle in str(h.get('text') or '') for h in hits1):
            recalled_after += 1

    assert recalled_before == 0, '过滤在的情况下仍有 %d 条被召回' % recalled_before
    assert recalled_after > 0, (
        '把失效事实标成 active 之后仍然召回不了 ⇒ '
        '`test_superseded_never_recalled` 测的是空气，'
        '防线不是 status 过滤（或者题库里这条压根不该被召回）。'
        '请重新设计该指标。')


def test_filter_is_the_only_gate():
    """结构钉：`search_memory` 里必须有且只有一处 status 过滤。

    ⚠ 这条用 ast 判，不用 grep —— 注释里提到「status=='active'」不算违规
    （本仓因为这个踩过三次：check_channel_ledger / test_no_log_pollution / silent_guard）。
    """
    import ast as _ast
    src = io.open(os.path.join(BASE, 'memory_engine.py'), encoding='utf-8').read()
    tree = _ast.parse(src)
    hits = []
    for n in _ast.walk(tree):
        if not isinstance(n, _ast.FunctionDef) or n.name not in ('search_memory',
                                                                 'search_memory_for_injection'):
            continue
        seg = _ast.get_source_segment(src, n) or ''
        for i, line in enumerate(seg.splitlines()):
            if "'status'" in line or '"status"' in line:
                hits.append((n.name, i + 1, line.strip()[:70]))
    assert len(hits) == 1, (
        'status 过滤出现 %d 处（应为 1，只在 search_memory 里）：%r' % (len(hits), hits))
