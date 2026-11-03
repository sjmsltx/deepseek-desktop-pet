# -*- coding: utf-8 -*-
"""选自适应闸门的规模阈值（2026-11-03）

## 为什么需要自适应

产品的回归护栏（`tests/test_memory_eval.py` 的 BASELINE）写着「只许上调，不许为了变绿往下改」，
且 `H_R@3 = 3/12`。实测稀有词闸门在 21 条真库上会把 H_R@3 打到 **2/12** ⇒ 触发护栏。

但语料变密后误报率确实涨（1411 条实测 4.8% → 26.9%），必须治。

⇒ 折中：**小库用小库的判据，大库用大库的判据**。
   问题退化成「阈值取多少」。

## 怎么选阈值

要求：
1. 阈值以上，新判据的收益（误报下降）明显大于代价（召回下降）
2. 阈值以下（尤其 21 条），必须与旧判据**完全一致**，不能动护栏

下面在每个规模点同时跑两种判据，看拐点在哪。
"""
import io
import json
import os
import random
import sys

REPO = r'D:\ai工作站\desktop-pet'
OUT = r'D:\AutoClawworkspace\桌宠记忆实验-20261103'
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import memory_engine as me  # noqa: E402

REPEATS = 3
POINTS = [21, 35, 50, 75, 100, 150, 200]


def median(xs):
    s = sorted(xs)
    n = len(s)
    return 0.0 if not n else (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0)


def rare_count(qt, dt, idx):
    hit = [w for w in set(qt) if w in set(dt)]
    if not hit:
        return 0
    if len(set(qt)) <= 1:
        return len(hit)
    idfs = {w: idx._idf(w) for w in set(qt)}
    thr = median(list(idfs.values()))
    return len([w for w in hit if idfs[w] > thr])


def run_lib(mixed, cases, neg_qs, mode):
    active = [f for f in mixed if f.get('status', 'active') == 'active']
    docs = [{'id': str(f.get('id', i)), 'content': str(f.get('content') or '')}
            for i, f in enumerate(active)]
    idx = me.BM25Index([{'id': d['id'], 'text': d['content']} for d in docs])

    def run(q):
        qt = me.tokenize(q)
        det = idx.search_detailed(q, top_k=8)
        if not det:
            return []
        best = det[0]['score']
        kept = []
        for d in det:
            if mode == 'old':
                ok = (d['matched'] >= 2 or d['coverage'] >= 0.30) \
                    and d['score'] >= 0.25 * best
            else:
                nr = rare_count(qt, idx.doc_tokens[d['index']], idx)
                ok = nr >= 1 and d['coverage'] >= 0.30 and d['score'] >= 0.25 * best
            if ok:
                kept.append(d)
        kept.sort(key=lambda x: -x['score'])
        return [docs[d['index']] for d in kept[:3]]

    r = sum(1 for c in cases['recall']
            if any(n in ' '.join(x['content'] for x in run(c['query'])) for n in c['expect_any']))
    h = sum(1 for c in cases['holdout']
            if any(n in ' '.join(x['content'] for x in run(c['query'])) for n in c['expect_any']))
    inj = sum(1 for q in neg_qs if run(q))
    return r, h, inj


def main():
    real = [f for f in json.loads(io.open(os.path.join(REPO, 'memory.json'),
                                          encoding='utf-8').read())['facts']
            if f.get('status') == 'active']
    cases = json.loads(io.open(os.path.join(REPO, 'tools', 'eval', 'cases.json'),
                               encoding='utf-8').read())
    neg = json.loads(io.open(os.path.join(REPO, 'tools', 'eval', 'negatives.json'),
                             encoding='utf-8').read())
    neg_qs = [q for cat, qs in neg['categories'].items() for q in qs]
    noise = json.loads(io.open(os.path.join(OUT, 'experiment.json'), encoding='utf-8').read())['facts']

    print('=' * 88)
    print('同一规模下两种判据对比（%d 次随机噪声均值）' % REPEATS)
    print('=' * 88)
    print('  %-8s %-26s %-26s %s' % ('总条数', '旧 matched>=2 OR cov>=.30',
                                     '新 rare>=1 AND cov>=.30', '差（新-旧）'))
    print('  %-8s %-26s %-26s' % ('', 'rec / hold / 负样本', 'rec / hold / 负样本'))
    print('  ' + '-' * 84)
    rows = []
    for n in POINTS:
        agg = {'old': [], 'new': []}
        for rep in range(REPEATS):
            rnd = random.Random(20261103 + rep * 104729 + n)
            pool = noise[:]
            rnd.shuffle(pool)
            mixed = [{'id': str(f.get('id') or 'r'), 'content': str(f.get('content') or ''),
                      'status': 'active'} for f in real]
            for i, f in enumerate(pool[:max(0, n - len(real))]):
                mixed.append({'id': 'n%05d' % i, 'content': f.get('content', ''),
                              'status': 'active'})
            for mode in ('old', 'new'):
                agg[mode].append(run_lib(mixed, cases, neg_qs, mode))
        avg = lambda xs, i: sum(x[i] for x in xs) / len(xs)  # noqa: E731
        o = [avg(agg['old'], i) for i in range(3)]
        w = [avg(agg['new'], i) for i in range(3)]
        print('  %-8d %-26s %-26s hold %+.1f / 负样本 %+.1f' % (
            n,
            '%.1f / %.1f / %.1f' % tuple(o),
            '%.1f / %.1f / %.1f' % tuple(w),
            w[1] - o[1], w[2] - o[2]))
        rows.append({'total': n, 'old': o, 'new': w})

    print()
    print('读法：负样本列越低越好，hold 列越高越好。')
    print('要选的是「负样本明显降、hold 几乎不降」的起始规模。')
    p = os.path.join(OUT, 'gate_threshold.json')
    io.open(p, 'w', encoding='utf-8', newline='\n').write(
        json.dumps({'note': '每点 %d 次随机噪声均值' % REPEATS, 'rows': rows},
                   ensure_ascii=False, indent=2) + '\n')
    print()
    print('  已写 %s' % p)
    return 0


if __name__ == '__main__':
    sys.exit(main())
