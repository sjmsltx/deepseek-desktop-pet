# -*- coding: utf-8 -*-
"""细密度曲线：产品真实容量内（<=200 条）误命中怎么涨（2026-11-03）

## 为什么补这个

粗粒度实验得到「21 条 4.8% → 1421 条 35.7%」，但产品 `MAX_MEMORIES=200`，
超过就淘汰 ⇒ **1400 条这个点产品根本走不到**。

所以真正要回答的是：**在 0~200 这条产品真会经历的路上，误命中涨了多少？**
如果 200 条时是 12%，那这是「需要关注」；如果 200 条时也是 30%，那是「必须改」。

## 采样点

0 / 25 / 50 / 75 / 100 / 125 / 150 / 175 / 200（产品上限）
+ 300 / 500 作为「假如放宽上限」的前瞻参考

每个点重复 3 次不同随机噪声，取均值 ± 极差 —— 单次结果可能是抽样噪声（教训 ⑥）。
"""
import io
import json
import os
import random
import sys

REPO = r'D:\ai工作站\desktop-pet'
OUT = r'D:\AutoClawworkspace\mem-exp-20261103'
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import memory_engine as me  # noqa: E402

POINTS = [0, 25, 50, 75, 100, 125, 150, 175, 200, 300, 500]
REPEATS = 3


def main():
    real = [f for f in json.loads(io.open(os.path.join(REPO, 'memory.json'),
                                          encoding='utf-8').read())['facts']
            if f.get('status') == 'active']
    noise = json.loads(io.open(os.path.join(OUT, 'experiment.json'), encoding='utf-8').read())['facts']
    cases = json.loads(io.open(os.path.join(REPO, 'tools', 'eval', 'cases.json'),
                               encoding='utf-8').read())
    neg = json.loads(io.open(os.path.join(REPO, 'tools', 'eval', 'negatives.json'),
                             encoding='utf-8').read())
    neg_qs = [q for cat, qs in neg['categories'].items() for q in qs]
    print('真实库 %d 条 / 噪声池 %d 条 / 负样本 %d 条'
          % (len(real), len(noise), len(neg_qs)))
    print()
    print('  %-8s %-8s %-16s %-16s %-18s %s' % (
        '条数', '重复', '负样本误命中', 'recall', 'holdout', '平均返回'))
    print('  ' + '-' * 80)

    rows = []
    for n in POINTS:
        injs, recs, holds, rets = [], [], [], []
        for rep in range(REPEATS):
            rnd = random.Random(20261103 + rep * 7919 + n)
            pool = noise[:]
            rnd.shuffle(pool)
            mixed = [{'id': str(f.get('id') or 'r'), 'content': str(f.get('content') or ''),
                      'status': 'active', 'importance': f.get('importance', 3),
                      'updated_at': f.get('updated_at', '')} for f in real]
            for i, f in enumerate(pool[:n]):
                mixed.append({'id': 'n%05d' % i, 'content': f.get('content', ''),
                              'status': 'active', 'importance': f.get('importance', 3),
                              'updated_at': f.get('created_at', '')})

            def run(q):
                return me.search_memory_for_injection(mixed, q, top_k=3)

            inj = sum(1 for q in neg_qs if run(q))
            r_ok = h_ok = tot_ret = 0
            for c in cases['recall']:
                h = run(c['query'])
                tot_ret += len(h)
                if any(n2 in ' '.join(str(x.get('text') or x.get('content') or '') for x in h)
                       for n2 in c['expect_any']):
                    r_ok += 1
            for c in cases['holdout']:
                h = run(c['query'])
                tot_ret += len(h)
                if any(n2 in ' '.join(str(x.get('text') or x.get('content') or '') for x in h)
                       for n2 in c['expect_any']):
                    h_ok += 1
            injs.append(inj)
            recs.append(r_ok)
            holds.append(h_ok)
            rets.append(tot_ret / 18.0)

        avg_inj = sum(injs) / len(injs)
        span = '%d~%d' % (min(injs), max(injs)) if min(injs) != max(injs) else '%d' % injs[0]
        print('  %-8d %-8s %-16s %-16s %-18s %.2f' % (
            n, '%d次' % REPEATS,
            '%.1f/42 (%s)' % (avg_inj, span),
            '%.1f/6' % (sum(recs) / len(recs)),
            '%.1f/12' % (sum(holds) / len(holds)),
            sum(rets) / len(rets)))
        rows.append({'noise': n, 'total': len(real) + n,
                     'neg_inject_mean': round(avg_inj, 2),
                     'neg_inject_range': [min(injs), max(injs)],
                     'recall_mean': round(sum(recs) / len(recs), 2),
                     'holdout_mean': round(sum(holds) / len(holds), 2),
                     'avg_returned': round(sum(rets) / len(rets), 2)})

    p = os.path.join(OUT, 'density_curve.json')
    io.open(p, 'w', encoding='utf-8', newline='\n').write(json.dumps({
        'note': '每个点 %d 次独立随机噪声，取均值并记录极差' % REPEATS,
        'real_facts': len(real), 'rows': rows}, ensure_ascii=False, indent=2) + '\n')
    print()
    print('  已写 %s' % p)
    base = rows[0]['neg_inject_mean']
    print()
    print('  相对 21 条的倍数：')
    for r in rows:
        mult = r['neg_inject_mean'] / base if base else 0
        flag = ' ★产品上限' if r['noise'] == 200 else ''
        print('     %-5d 条  %.1f/42  = %.1f×%s' % (
            r['total'], r['neg_inject_mean'], mult, flag))
    return 0


if __name__ == '__main__':
    sys.exit(main())
