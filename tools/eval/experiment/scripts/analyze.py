# -*- coding: utf-8 -*-
"""1200 条记忆实验：分析（2026-11-03）

## 这个脚本回答四个问题

| # | 问题 | 为什么重要 |
|---|---|---|
| ① | 稠密语料下检索还成不成？ | 现在闸门 0.30 是按 21 条 facts 调的，1200 条会不会全崩 |
| ② | 两种衰减模型在真实年龄分布上差多少？ | 这是「幂律 vs 指数」唯一能做的定量比较 |
| ③ | 星图的关键词分类在 1200 条上还站得住吗？ | 分类是硬编码关键词，规模一大可能全挤在几类 |
| ④ | 淘汰机制跑起来会怎么表现？ | `MAX_MEMORIES=200`，1200 条必触发，这是它第一次真跑 |

## ⚠ 必须写进结论的限制

- 这是**合成数据**，不是真人使用记录
- 时间轴是**回填**的，不是真实流逝
- 所以能答「模型之间有没有差别」「规模上去会不会崩」，
  **不能**答「人真正怎么忘」「哪个模型更对」
"""
import datetime
import io
import json
import os
import sys
from collections import Counter

REPO = r'D:\ai工作站\desktop-pet'
OUT = r'D:\AutoClawworkspace\mem-exp-20261103'
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import memory_engine as me  # noqa: E402
import memory_events as mev  # noqa: E402
import memory_starmap as msm  # noqa: E402

EXP = os.path.join(OUT, 'experiment.json')


def load():
    d = json.loads(io.open(EXP, encoding='utf-8').read())
    facts = d['facts']
    # 转成 memory_engine 认的形状
    for i, f in enumerate(facts):
        f.setdefault('id', 'x%04d' % i)
        f.setdefault('status', 'active')
        f.setdefault('updated_at', f.get('created_at') or '')
    return d, facts


def q1_retrieval(facts):
    print('=' * 78)
    print('① 稠密语料下的检索：1200 条 vs 21 条')
    print('=' * 78)
    cases = json.loads(io.open(os.path.join(REPO, 'tools', 'eval', 'cases.json'),
                               encoding='utf-8').read())
    print('  闸门：MATCHED=%s COVERAGE=%s KEEP=%s'
          % (me.GATE_MIN_MATCHED, me.GATE_MIN_COVERAGE, me.GATE_KEEP_RATIO))
    print()
    print('  %-6s %-34s %-8s %s' % ('id', 'query', '命中', 'top1（前 40 字）'))
    print('  ' + '-' * 74)
    for grp in ('recall', 'holdout'):
        ok = 0
        for c in cases.get(grp, []):
            hits = me.search_memory_for_injection(facts, c['query'], top_k=3)
            texts = [str(h.get('text') or '') for h in hits]
            joined = ' '.join(texts)
            hit = any(n in joined for n in c['expect_any'])
            ok += 1 if hit else 0
            print('  %-6s %-34s %-8s %s' % (
                c['id'], c['query'][:32], '✓' if hit else '✗',
                (texts[0][:38] if texts else '（空）')))
        print('  %s: %d/%d = %.0f%%' % (grp, ok, len(cases[grp]),
                                         ok / max(len(cases[grp]), 1) * 100))
        print()
    # 噪声：1200 条下会不会更容易误命中
    neg = json.loads(io.open(os.path.join(REPO, 'tools', 'eval', 'negatives.json'),
                             encoding='utf-8').read())
    n_inj = 0
    tot = 0
    for cat, qs in neg['categories'].items():
        for q in qs:
            tot += 1
            if me.search_memory_for_injection(facts, q, top_k=3):
                n_inj += 1
    print('  负样本（%d 条）有注入：%d 条  %.1f%%' % (tot, n_inj, n_inj / max(tot, 1) * 100))
    print('  （21 条库时是 2/42 = 4.8% —— 语料变密后误命中率的变化是关键）')
    return {'neg_inject': n_inj, 'neg_total': tot}


def q2_decay(facts):
    print()
    print('=' * 78)
    print('② 两种衰减模型在真实年龄分布上的差别')
    print('=' * 78)
    buckets = [(0, 7), (7, 30), (30, 90), (90, 180), (180, 365), (365, 545), (545, 99999)]
    print('  %-12s %-6s %-10s %-10s %-10s %s' % ('年龄段', '条数', '指数均值', '幂律均值', '差', '幂律/指数'))
    print('  ' + '-' * 76)
    rows = []
    for lo, hi in buckets:
        group = [f for f in facts if lo <= (f.get('age_days') or 0) < hi]
        if not group:
            continue
        mev.DECAY_MODEL = 'exponential'
        ex = [mev.decayed_weight(f.get('importance', 3) / 5.0, f['age_days']) for f in group]
        mev.DECAY_MODEL = 'power'
        pw = [mev.decayed_weight(f.get('importance', 3) / 5.0, f['age_days']) for f in group]
        a, b = sum(ex) / len(ex), sum(pw) / len(pw)
        ratio = ('%.1f×' % (b / a)) if a > 1e-9 else '∞'
        rows.append((lo, hi, len(group), a, b))
        print('  %-12s %-6d %-10.5f %-10.5f %-10.5f %s' % (
            '%d-%d天' % (lo, hi), len(group), a, b, b - a, ratio))
    mev.DECAY_MODEL = 'power'

    # 排序分歧：把两种模型各自排序，看前 20 名有多少不同
    mev.DECAY_MODEL = 'exponential'
    rank_ex = [i for i, _ in sorted(
        enumerate(facts), key=lambda p: -mev.decayed_weight(
            p[1].get('importance', 3) / 5.0, p[1]['age_days']))][:20]
    mev.DECAY_MODEL = 'power'
    rank_pw = [i for i, _ in sorted(
        enumerate(facts), key=lambda p: -mev.decayed_weight(
            p[1].get('importance', 3) / 5.0, p[1]['age_days']))][:20]
    mev.DECAY_MODEL = 'power'
    overlap = len(set(rank_ex) & set(rank_pw))
    print()
    print('  两种模型各自「权重最高的前 20 条」重合：%d/20' % overlap)
    print('  ⇒ 重合越少，说明换模型真的会改变「哪些记忆更靠前」')
    return {'overlap_top20': overlap, 'rows': rows}


def q3_starmap(facts):
    print()
    print('=' * 78)
    print('③ 星图分类在 1200 条上的分布（关键词表还站得住吗）')
    print('=' * 78)
    c = Counter()
    for f in facts:
        c[msm._classify(f.get('content', ''), 'active', 'fact')] += 1
    total = sum(c.values())
    cn = getattr(msm, 'CN', {})
    for k, v in c.most_common():
        print('  %-8s %-14s %5d  %5.1f%%  %s' % (
            k, cn.get(k, ''), v, v / max(total, 1) * 100, '#' * int(v / max(total, 1) * 50)))
    print()
    top1 = c.most_common(1)[0]
    print('  最大类占 %.0f%%（%s）' % (top1[1] / max(total, 1) * 100, top1[0]))
    if top1[1] / max(total, 1) > 0.5:
        print('  ★ 单类超过 50%% —— 关键词表在稠密语料下失真，星图会挤成一团')
    else:
        print('  分布尚可，但需人工看几类是否语义合理')
    return dict(c)


def q4_eviction(facts):
    print()
    print('=' * 78)
    print('④ 淘汰机制第一次真跑（MAX_MEMORIES=%d，当前 %d 条）'
          % (mev.MAX_MEMORIES, len(facts)))
    print('=' * 78)
    if len(facts) <= mev.MAX_MEMORIES:
        print('  当前条数未超上限，淘汰不会触发')
        print('  （若实验产出 >200 条，这里会看到真实淘汰记录）')
        return
    import tempfile
    tmp = tempfile.mkdtemp(prefix='evict_exp_')
    m = mev.MemoryEvents(os.path.join(tmp, 'memories.json'))
    # 逐条塞进去，让产品自己的淘汰逻辑跑
    for f in facts:
        m.add('flash', 'event', f.get('content', '')[:80], f.get('content', ''),
              origin='user')
    alive = len(m.all())
    rows = m.evicted_recent(5000)
    print('  塞入 %d 条 → 存活 %d 条（上限 %d）' % (len(facts), alive, mev.MAX_MEMORIES))
    print('  台账记录 %d 条' % len(rows))
    if rows:
        import hashlib
        print()
        print('  台账字段完整性：')
        keys = set(rows[0].keys())
        for k in ('t', 'reason', 'id', 'content_hash', 'committed', 'v', 'kept'):
            print('     %-14s %s' % (k, '有' if k in keys else '★缺'))
        print('  committed 全为 True：%s' % all(r.get('committed') for r in rows))
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


def main():
    d, facts = load()
    print('实验数据：facts %d / events %d' % (len(d['facts']), len(d['events'])))
    print('时间跨度：%s ~ %s' % (
        min(f.get('created_at', '') for f in facts),
        max(f.get('created_at', '') for f in facts)))
    print()
    r1 = q1_retrieval(facts)
    r2 = q2_decay(facts)
    r3 = q3_starmap(facts)
    q4_eviction(facts)

    print()
    print('=' * 78)
    print('限制（必须写进任何对外结论）')
    print('=' * 78)
    print('  · 合成数据，非真人使用记录')
    print('  · 时间轴是回填的，非真实流逝')
    print('  · 能答「模型间有无差别」「规模上去会不会崩」')
    print('  · 不能答「人真正怎么忘」「哪个模型更对」')

    p = os.path.join(OUT, 'analysis.json')
    io.open(p, 'w', encoding='utf-8', newline='\n').write(json.dumps({
        'generated': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
        'n_facts': len(facts), 'n_events': len(d['events']),
        'retrieval': r1, 'decay': r2, 'starmap': r3,
    }, ensure_ascii=False, indent=2, default=str) + '\n')
    print()
    print('  已写 %s' % p)
    return 0


if __name__ == '__main__':
    sys.exit(main())
