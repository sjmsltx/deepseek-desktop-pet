# -*- coding: utf-8 -*-
"""build_edges 优化的分步测速（2026-11-03）

## 三个候选瓶颈，先量再改

| 瓶颈 | 机制 | 预估 |
|---|---|---|
| A 强边重复 tokenize | 每次 jaccard 都重算两段 terms()，995k 配对 × 2 | 大 |
| B 强边全配对 | 共享 0 词的配对 jaccard 恒为 0，算了也白算 | 中 |
| C 弱边 Prim | 1 维距离用 O(V²) 朴素 Prim，累计 O(V³) | 大 |

## 本脚本只测，不改产品代码

对 1411 条实测每个阶段耗时，确认改哪里最值。
"""
import io
import json
import os
import sys
import time

import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
OUT = _os.path.dirname(_HERE)                  # 本实验目录（data/ 与 results/ 的父目录）
DATA = _os.path.join(OUT, 'data')              # 只读：语料 / 时间轴 / 1411 条记忆
RESULTS = _os.path.join(OUT, 'results')        # 只写：各脚本的分析结果
REPO = _os.path.dirname(_os.path.dirname(_os.path.dirname(OUT)))  # 仓库根（上溯 3 层）
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import memory_starmap as msm  # noqa: E402


def load_real_stars(n_noise):
    """用实验数据当星点源（与 products 的 load_stars 输出同形状）"""
    src = json.loads(io.open(os.path.join(DATA, 'memories-1411.json'), encoding='utf-8').read())
    real = [f for f in json.loads(io.open(os.path.join(REPO, 'memory.json'),
                                         encoding='utf-8').read())['facts']
            if f.get('status') == 'active']
    stars = []
    for f in real:
        stars.append({'text': str(f.get('content') or ''), 'imp': f.get('importance', 3),
                      'age': 5.0, 'kind': 'fact', 'cat': msm._classify(str(f.get('content') or ''),
                                                                      'active', 'fact'),
                      'detail': '', 'time': '', 'key': 'f:%s' % f.get('id')})
    for i, f in enumerate(src['facts'][:n_noise]):
        stars.append({'text': f.get('content', ''), 'imp': f.get('importance', 3),
                      'age': float(f.get('age_days') or 1.0), 'kind': 'fact',
                      'cat': msm._classify(f.get('content', ''), 'active', 'fact'),
                      'detail': '', 'time': f.get('created_at', ''), 'key': 'n:%d' % i})
    return stars


def main():
    print('=' * 76)
    print('分阶段测速（1411 条）')
    print('=' * 76)
    stars = load_real_stars(1390)
    n = len(stars)
    print('  星点 %d' % n)

    # --- 阶段 0：terms 全量预计算
    t0 = time.time()
    term_sets = [msm.terms(s.get('text', '')) for s in stars]
    t_terms = time.time() - t0
    print('  ① terms() 全量一次：%.2f s（平均每篇 %.2f ms）'
          % (t_terms, t_terms / n * 1000))

    # --- 阶段 1：全配对 jaccard（= 现状做法，但复用已算好的 terms）
    #   用来分离「tokenize 开销」与「配对开销」
    t0 = time.time()
    pairs = 0
    thr = msm.STRONG_EDGE_JACCARD
    for i in range(n):
        ta = term_sets[i]
        if not ta:
            continue
        for j in range(i + 1, n):
            tb = term_sets[j]
            if not tb:
                continue
            pairs += 1
            if len(ta & tb) / float(len(ta | tb)) >= thr:
                pass          # 只计数，不存 —— 测纯计算时间
    t_allpairs = time.time() - t0
    print('  ② 全配对（terms 已缓存）：%.2f s / %d 对 = %.2f µs/对'
          % (t_allpairs, pairs, t_allpairs / max(pairs, 1) * 1e6))

    # --- 阶段 2：倒排索引，只算「共享至少 1 词」的配对
    t0 = time.time()
    inv = {}
    for i, ts in enumerate(term_sets):
        for w in ts:
            inv.setdefault(w, []).append(i)
    t_inv = time.time() - t0
    shared = {}
    t0 = time.time()
    cnt_pairs = 0
    for w, docs in inv.items():
        m = len(docs)
        if m < 2:
            continue
        for a in range(m):
            ia = docs[a]
            for b in range(a + 1, m):
                ib = docs[b]
                k = (ia, ib) if ia < ib else (ib, ia)
                shared[k] = shared.get(k, 0) + 1
                cnt_pairs += 1
    t_invcount = time.time() - t0
    print('  ③ 建倒排：%.2f s（%d 个词）' % (t_inv, len(inv)))
    print('     倒排计数：%.2f s / %d 次累加（提出 %d 个候选对）'
          % (t_invcount, cnt_pairs, len(shared)))
    print('     ⇒ 候选对占全配对 %.1f%%（其余共享 0 词，jaccard 恒 0）'
          % (100.0 * len(shared) / max(n * (n - 1) / 2, 1)))

    # --- 阶段 3：弱边 Prim 现状（O(n³)）
    by_cat = {}
    for idx, s in enumerate(stars):
        by_cat.setdefault(s.get('cat'), []).append(idx)
    biggest = max(by_cat.items(), key=lambda kv: len(kv[1]))
    print('  ④ 最大星团：%s（%d 点）' % (biggest[0], len(biggest[1])))
    t0 = time.time()
    cand_idx = biggest[1]
    rest = set(cand_idx)
    first = max(rest, key=lambda k: stars[k].get('age') or 0.0)
    rest.discard(first)
    tree = [first]
    ops = 0
    while rest:
        best = None
        for a in tree:
            for b in rest:
                ops += 1
                d = abs((stars[a].get('age') or 0.0) - (stars[b].get('age') or 0.0))
                if best is None or d < best[0]:
                    best = (d, a, b)
        _d, a, b = best
        tree.append(b)
        rest.discard(b)
        if len(tree) > 400:      # 只测 400 步就够外推（避免真跑完）
            break
    t_prim400 = time.time() - t0
    full_est = t_prim400 * (len(cand_idx) / 400.0) ** 3
    print('     朴素 Prim 前 400 步：%.2f s（%d 次距离比较）' % (t_prim400, ops))
    print('     ⇒ 该类跑完预估 %.0f s（O(n³)，%d 点）' % (full_est, len(cand_idx)))

    # --- 阶段 4：1 维 MST 用排序替代（等价）
    t0 = time.time()
    order = sorted(cand_idx, key=lambda k: (stars[k].get('age') or 0.0, k))
    edges_sorted = [(order[i], order[i + 1]) for i in range(len(order) - 1)]
    t_sort = time.time() - t0
    print('  ⑤ 排序法建 1 维 MST：%.4f s（%d 条边）' % (t_sort, len(edges_sorted)))

    print()
    print('=' * 76)
    print('结论')
    print('=' * 76)
    print('  强边：terms 缓存把 199 万次 tokenize 压成 %d 次；' % n)
    print('        倒排把配对从 %d 降到 %d（省 %.0f%%）'
          % (pairs, len(shared), 100.0 * (1 - len(shared) / max(pairs, 1))))
    print('  弱边：O(n³) → O(n log n)，结果等价（1 维 MST 就是排序相邻连）')
    print('  两项合计预估：%.0f s → %.1f s' % (36.9, t_terms + t_inv + t_invcount + t_sort + 1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
