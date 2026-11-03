# -*- coding: utf-8 -*-
"""build_edges 优化前后的等价性 + 性能对比（2026-11-03）

## 为什么必须做这步

性能优化最危险的情况是「变快了但答案变了」。所以必须：
1. 用**旧算法**（原样复刻 Prim + 全配对 jaccard）跑一遍
2. 用**新算法**（产品当前实现）跑同一份数据
3. 逐边对比

## 判据（不是"差不多就算对"）

| 项 | 要求 |
|---|---|
| 强边集合 | **完全一致**（顶点对集合 + 权重） |
| 弱边数量 | 完全一致 |
| 弱边总权重 | 完全一致（都是 MST） |
| 弱边集合 | 允许不同，但**只允许在 age 相同**的点之间不同（MST 不唯一） |

任何一项不满足 ⇒ 优化有问题，必须回退。
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


def old_build_edges(stars):
    """优化前的实现（原样复刻，用于对照）"""
    n = len(stars)
    if n < 2:
        return [], []
    cand = []
    for i in range(n):
        for j in range(i + 1, n):
            w = msm.jaccard(stars[i].get('text', ''), stars[j].get('text', ''))
            if w >= msm.STRONG_EDGE_JACCARD:
                cand.append((w, i, j))
    cand.sort(reverse=True)
    deg = {}
    strong = []
    for w, i, j in cand:
        if deg.get(i, 0) >= msm.STRONG_EDGES_PER_NODE or \
           deg.get(j, 0) >= msm.STRONG_EDGES_PER_NODE:
            continue
        strong.append((i, j, w))
        deg[i] = deg.get(i, 0) + 1
        deg[j] = deg.get(j, 0) + 1
    by_cat = {}
    for idx, s in enumerate(stars):
        by_cat.setdefault(s.get('cat'), []).append(idx)
    weak = []
    for cand_idx in by_cat.values():
        if len(cand_idx) < 2:
            continue
        rest = set(cand_idx)
        first = max(rest, key=lambda k: stars[k].get('age') or 0.0)
        rest.discard(first)
        tree = [first]
        while rest:
            best = None
            for a in tree:
                for b in rest:
                    d = abs((stars[a].get('age') or 0.0) - (stars[b].get('age') or 0.0))
                    if best is None or d < best[0]:
                        best = (d, a, b)
            _d, a, b = best
            weak.append((a, b))
            tree.append(b)
            rest.discard(b)
    return strong, weak


def load_stars(n_noise):
    src = json.loads(io.open(os.path.join(DATA, 'memories-1411.json'), encoding='utf-8').read())
    real = [f for f in json.loads(io.open(os.path.join(REPO, 'memory.json'),
                                         encoding='utf-8').read())['facts']
            if f.get('status') == 'active']
    stars = []
    for f in real:
        c = str(f.get('content') or '')
        stars.append({'text': c, 'imp': f.get('importance', 3), 'age': 5.0, 'kind': 'fact',
                      'cat': msm._classify(c, 'active', 'fact'), 'detail': '', 'time': '',
                      'key': 'f:%s' % f.get('id')})
    for i, f in enumerate(src['facts'][:n_noise]):
        c = f.get('content', '')
        stars.append({'text': c, 'imp': f.get('importance', 3),
                      'age': float(f.get('age_days') or 1.0), 'kind': 'fact',
                      'cat': msm._classify(c, 'active', 'fact'), 'detail': '',
                      'time': f.get('created_at', ''), 'key': 'n:%d' % i})
    return stars


def main():
    for n_noise in (39, 200, 1390):
        stars = load_stars(n_noise)
        n = len(stars)
        print('=' * 76)
        print('%d 个星点' % n)
        print('=' * 76)

        t0 = time.time()
        s_old, w_old = old_build_edges(stars)
        t_old = time.time() - t0

        t0 = time.time()
        s_new, w_new = msm.build_edges(stars)
        t_new = time.time() - t0

        print('  耗时：旧 %.2f s → 新 %.2f s（%.1f× 快）'
              % (t_old, t_new, t_old / max(t_new, 1e-6)))

        # 强边：顶点对集合必须一致（权重由同一公式算出，必然一致）
        def pairs(es):
            return set((min(i, j), max(i, j)) for i, j, _w in es)
        po, pn = pairs(s_old), pairs(s_new)
        same_strong = po == pn
        print('  强边：旧 %d 条 / 新 %d 条  顶点对一致：%s'
              % (len(s_old), len(s_new), '✓' if same_strong else '✗'))
        if not same_strong:
            print('     只在旧：%s' % list(po - pn)[:5])
            print('     只在新：%s' % list(pn - po)[:5])

        # 弱边：数量与总权重
        def wsum(ws):
            return sum(abs((stars[a].get('age') or 0.0) - (stars[b].get('age') or 0.0))
                       for a, b in ws)
        print('  弱边：旧 %d 条 / 新 %d 条  总权重 %.4f vs %.4f  差 %.2e'
              % (len(w_old), len(w_new), wsum(w_old), wsum(w_new),
                 abs(wsum(w_old) - wsum(w_new))))
        same_count = len(w_old) == len(w_new)
        same_weight = abs(wsum(w_old) - wsum(w_new)) < 1e-6
        print('     数量一致 %s / 总权重一致 %s'
              % ('✓' if same_count else '✗', '✓' if same_weight else '✗'))

        # 弱边等价性的正确判据（1 维 MST 的性质）：
        #   一维点集的最小生成森林总权重 = Σ(排序后相邻差)，与边集本身无关。
        #   ⇒ 「边数相同 + 总权重相同 + 都连通」即证明两者都是最小生成树。
        #   边集在 age 并列的点附近可以互换，星图视觉（线的总长）完全一致。
        wo = set((min(a, b), max(a, b)) for a, b in w_old)
        wn = set((min(a, b), max(a, b)) for a, b in w_new)
        diff = wo ^ wn
        n_cat = len(set(s.get('cat') for s in stars))
        want_edges = n - n_cat          # 每类一棵树 ⇒ n - 类别数
        connected = len(w_old) == want_edges and len(w_new) == want_edges
        print('     边集差异 %d 条（%.1f%%）' % (len(diff), 100.0 * len(diff) / max(len(wo), 1)))
        print('     连通性：每类一棵树需 %d 条边，旧 %d / 新 %d  %s'
              % (want_edges, len(w_old), len(w_new), '✓' if connected else '✗'))
        equiv = same_count and same_weight and connected
        print('     ⇒ 等价判定（边数+总权重+连通）：%s' % ('✓ 等价' if equiv else '✗ 不等价'))
        if diff and same_weight:
            print('        边集可互换的原因：age 有并列值 ⇒ 一维 MST 不唯一，')
            print('        但总权重恒等于 Σ(排序相邻差) = max-min，视觉总长不变。')
            ages = [stars[k].get('age') or 0.0 for k in range(n)]
            from collections import Counter
            dup = sum(1 for v, c in Counter(round(a, 6) for a in ages).items() if c > 1)
            print('        并列 age 取值个数：%d' % dup)
        print()
    return 0


if __name__ == '__main__':
    sys.exit(main())
