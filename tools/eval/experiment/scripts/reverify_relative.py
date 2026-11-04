# -*- coding: utf-8 -*-
"""固定阈值随库增大而失效 → 试相对判据（2026-11-04）

## 问题

实测（reverify_scale.py，阈值固定 0.51）：

    库 21 条    注入率 36%（召回 11/12）
    库 121 条   注入率 67%
    库 221 条   注入率 76%
    库 1432 条  注入率 87%

机制是**极值效应**：库里有 N 条时，最大余弦是 N 个样本的最大值，N 越大越高。
所以「cos ≥ 0.51」这条绝对判据的等价含义是「库越大越宽松」——
与「记忆过拟合」要治的方向正好相反。

## 试什么

在绝对阈值之外加**相对判据**（拿该查询在库内的相似度分布做参照）：

  A  现况：cos ≥ 0.51
  B  绝对 + 均值距：cos ≥ 0.51 且 cos - mean(sims) ≥ d
  C  绝对 + z 分：cos ≥ 0.51 且 (cos - mean)/std ≥ z

## 验收

对每个库规模（21 / 171 / 521 / 1432）同时看：
  · 留出集召回（12 条）   · 真实对话注入率（45 条）
理想结果：召回在 11/12 附近，注入率在各规模上都压得住。
"""
import io
import json
import os
import sys

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
perm = np.random.RandomState(20261104).permutation(len(BIG_T))


_BUILD_CACHE = {}


def build(extra):
    """带缓存的库构建。

    ⚠ 第一版没有缓存：evaluate() 里每条查询都调一次 build()，
      12 条 × 6 判据 × 4 规模 = 288 次重编码 ⇒ 跑超时（实测 20 分钟未完）。
      缓存后同一规模只编码一次。
    """
    if extra in _BUILD_CACHE:
        return _BUILD_CACHE[extra]
    if extra == 0:
        out = (list(FT), FV)
    else:
        texts = list(FT) + [BIG_T[int(i)] for i in perm[:extra]]
        vecs = np.vstack([FV, e.encode([BIG_T[int(i)] for i in perm[:extra]])])
        out = (texts, vecs)
    _BUILD_CACHE[extra] = out
    return out


def stats(sims):
    return float(sims.max()), float(sims.mean()), float(sims.std())


# 预先把每个（库规模 × 查询）的 sims 统计算好，避免重复编码
SCALES = [0, 150, 500, 1411]
QUERIES = [('hold', c['id'], c['query'], c.get('expect_any')) for c in HOLD]
QUERIES += [('msg', 'm%02d' % i, m['text'], None) for i, m in enumerate(MSGS)]

print('=' * 104)
print('各库规模下，查询的相似度分布（看极值效应是否成立）')
print('=' * 104)
print('  %-10s %-12s %-12s %-12s %-12s'
      % ('库条数', 'hold max中位', 'msg max中位', 'hold mean中位', 'msg mean中位'))
print('  ' + '-' * 88)
DATA_S = {}
for extra in SCALES:
    texts, vecs = build(extra)
    rec = {}
    for kind, qid, q, exp in QUERIES:
        qv = e.encode([q])[0]
        sims = vecs @ qv
        mx, mu, sd = stats(sims)
        idx = int(np.argmax(sims))
        ok = (exp is not None and rs.hit_any([texts[idx]], exp))
        rec[qid] = dict(max=mx, mean=mu, std=sd, top1=texts[idx], ok=ok)
    DATA_S[extra] = rec
    hmax = np.median([rec[c['id']]['max'] for c in HOLD])
    mmax = np.median([rec['m%02d' % i]['max'] for i in range(len(MSGS))])
    hmu = np.median([rec[c['id']]['mean'] for c in HOLD])
    mmu = np.median([rec['m%02d' % i]['mean'] for i in range(len(MSGS))])
    print('  %-10d %-12.4f %-12.4f %-12.4f %-12.4f'
          % (len(texts), hmax, mmax, hmu, mmu))

print()
print('=' * 104)
print('三种判据 × 四种库规模')
print('=' * 104)
print('  %-22s %-14s %-14s %-14s %-14s'
      % ('判据', '库 21', '库 171', '库 521', '库 1432'))
print('  ' + '-' * 92)


_QV_CACHE = {}


def qvec(q):
    if q not in _QV_CACHE:
        _QV_CACHE[q] = e.encode([q])[0]
    return _QV_CACHE[q]


def evaluate(rule, extra):
    rec = DATA_S[extra]
    hit3 = 0
    texts, vecs = build(extra)
    for c in HOLD:
        qv = qvec(c['query'])
        sims = vecs @ qv
        order = np.argsort(-sims)[:3]
        kept = [texts[int(j)] for j in order if rule(sims, int(j))]
        if rs.hit_any(kept[:3], c['expect_any']):
            hit3 += 1
    inj = 0
    for i, m in enumerate(MSGS):
        r = rec['m%02d' % i]
        if rule(None, 0, pre=r) and not mem.is_definition_question(m['text']):
            inj += 1
    return hit3, 100.0 * inj / len(MSGS)


def rule_abs(sims, j, pre=None):
    return (pre['max'] if pre else float(sims[j])) >= THR


def rule_gap(d):
    def f(sims, j, pre=None):
        if pre is not None:
            return pre['max'] >= THR and (pre['max'] - pre['mean']) >= d
        return float(sims[j]) >= THR and (float(sims[j]) - float(sims.mean())) >= d
    return f


def rule_z(z):
    def f(sims, j, pre=None):
        if pre is not None:
            sd = pre['std'] or 1e-9
            return pre['max'] >= THR and (pre['max'] - pre['mean']) / sd >= z
        sd = float(sims.std()) or 1e-9
        return float(sims[j]) >= THR and (float(sims[j]) - float(sims.mean())) / sd >= z
    return f


rows = []
for name, rule in (('A 绝对 cos≥0.51', rule_abs),
                   ('B 绝对 + 均值距≥0.15', rule_gap(0.15)),
                   ('B 绝对 + 均值距≥0.20', rule_gap(0.20)),
                   ('C 绝对 + z≥1.5', rule_z(1.5)),
                   ('C 绝对 + z≥2.0', rule_z(2.0)),
                   ('C 绝对 + z≥2.5', rule_z(2.5))):
    cells = []
    for extra in SCALES:
        h, inj = evaluate(rule, extra)
        cells.append('%d/12 · %.0f%%' % (h, inj))
    print('  %-22s %-14s %-14s %-14s %-14s' % (name, *cells))
    rows.append((name, cells))

print()
print('  单元格含义：留出集召回 · 真实对话注入率')
print('  ⚠ 这张表**不能直接选最优**：z/均值距 也依赖库规模（分布随 N 变窄），')
print('    只能看「哪种判据在四种规模上都稳」，再单独定系数。')
