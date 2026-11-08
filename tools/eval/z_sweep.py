# -*- coding: utf-8 -*-
"""z 门槛在临界库规模上的行为（2026-11-08）

## 要回答的问题

2026-11-08 清理试跑发现：库从 18 条减到 15 条，h06/h08 的答案条目都在、余弦几乎没变，
但 z 从 2.62→2.38、2.66→2.47，掉到门槛 2.50 以下 ⇒ 召回掉了。
**说明 z 判据在当前库规模上处在临界带。**

本脚本量化三件事：

1. **临界带有多宽**：每条用例的答案条目，其 z 落在哪个区间（离门槛多远）
2. **门槛移动的影响**：固定库、扫 z 门槛，选参集与验收集各自怎么变
3. **库规模移动的影响**：同一门槛下，删掉几条记忆（模拟清理）会让多少用例翻面

## 纪律（这两条不遵守结果就没意义）

- **选参只用 `cases.json.tuning`**（8 条，覆盖 holdout 未涉及的记忆条目）
- **`holdout` 只在最后验收时跑一次**，不参与任何选择
- 报结果必须两者分开写，不许混成一个数

## 用法

    python tools/eval/z_sweep.py                 # 全表
    python tools/eval/z_sweep.py --sizes 15,18   # 只看指定库规模
"""
import argparse
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import memory_embed as mb        # noqa: E402
import memory_engine as me       # noqa: E402

EV = os.path.join(ROOT, 'tools', 'eval')

#: 不该被注入的问句（用来确认「降门槛不会把噪声放进来」）
OFF_TOPIC = ['今天天气怎么样', '帮我写个快速排序', '重庆到成都高铁多久', '推荐一部科幻电影',
             '怎么配置 nginx 反向代理', '1 加 1 等于几', '帮我查一下明天重庆的天气',
             '解释一下什么是光合作用', '这个月花了多少钱', '给我讲个笑话',
             'docker 容器怎么重启', '我的电脑连不上 wifi', 'Excel 怎么做透视表',
             '把这段话翻译成英文：今天很好', '现在几点了', '推荐几个学英语的方法']


def load_cases():
    d = json.load(io.open(os.path.join(EV, 'cases.json'), encoding='utf-8'))
    neg = json.load(io.open(os.path.join(EV, 'negatives.json'), encoding='utf-8'))
    negatives = []
    for _cat, lst in neg.get('categories', {}).items():
        for q in (lst if isinstance(lst, list) else []):
            t = q.get('query') if isinstance(q, dict) else str(q)
            if t:
                negatives.append(t)
    return d, negatives


def load_facts(path=None):
    p = path or os.path.join(ROOT, 'memory.json')
    d = json.load(io.open(p, encoding='utf-8'))
    return [f for f in d.get('facts', []) if f.get('status') == 'active']


def hit_one(facts, case):
    got = me.search_memory_for_injection(facts, case['query'], top_k=3)
    if not got:
        return False
    joined = ' '.join(str(g.get('content', g.get('text', ''))) for g in got)
    return any(x in joined for x in case.get('expect_any', []))


def evaluate(facts, cases):
    return sum(1 for c in cases if hit_one(facts, c)), len(cases)


def answer_z(facts, case, embedder):
    """答案条目在本库分布里的 z 与余弦（不论是否真注入）"""
    import numpy as np
    texts = [str(f.get('content') or '') for f in facts]
    mat = embedder.encode(texts)
    sims = embedder.score(case['query'], mat)
    mu, sd = float(sims.mean()), float(sims.std()) or 1e-6
    idx = None
    for i, t in enumerate(texts):
        if any(e in t for e in case.get('expect_any', [])):
            idx = i
            break
    if idx is None:
        return None
    order = np.argsort(-sims)
    return {'z': (float(sims[idx]) - mu) / sd, 'cos': float(sims[idx]),
            'rank': list(order).index(idx) + 1,
            'top1_cos': float(sims[int(order[0])])}


def main(argv=None):
    ap = argparse.ArgumentParser(description='z 门槛临界带扫描')
    ap.add_argument('--sizes', default='',
                    help='逗号分隔的库规模（默认只用真实库；给数字则按顺序截取前 N 条）')
    args = ap.parse_args(argv)

    cases, negatives = load_cases()
    tuning = cases.get('tuning', [])
    holdout = cases.get('holdout', [])
    if not tuning:
        raise SystemExit('cases.json 里没有 tuning 段，先补调参集')

    facts = load_facts()
    emb = mb.get_embedder()
    if not emb.ok:
        raise SystemExit('向量模型不可用：%s' % (emb.reason or '未知'))

    print('库：%d 条 active' % len(facts))
    print('调参集 tuning：%d 条（只用于选参）' % len(tuning))
    print('验收集 holdout：%d 条（只在最后跑一次）' % len(holdout))
    print()

    # ---------- ① 临界带：每条用例的答案 z 离门槛多远 ----------
    print('=' * 96)
    print('① 临界带（当前库 %d 条，门槛 = %.2f）' % (len(facts), mb.adaptive_z_threshold(len(facts))))
    print('=' * 96)
    zmin = mb.adaptive_z_threshold(len(facts))
    print('%-6s %-24s %7s %7s %6s %8s %s' % ('id', '问句', '答案z', '余弦', '名次', '距门槛', '判定'))
    band = []
    for c in tuning + holdout:
        r = answer_z(facts, c, emb)
        if r is None:
            print('%-6s %-24s   （库里找不到期望内容）' % (c['id'], c['query'][:22]))
            continue
        gap = r['z'] - zmin
        mark = '过' if gap >= 0 else '否'
        if abs(gap) <= 0.5:
            band.append((c['id'], gap))
        print('%-6s %-24s %7.2f %7.3f %6d %8.2f %s'
              % (c['id'], c['query'][:22], r['z'], r['cos'], r['rank'], gap, mark))
    print()
    print('⇒ 距门槛 |Δz| ≤ 0.5 的用例：%d 条 %s'
          % (len(band), [b[0] for b in band]))
    print('   这些就是「库规模一动就翻面」的临界用例。')

    # ---------- ② 门槛移动：tuning 选参，holdout 验收 ----------
    print()
    print('=' * 96)
    print('② 门槛扫描（固定库 %d 条）—— 左半选参、右半验收' % len(facts))
    print('=' * 96)
    orig = mb.adaptive_z_threshold
    print('%-8s %-12s %-12s %-12s %-10s' % ('z门槛', 'tuning(选参)', 'holdout(验收)', '无关/16', '负样本/42'))
    rows = []
    try:
        for zt in [1.6, 1.8, 2.0, 2.2, 2.4, 2.5, 2.6, 2.8, 3.0]:
            mb.adaptive_z_threshold = lambda n, _z=zt: float(_z)
            th, tn = evaluate(facts, tuning)
            hh, hn = evaluate(facts, holdout)
            of = sum(1 for q in OFF_TOPIC if me.search_memory_for_injection(facts, q, top_k=3))
            ng = sum(1 for q in negatives if me.search_memory_for_injection(facts, q, top_k=3))
            rows.append((zt, th, tn, hh, hn, of, ng))
            star = ' ← 现值' if abs(zt - 2.5) < 1e-9 else ''
            print('%-8.1f %-12s %-12s %-12s %-10s%s'
                  % (zt, '%d/%d' % (th, tn), '%d/%d' % (hh, hn), '%d/16' % of, '%d/42' % ng, star))
    finally:
        mb.adaptive_z_threshold = orig

    # 选参：只看 tuning + 噪声约束
    best = None
    for zt, th, tn, hh, hn, of, ng in rows:
        # 选参判据：tuning 最高；并列时取噪声最少的；再并列取门槛最高（保守）
        key = (th, -of, -ng, zt)
        if best is None or key > best[0]:
            best = (key, zt, th, tn, hh, hn, of, ng)
    _, zt_b, th_b, tn_b, hh_b, hn_b, of_b, ng_b = best
    print()
    print('按「tuning 命中最多、噪声最少、门槛最保守」选出的门槛：%.1f' % zt_b)
    print('  该门槛下 tuning %d/%d、holdout %d/%d（验收，非选参）、无关 %d/16、负样本 %d/42'
          % (th_b, tn_b, hh_b, hn_b, of_b, ng_b))
    print('  当前生产值 2.5 下：tuning %s、holdout %s'
          % (next(('%d/%d' % (r[1], r[2])) for r in rows if abs(r[0] - 2.5) < 1e-9),
             next(('%d/%d' % (r[3], r[4])) for r in rows if abs(r[0] - 2.5) < 1e-9)))

    # ---------- ③ 库规模移动的影响 ----------
    if args.sizes:
        print()
        print('=' * 96)
        print('③ 库规模移动的影响（门槛固定 2.5，按原顺序截取前 N 条）')
        print('=' * 96)
        mb.adaptive_z_threshold = lambda n: 2.5
        try:
            print('%-8s %-12s %-12s' % ('库条数', 'tuning', 'holdout'))
            for s in [int(x) for x in args.sizes.split(',') if x.strip()]:
                sub = facts[:s]
                th, tn = evaluate(sub, tuning)
                hh, hn = evaluate(sub, holdout)
                print('%-8d %-12s %-12s' % (s, '%d/%d' % (th, tn), '%d/%d' % (hh, hn)))
        finally:
            mb.adaptive_z_threshold = orig
        print()
        print('⚠ 这个扫描只是「截取前 N 条」的粗略模拟，不是真实清理（清理会按内容挑，不是按顺序）。')
        print('   它的用途是说明「同一门槛在相邻库规模上结论会翻」，不能当作清理效果预测。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
