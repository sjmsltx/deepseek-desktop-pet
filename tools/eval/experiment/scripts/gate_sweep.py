# -*- coding: utf-8 -*-
"""闸门阈值扫描：产品真实容量（200 条）下的 precision/recall 权衡（2026-11-03）

## 为什么这是最重要的一张表

前面查清了三件事：
1. 召回**不随**语料变密而下降（恒定 2/6）—— 之前「稠密语料让检索崩了」的判断是错的
2. 误命中率**随**语料变密上升（21 条 2/42 → 300 条 11/42）
3. `r01「我叫什么名字？」` 的真答案**排名第 1**，却被闸门挡掉 ⇒ **召回低的直接原因是闸门，不是检索**

所以闸门松紧是唯一可调的总开关。这张表把「松一档，换来多少召回、付出多少误报」摆出来。

## 判据（不能只看一边）

- 只看召回 → 全放开最优（召回 100%，误命中 100%，无意义）
- 只看误报 → 全关掉最优（误命中 0%，召回 0%，也没意义）
- 真实可感知性：**误命中比漏召回更伤**——用户会看到「它说起我根本没说的事」，
  而漏召回只表现为「它没想起来」，后者用户常归因于自己没说过

## 采样

容量固定 200 条（产品上限），噪声用 5 个不同随机种子重复，取均值与极差。
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

CAP = 200
REPEATS = 5

# (min_matched, min_coverage, keep_ratio) 候选组合
COMBOS = [
    (2, 0.30, 0.25),   # 现状
    (2, 0.25, 0.25),
    (2, 0.20, 0.25),
    (1, 0.40, 0.25),
    (1, 0.33, 0.25),
    (1, 0.30, 0.25),
    (1, 0.25, 0.25),
    (2, 0.00, 0.25),
    (1, 0.00, 0.25),
    (0, 0.00, 0.00),   # 全放开（对照上限）
]


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

    # 只用「期望词在真实库中存在」的用例：否则答案根本不在库里，
    # 测出来的是「模型会不会编」，不是「检索能不能找到」
    real_text = '\n'.join(str(f.get('content') or '') for f in real)
    usable = {g: [c for c in cases[g] if any(n in real_text for n in c['expect_any'])]
              for g in ('recall', 'holdout')}
    print('真实库 %d 条 / 噪声 %d 条 → 固定总容量 %d 条'
          % (len(real), CAP - len(real), CAP))
    print('可用用例：recall %d / holdout %d（期望词在真实库中存在的）'
          % (len(usable['recall']), len(usable['holdout'])))
    print()

    # 预构建 5 个不同随机种子的 200 条库
    libs = []
    for rep in range(REPEATS):
        rnd = random.Random(20261103 + rep * 104729)
        pool = noise[:]
        rnd.shuffle(pool)
        mixed = [{'id': str(f.get('id') or 'r'), 'content': str(f.get('content') or ''),
                  'status': 'active', 'importance': float(f.get('importance', 3) or 3),
                  'updated_at': f.get('updated_at', '')} for f in real]
        for i, f in enumerate(pool[:CAP - len(real)]):
            mixed.append({'id': 'n%05d' % i, 'content': f.get('content', ''),
                          'status': 'active', 'importance': float(f.get('importance', 3) or 3),
                          'updated_at': f.get('created_at', '')})
        libs.append(mixed)

    old = (me.GATE_MIN_MATCHED, me.GATE_MIN_COVERAGE, me.GATE_KEEP_RATIO)
    print('  %-24s %-14s %-14s %-18s %s' % ('闸门配置', 'recall', 'holdout', '负样本误命中', '平均返回'))
    print('  ' + '-' * 84)
    results = []
    for mm, mc, kr in COMBOS:
        me.GATE_MIN_MATCHED, me.GATE_MIN_COVERAGE, me.GATE_KEEP_RATIO = mm, mc, kr
        r_l, h_l, n_l, ret_l = [], [], [], []
        for mixed in libs:
            def run(q):
                return me.search_memory_for_injection(mixed, q, top_k=3)
            r_ok = sum(1 for c in usable['recall']
                       if any(n in ' '.join(str(x.get('text') or '') for x in run(c['query']))
                              for n in c['expect_any']))
            h_ok = sum(1 for c in usable['holdout']
                       if any(n in ' '.join(str(x.get('text') or '') for x in run(c['query']))
                              for n in c['expect_any']))
            inj = sum(1 for q in neg_qs if run(q))
            ret = sum(len(run(c['query'])) for c in usable['recall'] + usable['holdout']) \
                / max(len(usable['recall']) + len(usable['holdout']), 1)
            r_l.append(r_ok); h_l.append(h_ok); n_l.append(inj); ret_l.append(ret)
        avg = lambda x: sum(x) / len(x)  # noqa: E731
        tag = ' ← 现状' if (mm, mc, kr) == (2, 0.30, 0.25) else ''
        print('  %-24s %-14s %-14s %-18s %.2f%s' % (
            'm>=%d cov>=%.2f keep%.2f' % (mm, mc, kr),
            '%.1f/%d' % (avg(r_l), len(usable['recall'])),
            '%.1f/%d' % (avg(h_l), len(usable['holdout'])),
            '%.1f/%d (%.0f%%)  [%d~%d]' % (avg(n_l), len(neg_qs),
                                           avg(n_l) / len(neg_qs) * 100, min(n_l), max(n_l)),
            avg(ret_l), tag))
        results.append({'min_matched': mm, 'min_coverage': mc, 'keep_ratio': kr,
                        'recall': round(avg(r_l), 2), 'holdout': round(avg(h_l), 2),
                        'neg_inject': round(avg(n_l), 2),
                        'neg_inject_range': [min(n_l), max(n_l)],
                        'avg_returned': round(avg(ret_l), 2)})
    me.GATE_MIN_MATCHED, me.GATE_MIN_COVERAGE, me.GATE_KEEP_RATIO = old

    p = os.path.join(OUT, 'gate_sweep.json')
    io.open(p, 'w', encoding='utf-8', newline='\n').write(json.dumps({
        'note': '容量固定 %d 条（产品上限），%d 个随机种子重复' % (CAP, REPEATS),
        'n_recall': len(usable['recall']), 'n_holdout': len(usable['holdout']),
        'n_neg': len(neg_qs), 'rows': results}, ensure_ascii=False, indent=2) + '\n')
    print()
    print('  已写 %s' % p)
    return 0


if __name__ == '__main__':
    sys.exit(main())
