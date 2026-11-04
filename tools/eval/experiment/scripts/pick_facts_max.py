# -*- coding: utf-8 -*-
"""给 FACTS_MAX 找有依据的取值（2026-11-04）

## 问题

现在 FACTS_MAX=400，而实测 171 条时真实对话注入率已 76%（Owner 定目标 50%）。
⇒ 400 会让注入率长期处于超标状态。

但「降到多少」不能拍脑袋。需要一条**注入率 vs 库规模**的曲线，
找出「注入率仍 ≤50% 的最大条数」。

## 方法

用真实库 21 条为基底，按真实风格补无关记忆到 N 条（N = 21/50/80/120/171/250/400），
对 45 条真实对话算「有记忆被注入」的比例。

⚠ 局限（必须写在结论里）：
  · 补的是**无关**记忆 ⇒ 这是「只增加竞争、不增加帮助」的最坏情况
  · 真实增长会带来相关记忆，注入率可能比这里低
  · 所以得到的是**下界**（最保守的容量）

## 两种阈值的对比

  现况纯 BM25（cov 0.30）
  向量 cos≥0.51（组件口径）

因为它们对「库变大」的敏感度不同。
"""
import importlib.util
import json
import os
import sys

import numpy as np

REPO = r'D:\ai工作站\desktop-pet'
EXP = os.path.join(REPO, 'tools', 'eval', 'experiment')
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, 'tools', 'eval', 'gate_study'))
os.environ.setdefault('PET_EMBED_DIR', os.path.join(EXP, '_embed_probe'))

import memory_embed as mem              # noqa: E402
import memory_engine as me              # noqa: E402
import run_study as rs                  # noqa: E402

TARGET = 0.50
e = mem.get_embedder()
assert e.ok

real = [f for f in json.loads(open(os.path.join(REPO, 'memory.json'), encoding='utf-8').read())['facts']
        if f.get('status', 'active') == 'active']
syn = json.loads(open(os.path.join(EXP, 'data', 'memories-1411.json'), encoding='utf-8').read())['facts']
POOL = [(f.get('content') or '').strip() for f in syn]
POOL = [t for t in POOL if t]
MSGS = [m['text'] for m in rs.load_realdist()['messages']]

perm = np.random.RandomState(20261104).permutation(len(POOL))

print('基底：真实库 %d 条 active；补无关记忆到 N 条；%d 条真实对话' % (len(real), len(MSGS)))
print()

print('=' * 96)
print('注入率 vs 库规模')
print('=' * 96)
print('  %-8s %-14s %-14s' % ('库条数', '纯 BM25', '向量 0.51'))
print('  ' + '-' * 40)

rows = []
for N in (21, 50, 80, 120, 171, 250, 400):
    extra = max(0, N - len(real))
    facts = [dict(f) for f in real]
    texts = [(f.get('content') or '').strip() for f in facts]
    for i in range(extra):
        facts.append({'id': 'syn%04d' % i, 'content': POOL[int(perm[i])],
                      'importance': 3, 'status': 'active'})
        texts.append(POOL[int(perm[i])])

    # ① 纯 BM25（产品现况）
    n_bm = 0
    for q in MSGS:
        if me.search_memory_for_injection(facts, q, top_k=3):
            n_bm += 1
    rate_bm = 100.0 * n_bm / len(MSGS)

    # ② 向量
    V = e.encode(texts)
    n_v = 0
    for q in MSGS:
        if e.search(q, V, texts, k=3, threshold=mem.DEFAULT_THRESHOLD):
            n_v += 1
    rate_v = 100.0 * n_v / len(MSGS)

    rows.append((len(facts), rate_bm, rate_v))
    mark = ' ← 目标 %.0f%%' % (TARGET * 100) if abs(rate_v - TARGET * 100) < 12 else ''
    print('  %-8d %-14s %-14s%s' % (len(facts), '%.0f%%' % rate_bm, '%.0f%%' % rate_v, mark))

print()
print('=' * 96)
print('判读')
print('=' * 96)
# 找向量口径下最后一个仍 <= 50% 的规模
ok = [r for r in rows if r[2] <= TARGET * 100]
if ok:
    best = max(ok, key=lambda r: r[0])
    print('  向量口径下仍 ≤ 目标 %.0f%% 的最大规模：**%d 条**（实测 %.0f%%）'
          % (TARGET * 100, best[0], best[2]))
    # 线性插值估「刚好 50%」的规模
    prev = [r for r in rows if r[0] <= best[0]]
    nxt = [r for r in rows if r[0] > best[0]]
    if prev and nxt:
        a, b = prev[-1], nxt[0]
        if b[2] != a[2]:
            t = (TARGET * 100 - a[2]) / (b[2] - a[2])
            est = a[0] + t * (b[0] - a[0])
            print('  线性插值估算：「刚好 50%%」约在 **%d 条**附近' % round(est))
else:
    print('  ⚠ 连 21 条时注入率就已超过目标？检查口径')

bm_ok = [r for r in rows if r[1] <= TARGET * 100]
if bm_ok:
    bb = max(bm_ok, key=lambda r: r[0])
    print('  BM25 口径下仍 ≤ 目标的最大规模：%d 条（%.0f%%）' % (bb[0], bb[1]))

print()
print('  ⚠ 本曲线是**最坏情况**：补的全是无关记忆（只增竞争、不增帮助）。')
print('    真实增长会带入相关记忆，注入率可能低于此值 ⇒ 得到的是容量**下界**。')
print()
print('  对照：当前 FACTS_MAX = 400')