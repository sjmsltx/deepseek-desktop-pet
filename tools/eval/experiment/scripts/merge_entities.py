# -*- coding: utf-8 -*-
"""实体合并：把「同一段对话」的标签合并成「同一个实体」（2026-11-04）

## 现在的状态

v3 按对话命名，质量对了（batch 0 → 「遥感原理学习」，batch 57 → 「鱼香肉丝口味」），
但 topic 数 = 239 = batch 数 ⇒ **topic 只是 batch 的别名，没有做跨对话归并**。

真实需求：如果「遥感原理」在 3 段对话里都出现过，它们应该是**一个实体**。

## 合并依据

1. **object 完全相同且是专名** ⇒ 直接合并（最可靠：同一对象）
2. **topic 名称相同**（归一后） ⇒ 合并
3. 其余：用向量算 topic 名称的相似度做二次归并（阈值要高，避免误并）

## 验收

  · 合并后实体数（应显著少于 239，但远多于 86 那个过度合并版）
  · 抽样看合并结果是否合理：同实体内的条目是否真在说同一件事
  · **反向检查**：不该合并的（鱼香肉丝 vs 遥感）是否被误并
"""
import io
import json
import os
import sys
import collections

import numpy as np

REPO = r'D:\ai工作站\desktop-pet'
EXP = os.path.join(REPO, 'tools', 'eval', 'experiment')
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(EXP, 'scripts'))
os.environ.setdefault('PET_EMBED_DIR', os.path.join(EXP, '_embed_probe'))

import memory_embed as mem              # noqa: E402

V3 = os.path.join(EXP, 'results', 'library-labels-v3.json')
OUT = os.path.join(EXP, 'results', 'entity-merged.json')

d = _rjson(V3)
lab = d['synth']
syn = json.loads(io.open(os.path.join(EXP, 'data', 'memories-1411.json'),
                        encoding='utf-8').read())['facts']
sid_b = {'syn-%04d' % i: int(f.get('batch', -1)) for i, f in enumerate(syn)}
sid_t = {'syn-%04d' % i: (f.get('content') or '').strip() for i, f in enumerate(syn)}

e = mem.get_embedder()
assert e.ok


def norm(s):
    s = (s or '').strip().lower()
    for ch in ' \u3000，。、；：！？,.;:!?（）()「」"\'·':
        s = s.replace(ch, '')
    return s


# ---------- 第 1 步：按 object 合并（最可靠）----------
GROUPS = {}          # entity_key -> [sid]
parent = {}


def find(x):
    parent.setdefault(x, x)
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def union(a, b):
    ra, rb = find(a), find(b)
    if ra != rb:
        parent[rb] = ra


# 每个 batch 一个初始节点（因为 topic 是按 batch 定的）
node_label = {}
for b in sorted(set(sid_b.values())):
    sids = [s for s, bb in sid_b.items() if bb == b]
    L = lab.get(sids[0]) or {}
    node = 'B%d' % b
    node_label[node] = {'topic': L.get('topic') or '',
                        'object': (L.get('object') or '').strip(),
                        'members': sids}
    find(node)

# ① object 相同且非空 ⇒ 合并
by_obj = collections.defaultdict(list)
for node, v in node_label.items():
    o = norm(v['object'])
    if o and len(v['object']) >= 2:
        by_obj[o].append(node)
merged_obj = 0
for o, nodes in by_obj.items():
    if len(nodes) > 1:
        for x in nodes[1:]:
            union(nodes[0], x)
        merged_obj += len(nodes) - 1

# ② topic 名称完全相同 ⇒ 合并
by_topic = collections.defaultdict(list)
for node, v in node_label.items():
    t = norm(v['topic'])
    if t:
        by_topic[t].append(node)
merged_top = 0
for t, nodes in by_topic.items():
    if len(nodes) > 1:
        for x in nodes[1:]:
            union(nodes[0], x)
        merged_top += len(nodes) - 1

stage1 = len({find(n) for n in node_label})
print('按 object 合并 %d 个，按 topic 同名合并 %d 个' % (merged_obj, merged_top))
print('初始 %d 个节点 → 第 1 阶段 %d 个实体' % (len(node_label), stage1))

# ---------- 第 2 步：向量二次归并 ----------
# 用「topic + object」文本算相似度，只看有没有可能併
keys = sorted({find(n) for n in node_label})
rep = {}
for node, v in node_label.items():
    r = find(node)
    rep.setdefault(r, {'topic': v['topic'], 'object': v['object'],
                       'members': []})
    rep[r]['members'].extend(v['members'])

texts = ['%s %s' % (r['topic'], r['object']) for r in rep.values()]
V = e.encode(texts)
S = V @ V.T
np.fill_diagonal(S, -1.0)
print('实体两两相似度：中位 %.3f / p95 %.3f / 最大 %.3f'
      % (np.median(S[S > -1]), np.percentile(S[S > -1], 95), S.max()))

print()
print('=' * 92)
print('二次归并阈值扫描')
print('=' * 92)
print('  %-8s %-10s %-12s %s' % ('阈值', '实体数', '合并对数', '风险'))
print('  ' + '-' * 60)
best = None
for thr in (0.90, 0.92, 0.94, 0.96, 0.98):
    pairs = 0
    par2 = {k: k for k in rep}
    def f2(x):
        while par2[x] != x:
            par2[x] = par2[par2[x]]
            x = par2[x]
        return x
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            if S[i, j] >= thr:
                a, b = f2(keys[i]), f2(keys[j])
                if a != b:
                    par2[b] = a
                    pairs += 1
    n_final = len({f2(k) for k in rep})
    risk = '高（可能误并）' if thr < 0.94 else ('低' if thr >= 0.96 else '中')
    print('  %-8.2f %-10d %-12d %s' % (thr, n_final, pairs, risk))
    if best is None or (n_final < best[2] and thr >= 0.94):
        best = (thr, pairs, n_final)

print()
print('  参照：batch=%d（未合并）、v1 过度合并=86、v2 过碎=618' % len(node_label))

# 用 0.96 生成最终结果
THR = 0.96
par2 = {k: k for k in rep}


def f2(x):
    while par2[x] != x:
        par2[x] = par2[par2[x]]
        x = par2[x]
    return x


for i in range(len(keys)):
    for j in range(i + 1, len(keys)):
        if S[i, j] >= THR:
            a, b = f2(keys[i]), f2(keys[j])
            if a != b:
                par2[b] = a

final = collections.defaultdict(list)
for k in rep:
    final[f2(k)].extend(rep[k]['members'])
print()
print('  最终实体数 %d（阈值 %.2f）' % (len(final), THR))

# ---------- 反向检查：不该合并的有没有被并 ----------
print()
print('=' * 92)
print('反向检查：被合并的实体对，内部是否真在说同一件事')
print('=' * 92)
multi = {k: v for k, v in final.items() if len(v) > 3}
for k, sids in list(multi.items())[:6]:
    names = {lab.get(s, {}).get('topic') for s in sids}
    objs = {lab.get(s, {}).get('object') for s in sids if (lab.get(s, {}).get('object') or '').strip()}
    print('  实体 %s：%d 条，topic 名称 %d 种 %s' % (k[:8], len(sids), len(names), list(names)[:4]))
    print('     object：%s' % (list(objs)[:4] or '无'))
    for s in sids[:3]:
        print('       %s' % sid_t[s][:60])

# ---------- 抽样：实体内部一致性 ----------
print()
print('=' * 92)
print('抽样 5 个实体，看内部是否真属于同一件事')
print('=' * 92)
import random
pick = random.Random(7).sample(list(final.items()), 5)
for k, sids in pick:
    L = lab.get(sids[0]) or {}
    print('  【%s｜%s】%d 条' % (L.get('topic'), L.get('object') or '(无对象)', len(sids)))
    for s in sids[:4]:
        print('     %s' % sid_t[s][:58])
    print()

out = {
    'generated': __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M'),
    'n_batches': len(node_label),
    'after_object_merge': stage1,
    'final_entities': len(final),
    'threshold': THR,
    'entities': {k: v for k, v in final.items()},
}
with io.open(OUT, 'w', encoding='utf-8', newline='\n') as fh:
    fh.write(json.dumps(out, ensure_ascii=False, indent=1) + '\n')
print('  已写 %s' % OUT)
