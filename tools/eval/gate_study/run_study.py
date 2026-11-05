# -*- coding: utf-8 -*-
"""闸门调参的完整实验（可复跑）—— 2026-11-03 落盘

## 为什么有这个文件

评审-173 §六 第 2 问 + 评审-174 §三 两次追问「数据集在哪」。
我 321 说「脚本可复跑」，但那批脚本存在临时目录里、被我清理时清进了回收站
⇒ 那句话是假的。

现在：**数据在 `tools/eval/negatives.json` / `realdist.json`，实验在本文件。**
两者都在仓库里，任何人可复跑出 评审-321 里那几张表。

## 复跑

    python tools\\eval\\gate_study\\run_study.py            # 全跑（约 20 秒）
    python tools\\eval\\gate_study\\run_study.py --quick    # 只跑关键档位

## 五轮（与 评审-321 对应）

| 轮 | 做什么 | 结论 |
|---|---|---|
| ① | 完整网格 | 开发/留出差距在所有档位 >40 点；闸门全关留出集也只有 42% |
| ② | 0.20~0.34 精扫 + 契约约束 | 只有 0.26~0.32 同时满足「零纯噪声 + 概念提问挡住 + 强查询不死」 |
| ③ | 真实对话注入率 | 0.11~0.20 全 31.1%，0.34 是 26.7% |
| ④ | 42 条负样本逐条判「纯噪声 vs 相关」 | 0.28 零纯噪声；0.11 有 3 条纯噪声 |
| ⑤ | 结论区间 | 取平台中间 0.28 |
"""
import argparse
import io
import json
import os
import sys

# 本文件在 tools/eval/gate_study/ 下 ⇒ 向上 4 层才是仓库根
BASE = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import memory_engine as me  # noqa: E402

EVAL = os.path.join(BASE, 'tools', 'eval')
FACTS = json.loads(io.open(os.path.join(BASE, 'memory.json'), encoding='utf-8').read())['facts']

#: 既有契约里的两条概念提问（test_memory_gate.py 的 docstring 原文举例）
CONTRACT_FACTS = [
    {'id': 'f1', 'content': '用户的考研目标是某大学地图学与地理信息系统 数学二 复习计划',
     'importance': 5, 'status': 'active'},
    {'id': 'f2', 'content': '用户喜欢在桌宠里玩扫雷和 Farkle 骰子', 'importance': 3, 'status': 'active'},
]
CONTRACT_QUERIES = ['扫雷是什么', '介绍一下骰子']
CONTRACT_STRONG = '考研数学二复习计划怎么安排'


def load_cases():
    return json.loads(io.open(os.path.join(EVAL, 'cases.json'), encoding='utf-8').read())


def load_negatives():
    return json.loads(io.open(os.path.join(EVAL, 'negatives.json'), encoding='utf-8').read())


def load_realdist():
    return json.loads(io.open(os.path.join(EVAL, 'realdist.json'), encoding='utf-8').read())


def hit_any(texts, needles):
    return any(any(n in t for n in needles) for t in texts)


def query(cov, q, facts=None, top_k=3, matched=2):
    old = (me.GATE_MIN_MATCHED, me.GATE_MIN_COVERAGE, me.GATE_KEEP_RATIO)
    me.GATE_MIN_MATCHED, me.GATE_MIN_COVERAGE, me.GATE_KEEP_RATIO = matched, cov, 0.25
    try:
        return [str(h.get('text') or '') for h in
                me.search_memory_for_injection(facts or FACTS, q, top_k=top_k)]
    finally:
        me.GATE_MIN_MATCHED, me.GATE_MIN_COVERAGE, me.GATE_KEEP_RATIO = old


def recall_rate(cov, cases, facts=None, matched=2):
    """返回 (r1, r3, misses)"""
    r1 = r3 = 0
    misses = []
    for c in cases:
        texts = query(cov, c['query'], facts, matched=matched)
        if texts and hit_any([texts[0]], c['expect_any']):
            r1 += 1
        if hit_any(texts[:3], c['expect_any']):
            r3 += 1
        else:
            misses.append(c['id'])
    n = max(len(cases), 1)
    return r1 / n, r3 / n, misses


def leak_stats(cov):
    """返回 (纯噪声注入数, 总注入行数, 有注入的问句数)"""
    neg = load_negatives()
    pure = 0
    total_rows = 0
    injected_queries = 0
    for _cat, qs in neg['categories'].items():
        for q in qs:
            texts = query(cov, q)
            if texts:
                injected_queries += 1
                total_rows += len(texts)
    for c in neg.get('pure_noise_cases', []):
        if not c.get('must_not_hit'):
            continue
        if hit_any(query(cov, c['query']), c['must_not_hit']):
            pure += 1
    return pure, total_rows, injected_queries


def contract_ok(cov):
    """概念提问必须被挡住；强查询不能被闸死"""
    blocked = all(len(query(cov, q, CONTRACT_FACTS)) == 0 for q in CONTRACT_QUERIES)
    strong = len(query(cov, CONTRACT_STRONG, CONTRACT_FACTS)) > 0
    return blocked, strong


def realdist_inject_rate(cov):
    msgs = load_realdist()['messages']
    n_inj = 0
    for m in msgs:
        if query(cov, m['text']):
            n_inj += 1
    return n_inj / max(len(msgs), 1), n_inj, len(msgs)


def line(c='-', n=100):
    print(c * n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true')
    a = ap.parse_args()

    cases = load_cases()
    dev, hold = cases['recall'], cases['holdout']
    neg = load_negatives()
    print('数据：开发集 %d 条 / 留出集 %d 条 / 负样本 %d 条 / 真实对话 %d 条' % (
        len(dev), len(hold), neg['total'], load_realdist()['count']))
    print('当前闸门：MATCHED=%s COVERAGE=%s KEEP=%s' % (
        me.GATE_MIN_MATCHED, me.GATE_MIN_COVERAGE, me.GATE_KEEP_RATIO))

    # ═════════ ① 完整网格 ═════════
    print()
    line('=')
    print('① 完整网格（matched × coverage）—— 看开发/留出差距')
    line('=')
    print('%-16s %-8s %-8s %-8s %-8s' % ('(matched,cov)', 'devR@3', 'holdR@3', '差距', '纯噪声'))
    line()
    grid_m = [0, 1, 2, 3] if not a.quick else [0, 2]
    grid_c = [0.0, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.28, 0.34] if not a.quick \
        else [0.0, 0.10, 0.20, 0.34]
    for mm in grid_m:
        for c in grid_c:
            _, d3, _ = recall_rate(c, dev, matched=mm)
            _, h3, _ = recall_rate(c, hold, matched=mm)
            old = (me.GATE_MIN_MATCHED, me.GATE_MIN_COVERAGE, me.GATE_KEEP_RATIO)
            me.GATE_MIN_MATCHED = mm
            pure, _, _ = leak_stats(c)
            me.GATE_MIN_MATCHED, me.GATE_MIN_COVERAGE, me.GATE_KEEP_RATIO = old
            mk = '  ← 当前' if (mm, c) == (me.GATE_MIN_MATCHED, me.GATE_MIN_COVERAGE) else ''
            print('%-16s %-8.0f %-8.0f %-8.0f %-8d%s' % (
                '(%d,%.2f)' % (mm, c), d3 * 100, h3 * 100, (d3 - h3) * 100, pure, mk))

    # ═════════ ② 精扫 + 契约 ═════════
    print()
    line('=')
    print('② 0.20~0.34 精扫 + 契约约束（matched 固定 2）')
    line('=')
    print('%-8s %-8s %-8s %-8s %-9s %-8s %s' % (
        'cov', 'devR@3', 'holdR@3', '纯噪声', '扫雷挡住', '强查询', '判定'))
    line()
    fine = [0.20, 0.22, 0.24, 0.25, 0.26, 0.28, 0.30, 0.32, 0.34]
    results = {}
    for c in fine:
        _, d3, _ = recall_rate(c, dev)
        _, h3, _ = recall_rate(c, hold)
        pure, _, _ = leak_stats(c)
        blocked, strong = contract_ok(c)
        ok = blocked and strong and pure == 0
        results[c] = (d3, h3, pure, blocked, strong, ok)
        mk = '  ← 当前' if abs(c - me.GATE_MIN_COVERAGE) < 1e-9 else ''
        print('%-8s %-8.0f %-8.0f %-8d %-9s %-8s %s%s' % (
            c, d3 * 100, h3 * 100, pure, '是' if blocked else '★否',
            '是' if strong else '★否', '✓ 合格' if ok else '✗', mk))

    # ═════════ ③ 真实对话 ═════════
    print()
    line('=')
    print('③ 真实对话（%d 条 user 消息）注入率' % load_realdist()['count'])
    line('=')
    print('%-8s %-10s %-12s' % ('cov', '注入率', '注入条数'))
    line()
    for c in ([0.11, 0.15, 0.20, 0.28, 0.34] if not a.quick else [0.11, 0.28, 0.34]):
        r, n, tot = realdist_inject_rate(c)
        mk = '  ← 当前' if abs(c - me.GATE_MIN_COVERAGE) < 1e-9 else ''
        print('%-8s %-10s %-12s%s' % (c, '%.1f%%' % (r * 100), '%d/%d' % (n, tot), mk))

    # ═════════ ④ 结论 ═════════
    print()
    line('=')
    print('④ 结论：满足「零纯噪声 + 概念提问挡住 + 强查询不死」的区间')
    line('=')
    good = [(c, v[1]) for c, v in sorted(results.items()) if v[5]]
    if good:
        print('  合格档位：%s' % ', '.join('%s(holdR@3=%.0f%%)' % (c, h * 100) for c, h in good))
        # ⚠ 合格 ≠ 最优：0.34 也合格（概念提问挡得住），但它的 holdR@3 是 17%
        #   ⇒ 平台必须取「合格 且 holdR@3 最高」的那一段，否则会把更差的档算进中间。
        best = max(h for _c, h in good)
        plat = [c for c, h in good if abs(h - best) < 1e-9]
        print('  合格里 holdR@3 最高（%.0f%%）的档位：%s' % (best * 100, plat))
        print('  ⇒ 平台区间 %s ~ %s，取中间 %s'
              % (plat[0], plat[-1], plat[len(plat) // 2]))
        print('  ⛔ 0.34 虽合格但 holdR@3 只有 %.0f%% —— 它不在平台上，别把「合格」当「最优」'
              % (results[0.34][1] * 100 if 0.34 in results else 0))
    else:
        print('  ⚠ 没有档位同时满足全部约束')

    print()
    print('⚠ holdR@3 里含 L0 常驻块的功劳。纯检索口径：python tools\\eval_memory.py（看 H_R@3_pure）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
