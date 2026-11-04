# -*- coding: utf-8 -*-
"""多维节点原型 v2（2026-11-04）—— 只读 1411 条实验数据，不碰产品库

## v1 错在哪（必须记下来，否则会用错的数下结论）

1. **选阈值的选择函数坏了**：我用 `f1*0.6 + 实体召回*0.4` 打分，
   而「把所有条目并成 1 簇」时实体召回天然 = 1.0 ⇒ 选中了阈值 0.60（19 簇）。
   那个簇里最大一个装了 921 条 —— 不是聚类，是塌缩。
2. **在塌缩的簇上算出来的数全是假的**：压缩比 74:1、注入率 87%→16%、
   留存率 6%，都建立在 19 个巨型簇之上，不能当结论。
3. **手写结论与数字相反**：留存率实际 6%，我却印「大约只保留了原句一半的措辞」。

## v2 改法

- 局部指标优先：**kNN 同实体命中率**（不受 3581 vs 991174 的类别不平衡影响）
- 聚类换 scipy 层次聚类（average linkage），不再用顺序依赖的贪心
- 选阈值加约束：簇数必须落在真值 239 的 [0.5x, 3x] 内，再按 purity 选
- 所有结论句由变量插值生成
"""
import io
import json
import os
import sys

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

REPO = r'D:\ai工作站\desktop-pet'
sys.path.insert(0, REPO)
os.environ.setdefault('PET_EMBED_DIR',
                      os.path.join(REPO, 'tools', 'eval', 'experiment', '_embed_probe'))

import memory_embed as mem              # noqa: E402

DATA = os.path.join(REPO, 'tools', 'eval', 'experiment', 'data', 'memories-1411.json')
RESULTS = os.path.join(REPO, 'tools', 'eval', 'experiment', 'results')

d = json.loads(io.open(DATA, encoding='utf-8').read())
FACTS = d['facts']
TEXTS = [(f.get('content') or '').strip() for f in FACTS]
BATCH = np.array([int(f.get('batch', -1)) for f in FACTS])
IMP = np.array([float(f.get('importance', 3)) for f in FACTS])
N = len(TEXTS)
N_TRUE = len(set(BATCH.tolist()))

e = mem.get_embedder()
assert e.ok, mem.status()
print('语料 %d 条，真值实体 %d 个（batch 字段）' % (N, N_TRUE))
V = e.encode(TEXTS)


def line(c='=', n=98):
    print(c * n)


def short(t, n=52):
    return (t or '')[:n]


# ═══════════ ① 可分性（局部指标优先） ═══════════
line()
print('① 可分性')
line()
R = V @ V.T
np.fill_diagonal(R, -1.0)               # 排除自己
same = BATCH[:, None] == BATCH[None, :]
iu = np.triu_indices(N, k=1)
rs, rd = R[iu][same[iu]], R[iu][~same[iu]]
print('  同类对 %d 组：中位 %.4f（p10 %.4f / p90 %.4f）'
      % (len(rs), np.median(rs), np.percentile(rs, 10), np.percentile(rs, 90)))
print('  异类对 %d 组：中位 %.4f（p10 %.4f / p90 %.4f）'
      % (len(rd), np.median(rd), np.percentile(rd, 10), np.percentile(rd, 90)))
print('  ⇒ 中位差 %.4f；%s'
      % (np.median(rs) - np.median(rd),
         '分布有重叠（单阈值切不干净）'
         if np.percentile(rs, 10) < np.percentile(rd, 90) else '分布基本分离'))

print()
print('  ★ 局部指标（不受类别不平衡影响）：最近邻是否同一实体')
knn = {}
for k in (1, 3, 5):
    order = np.argsort(-R, axis=1)[:, :k]
    ok = sum(1 for i in range(N) if any(BATCH[j] == BATCH[i] for j in order[i]))
    knn[k] = ok / N
    print('    top-%d 里含同实体：%.1f%%' % (k, 100 * knn[k]))
print('  ⇒ 若 top-1 只有约 %.0f%%，说明「同一件事的不同面向」在向量空间里并不紧挨' % (100 * knn[1]))

# ═══════════ ② 层次聚类质量 ═══════════
line()
print('② 层次聚类（average linkage，余弦距离）')
line()
D = 1.0 - R
np.fill_diagonal(D, 0.0)
D = (D + D.T) / 2.0                      # 数值对称
Z = linkage(squareform(D, checks=False), method='average')

print('  %-9s %-8s %-9s %-9s %-11s %s'
      % ('距离阈', '簇数', 'purity', '实体召回', '中位簇内批数', '评价'))
print('  ' + '-' * 84)
rows = []
for cut in (0.20, 0.25, 0.30, 0.325, 0.35, 0.40, 0.45):
    labels = fcluster(Z, t=cut, criterion='distance')
    k = len(set(labels.tolist()))
    per = {}
    for lb, bt in zip(labels, BATCH):
        per.setdefault(int(lb), {})
        per[int(lb)][int(bt)] = per[int(lb)].get(int(bt), 0) + 1
    purity = sum(max(c.values()) for c in per.values()) / N
    per_b = {}
    for lb, bt in zip(labels, BATCH):
        per_b.setdefault(int(bt), {})
        per_b[int(bt)][int(lb)] = per_b[int(bt)].get(int(lb), 0) + 1
    ent_rec = sum(1 for c in per_b.values()
                  if max(c.values()) >= 0.5 * sum(c.values())) / len(per_b)
    med_batches = float(np.median([len(c) for c in per.values()]))
    rows.append((cut, k, purity, ent_rec, med_batches, labels))
    print('  %-9.3f %-8d %-9.3f %-9.3f %-11.1f %s'
          % (cut, k, purity, ent_rec, med_batches,
             '簇数接近真值' if 0.5 * N_TRUE <= k <= 3 * N_TRUE else '偏离真值'))

# 选阈值：簇数必须在 [0.5x, 3x] 真值内，再按 purity 取最高
cand = [r for r in rows if 0.5 * N_TRUE <= r[1] <= 3 * N_TRUE]
if one := cand:
    cut, k, purity, ent_rec, med_batches, labels = max(cand, key=lambda r: r[2])
    print()
    print('  ⇒ 取距离阈 %.3f：%d 簇（真值 %d），purity %.3f，实体召回 %.3f，'
          '每簇中位含 %.0f 个不同 batch'
          % (cut, k, N_TRUE, purity, ent_rec, med_batches))
    print('    purity %.3f 的含义：每个簇里最多的那个实体占 %.0f%%，其余是混进来的'
          % (purity, 100 * purity))
else:
    print()
    print('  ⚠ 没有任何档位的簇数落在真值的合理区间内 ⇒ 该聚类方式不可用')
    labels = np.zeros(N, dtype=int)
    k, purity, ent_rec, cut = 1, 0.0, 1.0, 0.0

# ═══════════ ③ 压缩与信息留存 ═══════════
line()
print('③ 压缩与信息留存（聚合句预算 200 字，按 importance 降序拼）')
line()
sizes = np.bincount(labels)
print('  簇数 %d（原 %d 条）⇒ 压缩比 %.1f:1' % (k, N, N / float(k)))
print('  簇大小：中位 %d / 最大 %d / 单条簇 %d 个（%.0f%%）'
      % (int(np.median(sizes)), int(sizes.max()),
         int((sizes == 1).sum()), 100.0 * (sizes == 1).sum() / len(sizes)))

BUDGET = 200
AGG = {}
for c in range(1, labels.max() + 1):
    members = np.where(labels == c)[0]
    order = sorted(members.tolist(), key=lambda i: -IMP[i])
    txt = ''
    for i in order:
        cand_txt = (txt + '；' + TEXTS[i]) if txt else TEXTS[i]
        if len(cand_txt) > BUDGET:
            continue                     # 跳过超长的，试下一条（别直接 break）
        txt = cand_txt
    AGG[c] = txt


def toks(t):
    t = (t or '').lower()
    out, run = [], []
    for ch in t:
        if '\u4e00' <= ch <= '\u9fff':
            run.append(ch)
        else:
            if len(run) >= 2:
                out.extend(''.join(run)[i:i + 2] for i in range(len(run) - 1))
            run = []
    if len(run) >= 2:
        out.extend(''.join(run)[i:i + 2] for i in range(len(run) - 1))
    return out


covs = []
for c in range(1, labels.max() + 1):
    at = set(toks(AGG[c]))
    for i in np.where(labels == c)[0]:
        ft = set(toks(TEXTS[i]))
        if ft:
            covs.append(len(ft & at) / len(ft))
covs = np.array(covs)
print('  原始记忆的 2-gram 在聚合句中的留存率：中位 %.2f / 均值 %.2f / 低于 0.5 占 %.0f%%'
      % (np.median(covs), covs.mean(), 100.0 * (covs < 0.5).mean()))
print('  ⇒ 平均每条只保留 %.0f%% 的原措辞（%s）'
      % (100 * np.median(covs),
         '信息损失明显，不能直接替代原节点'
         if np.median(covs) < 0.6 else '留存尚可'))

# ═══════════ ④ 注入噪声（在真实规模的聚类上比） ═══════════
line()
print('④ 注入噪声：真实对话 45 条的最高余弦')
line()
msgs = json.loads(io.open(os.path.join(REPO, 'tools', 'eval', 'realdist.json'),
                          encoding='utf-8').read())['messages']
MV = e.encode([m['text'] for m in msgs])
flat_max = (MV @ V.T).max(axis=1)
cent_texts = [AGG[c] for c in range(1, labels.max() + 1)]
CV = e.encode(cent_texts)
agg_max = (MV @ CV.T).max(axis=1)
print('  %d 个原节点：最高余弦 中位 %.4f / p90 %.4f'
      % (N, np.median(flat_max), np.percentile(flat_max, 90)))
print('  %d 个聚合节点：最高余弦 中位 %.4f / p90 %.4f'
      % (k, np.median(agg_max), np.percentile(agg_max, 90)))
print('  中位下降 %.4f' % (np.median(flat_max) - np.median(agg_max)))
print()
print('  ⚠ 两个口径**不能直接比阈值**：聚合句更长、信息更密，余弦尺度整体不同。')
print('    这里只报「最高余弦下降多少」，不报「注入率变成多少」——')
print('    要报注入率必须先在聚合节点上重新校准阈值（本轮没做）。')

# ═══════════ ⑤ 实体级召回 ═══════════
line()
print('⑤ 聚合后还能不能找回「那件事」（伪查询 = 原始记忆原文，取 200 条）')
line()
rng = np.random.RandomState(7)
sample = rng.choice(N, size=200, replace=False)
hit1 = hit3 = 0
for i in sample:
    sims = CV @ V[i]
    order = np.argsort(-sims)[:3]
    right = labels[i] - 1               # AGG 的键从 1 开始
    if right in set(int(j) for j in order):
        hit3 += 1
        if int(order[0]) == right:
            hit1 += 1
print('  聚合节点检索：top1 命中所属簇 %.0f%% / top3 %.0f%%'
      % (100.0 * hit1 / len(sample), 100.0 * hit3 / len(sample)))
print('  对照：原节点 top1 同实体 %.0f%% / top3 %.0f%%'
      % (100 * knn[1], 100 * knn[3]))

line()
print('结论（全部由变量插值生成）')
line()
facts_out = {
    'knn1_same_entity_pct': round(100 * knn[1], 1),
    'knn3_same_entity_pct': round(100 * knn[3], 1),
    'same_median': round(float(np.median(rs)), 4),
    'diff_median': round(float(np.median(rd)), 4),
    'cluster_cut': cut, 'n_clusters': int(k), 'n_true': int(N_TRUE),
    'purity': round(float(purity), 3),
    'entity_recall': round(float(ent_rec), 3),
    'compression': round(N / float(k), 1),
    'singleton_pct': round(100.0 * (sizes == 1).sum() / len(sizes), 1),
    'retention_median': round(float(np.median(covs)), 3),
    'noise_drop': round(float(np.median(flat_max) - np.median(agg_max)), 4),
}
lines = [
    '同实体中位余弦 %.3f vs 异类 %.3f（差 %.3f）' % (
        facts_out['same_median'], facts_out['diff_median'],
        facts_out['same_median'] - facts_out['diff_median']),
    '最近邻同实体仅 %.0f%%，top-3 %.0f%% ⇒ %s' % (
        facts_out['knn1_same_entity_pct'], facts_out['knn3_same_entity_pct'],
        '「同一件事的不同面向」在向量空间里并不紧挨'
        if facts_out['knn1_same_entity_pct'] < 70 else '同实体确实相邻'),
    '层次聚类 %d 簇（真值 %d），purity %.3f，实体召回 %.3f' % (
        facts_out['n_clusters'], facts_out['n_true'],
        facts_out['purity'], facts_out['entity_recall']),
    'purity %.3f ⇒ %s' % (
        facts_out['purity'],
        '簇里混进了其他实体，不能当「一件事」用'
        if facts_out['purity'] < 0.85 else '簇基本干净'),
    '压缩 %.1f:1，但聚合句只留原措辞 %.0f%% ⇒ %s' % (
        facts_out['compression'], 100 * facts_out['retention_median'],
        '信息损失过大，直接把多条压成一句会丢内容'
        if facts_out['retention_median'] < 0.6 else '损失可接受'),
    '真实消息最高余弦下降 %.4f（阈值需在聚合节点上重新校准后才能报注入率）'
    % facts_out['noise_drop'],
]
for t in lines:
    print('  · ' + t)

os.makedirs(RESULTS, exist_ok=True)
out = os.path.join(RESULTS, 'multidim-prototype.json')
with io.open(out, 'w', encoding='utf-8', newline='\n') as fh:
    fh.write(json.dumps({
        'generated': __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M'),
        'n_facts': N, 'n_true_entities': int(N_TRUE),
        'metrics': facts_out,
        'verdict': lines,
    }, ensure_ascii=False, indent=1) + '\n')
print()
print('  已写 %s' % out)
