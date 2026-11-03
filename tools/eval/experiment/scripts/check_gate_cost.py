# -*- coding: utf-8 -*-
"""改闸门前的最后一道核对：真实库（21 条）上会不会倒退（2026-11-03）

## 为什么必须做这步

`gate_mechanism.py` 测出 `rare>=1 AND cov>=0.30` 在 **200 条容量**下：
- 负样本误命中 6.4/42 → 1.0/42（15% → 2%）
- holdout 3.2/12 → 2.0/12（25% → 17%）← **这一列是退步**

但产品**现在**真实状态是 21 条。如果改闸门在 21 条上也把 holdout 降了，
那就是「为了一个还没发生的问题（库变大）牺牲了现在的效果」。

所以必须先回答：**21 条真库上，这个改动是赚还是亏？**

## 判据

| 21 条上的结果 | 该不该改 |
|---|---|
| holdout 不降，误报降 | 该改 |
| holdout 降，误报降 | 要看降多少，报给 Owner |
| holdout 降，误报不降 | 不该改 |

同时必须验 `test_memory_gate.py` 的语义契约：「扫雷是什么」不能注入。
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


def median(xs):
    s = sorted(xs)
    n = len(s)
    return 0.0 if not n else (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0)


def n_rare(qt, doc_tokens, idx):
    hit = [w for w in set(qt) if w in set(doc_tokens)]
    if not hit:
        return 0
    idfs = {w: idx._idf(w) for w in set(qt)}
    thr = median(list(idfs.values()))
    return len([w for w in hit if idfs[w] > thr])


def eval_lib(mixed, cases, neg_qs, mode, cov_thr=0.30):
    """mode: 'old' 现状 / 'rare' 新配方"""
    active = [f for f in mixed if f.get('status', 'active') == 'active']
    docs = [{'id': f.get('id', str(i)), 'content': f.get('content', '')}
            for i, f in enumerate(active)]
    idx = me.BM25Index([{'id': d['id'], 'text': d['content']} for d in docs])

    def run(query, top_k=3):
        qt = me.tokenize(query)
        det = idx.search_detailed(query, top_k=8)
        if not det:
            return []
        best = det[0]['score']
        kept = []
        for d in det:
            if mode == 'old':
                ok = (d['matched'] >= 2 or d['coverage'] >= 0.30) and \
                     d['score'] >= 0.25 * best
            else:
                ok = (n_rare(qt, idx.doc_tokens[d['index']], idx) >= 1
                      and d['coverage'] >= cov_thr)
            if ok:
                kept.append(d)
        kept.sort(key=lambda x: (-x['score'],))
        return [docs[d['index']] for d in kept[:top_k]]

    r = sum(1 for c in cases['recall']
            if any(n in ' '.join(x['content'] for x in run(c['query']))
                   for n in c['expect_any']))
    h = sum(1 for c in cases['holdout']
            if any(n in ' '.join(x['content'] for x in run(c['query']))
                   for n in c['expect_any']))
    inj = sum(1 for q in neg_qs if run(q))
    # 语义契约：概念提问不能注入
    mine = run('扫雷是什么')
    return r, h, inj, len(mine)


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

    print('=' * 78)
    print('真实库 21 条（产品当前状态）')
    print('=' * 78)
    print('  %-22s %-10s %-10s %-16s %s' % ('配方', 'recall', 'holdout', '负样本误命中', '扫雷注入'))
    print('  ' + '-' * 74)
    old = (me.GATE_MIN_MATCHED, me.GATE_MIN_COVERAGE, me.GATE_KEEP_RATIO)
    for mode, label in (('old', '现状 m>=2 OR cov>=.30'), ('rare', '新 rare>=1 AND cov>=.30')):
        r, h, inj, mine = eval_lib(real, cases, neg_qs, mode)
        print('  %-22s %-10s %-10s %-16s %d 条' % (
            label, '%d/6' % r, '%d/12' % h, '%d/42 (%.0f%%)' % (inj, inj/42*100), mine))

    print()
    print('=' * 78)
    print('200 条容量（产品上限，5 个随机种子取均值）')
    print('=' * 78)
    print('  %-22s %-10s %-10s %-16s %s' % ('配方', 'recall', 'holdout', '负样本误命中', '扫雷注入'))
    print('  ' + '-' * 74)
    for mode, label in (('old', '现状 m>=2 OR cov>=.30'), ('rare', '新 rare>=1 AND cov>=.30')):
        rs, hs, is_, ms = [], [], [], []
        for rep in range(5):
            rnd = random.Random(20261103 + rep * 104729)
            pool = noise[:]
            rnd.shuffle(pool)
            mixed = [{'id': str(f.get('id') or 'r'), 'content': str(f.get('content') or ''),
                      'status': 'active'} for f in real]
            for i, f in enumerate(pool[:200 - len(real)]):
                mixed.append({'id': 'n%05d' % i, 'content': f.get('content', ''),
                              'status': 'active'})
            r, h, inj, mine = eval_lib(mixed, cases, neg_qs, mode)
            rs.append(r); hs.append(h); is_.append(inj); ms.append(mine)
        avg = lambda x: sum(x) / len(x)  # noqa: E731
        print('  %-22s %-10s %-10s %-16s %.1f 条' % (
            label, '%.1f/6' % avg(rs), '%.1f/12' % avg(hs),
            '%.1f/42 (%.0f%%)' % (avg(is_), avg(is_)/42*100), avg(ms)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
