# -*- coding: utf-8 -*-
"""库规模对召回的影响（2026-11-04）

## 为什么补这一段

上一轮干扰项测试只测了 0/100/500/1411 四个点，而**产品上限是 200 条**。
100 → top1 10/12、500 → top1 4/12，中间跨度太大，看不出 200 条时到底什么样。
这里按 0/50/100/150/200/300/500 补齐，并把注入率也一起量。

## 口径说明（避免误读）

干扰项来自 1411 条合成记忆（与本机真实记忆无关）。正确答案**仍在库里**，
所以「找不到」是真的被淹没，不是上次那个「库里根本没有」的错误测试。
"""
import io
import json
import os
import sys
import time

REPO = r'D:\ai工作站\desktop-pet'
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, 'tools', 'eval', 'gate_study'))
os.environ.setdefault('PET_EMBED_DIR',
                      os.path.join(REPO, 'tools', 'eval', 'experiment', '_embed_probe'))

import numpy as np                      # noqa: E402

import memory_embed as mem              # noqa: E402
import run_study as rs                  # noqa: E402

DATA = os.path.join(REPO, 'tools', 'eval', 'experiment', 'data')
THR = mem.DEFAULT_THRESHOLD

e = mem.get_embedder()
assert e.ok

FACTS = [f for f in json.loads(io.open(os.path.join(REPO, 'memory.json'),
                                      encoding='utf-8').read())['facts']
         if f.get('status', 'active') == 'active']
FT = [(f.get('content') or '').strip() for f in FACTS]
FV = e.encode(FT)
HOLD = rs.load_cases()['holdout']
MSGS = rs.load_realdist()['messages']

big = json.loads(io.open(os.path.join(DATA, 'memories-1411.json'), encoding='utf-8').read())['facts']
BIG_T = [(f.get('content') or f.get('text') or '').strip() for f in big]
BIG_T = [t for t in BIG_T if t]
rng = np.random.RandomState(20261104)
perm = rng.permutation(len(BIG_T))

print('=' * 96)
print('库规模 → 召回 / 注入率（阈值 %.2f，正确答案始终在库里）' % THR)
print('=' * 96)
print('  %-8s %-10s %-10s %-12s %-10s %s'
      % ('干扰条数', '库总条数', 'top1 找对', 'top3 找对', '注入率', '单次延迟'))
print('  ' + '-' * 80)

cache = {}
for extra in (0, 50, 100, 150, 200, 300, 500, 1000, 1411):
    if extra == 0:
        texts, vecs = list(FT), FV
    else:
        if extra not in cache:
            dvec = e.encode([BIG_T[int(i)] for i in perm[:extra]])
            cache[extra] = dvec
        texts = list(FT) + [BIG_T[int(i)] for i in perm[:extra]]
        vecs = np.vstack([FV, cache[extra]])
    hit1 = hit3 = 0
    t0 = time.perf_counter()
    for c in HOLD:
        qv = e.encode([c['query']])[0]
        sims = vecs @ qv
        order = np.argsort(-sims)[:3]
        if sims[order[0]] < THR:
            continue
        ranked = [texts[int(j)] for j in order if sims[int(j)] >= THR]
        if ranked and rs.hit_any([ranked[0]], c['expect_any']):
            hit1 += 1
        if rs.hit_any(ranked[:3], c['expect_any']):
            hit3 += 1
    # 注入率：真实对话在「真库 + 干扰」上跑（干扰会带来新注入，这是真实风险）
    inj = 0
    for m in MSGS:
        if mem.is_definition_question(m['text']):
            continue
        qv = e.encode([m['text']])[0]
        sims = vecs @ qv
        if float(sims.max()) >= THR:
            inj += 1
    dt = (time.perf_counter() - t0) / max(len(HOLD), 1) * 1000
    print('  %-8d %-10d %-10s %-12s %-10s %.1f ms'
          % (extra, len(texts), '%d/12' % hit1, '%d/12' % hit3,
             '%.0f%%' % (100.0 * inj / len(MSGS)), dt))

print()
print('  产品上限 200 条（memory 上限）对应「干扰 179 条」档 ⇒ 看 150~200 两行')
print('  ⚠ 干扰项是无关合成记忆，真实增长会伴随「相关记忆变多」，')
print('    所以这里量的是**最坏情况**（只增加竞争、不增加帮助）。')
