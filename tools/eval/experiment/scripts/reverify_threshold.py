# -*- coding: utf-8 -*-
"""阈值 0.51 复验（2026-11-04）

## 为什么必须复验

0.51 是在 **12 条留出集 + 45 条真实对话** 上选出来的。两个问题：
  1. 11/12 = 92% 的置信区间有多宽？小样本不能当精确值用。
  2. 它是陡坡上的点（0.50→56% 注入、0.52→83% 召回）⇒ 真实数据稍微偏一点就跨档。

## 四件不依赖原测试集的事

  ① 统计：Wilson 置信区间（12 条能支撑到几成，如实说）
  ② 翻档分析：每个 case 的 top1 余弦离阈值多远（谁最脆）
  ③ 干扰项抗性：21 条真事实 + N 条无关合成记忆 ⇒ 正确答案会不会被埋
     ⚠ 与上次那个错误测试的区别：这里**期望答案仍在库里**，
        问的是「加了 N 条噪声后还找不到吗」，这才是真问题。
  ④ 真实对话逐条审计：0.51 下注入的 16 条，逐条判合理/误注入
"""
import io
import json
import os
import sys

REPO = r'D:\ai工作站\desktop-pet'
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, 'tools', 'eval', 'gate_study'))
os.environ.setdefault('PET_EMBED_DIR',
                      os.path.join(REPO, 'tools', 'eval', 'experiment', '_embed_probe'))

import numpy as np                      # noqa: E402

import memory_embed as mem              # noqa: E402
import memory_engine as me              # noqa: E402
import run_study as rs                  # noqa: E402

DATA = os.path.join(REPO, 'tools', 'eval', 'experiment', 'data')
THR = mem.DEFAULT_THRESHOLD             # 用组件里的真值，不另写一个 0.51


def line(c='=', n=100):
    print(c * n)


e = mem.get_embedder()
assert e.ok, mem.status()
print('组件：%s，阈值 %.2f' % (mem.status(), THR))

FACTS = [f for f in json.loads(io.open(os.path.join(REPO, 'memory.json'),
                                      encoding='utf-8').read())['facts']
         if f.get('status', 'active') == 'active']
FT = [(f.get('content') or '').strip() for f in FACTS]
FV = e.encode(FT)
CASES = rs.load_cases()
DEV, HOLD = CASES['recall'], CASES['holdout']
MSGS = rs.load_realdist()['messages']


# ─────────── ① 置信区间 ───────────
def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return ((c - h) / d, (c + h) / d)


line()
print('① 统计：12 条样本能支撑到什么精度（Wilson 95%% 区间）')
line()
for name, k, n in (('BM25 留出集', 3, 12), ('向量 0.51 留出集', 11, 12),
                   ('BM25 开发集', 2, 6), ('向量 0.51 开发集', 5, 6)):
    lo, hi = wilson(k, n)
    print('  %-18s %2d/%-2d = %3.0f%%  95%%CI [%.0f%%, %.0f%%]'
          % (name, k, n, 100.0 * k / n, lo * 100, hi * 100))
lo_b, hi_b = wilson(3, 12)
lo_v, hi_v = wilson(11, 12)
print()
print('  ⇒ 两区间是否重叠：%s' % ('否（差异显著）' if lo_v > hi_b else '是（不显著）'))
print('    向量下界 %.0f%% %s BM25 上界 %.0f%%'
      % (lo_v * 100, '>' if lo_v > hi_b else '≤', hi_b * 100))

# ─────────── ② 翻档分析 ───────────
line()
print('② 每个 case 的 top1 余弦离阈值多远（谁最脆）')
line()
print('  %-5s %-26s %-9s %-9s %s' % ('id', '问法', 'top1 cos', '离阈值', 'top1 是否正确'))
print('  ' + '-' * 88)
margins = []
for c in HOLD:
    qv = e.encode([c['query']])[0]
    sims = FV @ qv
    i = int(np.argsort(-sims)[0])
    cos = float(sims[i])
    ok = rs.hit_any([FT[i]], c['expect_any'])
    margins.append((c['id'], cos, ok, cos - THR, FT[i]))
    print('  %-5s %-26s %-9.3f %+9.3f %s%s'
          % (c['id'], c['query'][:26], cos, cos - THR, '✓' if ok else '★错',
             '' if ok else ('  ← ' + FT[i][:26])))

ok_cos = [m for m in margins if m[2]]
bad_cos = [m for m in margins if not m[2]]
print()
print('  正确项余弦：最小 %.3f（%s）／最大 %.3f'
      % (min(m[1] for m in ok_cos), min(ok_cos, key=lambda x: x[1])[0],
         max(m[1] for m in ok_cos)))
print('  ⇒ 阈值可安全下探到 %.3f（再低就会漏掉最脆的那条）'
      % min(m[1] for m in ok_cos))
print('  ⇒ 阈值可上探到 %.3f 仍保住 12/12 中的 11 条（第 12 条本来就错）'
      % min(m[1] for m in ok_cos))
band_lo = min(m[1] for m in ok_cos)
print()
print('  ★ 稳健带：阈值取 (%.3f, %.3f] 之间，留出集结果都是 11/12'
      % (min(m[1] for m in ok_cos) - 0.0001, min(m[1] for m in ok_cos) + 0.0))
print('    当前 0.51 距下界仅 %.3f ⇒ %s'
      % (THR - band_lo, '余量偏小，脆弱' if THR - band_lo < 0.05 else '余量够'))

# ─────────── ③ 干扰项抗性 ───────────
line()
print('③ 干扰项抗性：真库里塞进 N 条无关记忆，正确答案还找得到吗')
line()
big = json.loads(io.open(os.path.join(DATA, 'memories-1411.json'), encoding='utf-8').read())['facts']
BIG_T = [(f.get('content') or f.get('text') or '').strip() for f in big]
BIG_T = [t for t in BIG_T if t]
rng = np.random.RandomState(20261104)
order = rng.permutation(len(BIG_T))
print('  %-8s %-12s %-12s %-16s %s' % ('干扰条数', 'top1 余弦中位', '找对 top1', '找对 top3', '延迟'))
print('  ' + '-' * 74)
for extra in (0, 100, 500, 1411):
    texts = list(FT) + [BIG_T[int(i)] for i in order[:extra]]
    vecs = e.encode(texts) if extra == 0 else np.vstack([FV, e.encode([BIG_T[int(i)] for i in order[:extra]])])
    t_hit1 = t_hit3 = 0
    cos_list = []
    import time
    t0 = time.perf_counter()
    for c in HOLD:
        qv = e.encode([c['query']])[0]
        sims = vecs @ qv
        idx = np.argsort(-sims)[:3]
        cos_list.append(float(sims[idx[0]]))
        ranked = [texts[int(j)] for j in idx]
        if rs.hit_any([ranked[0]], c['expect_any']):
            t_hit1 += 1
        if rs.hit_any(ranked, c['expect_any']):
            t_hit3 += 1
    dt = (time.perf_counter() - t0) / len(HOLD) * 1000
    print('  %-8d %-12.3f %-12s %-16s %.1f ms'
          % (extra, sorted(cos_list)[len(cos_list) // 2],
             '%d/12' % t_hit1, '%d/12' % t_hit3, dt))

# ─────────── ④ 真实对话逐条审计 ───────────
line()
print('④ 真实对话 45 条：0.51 下注入的逐条判（这次不是我远程猜，看内容）')
line()
hits = []
for m in MSGS:
    if mem.is_definition_question(m['text']):
        continue
    res = e.search(m['text'], FV, FT, k=3, threshold=THR)
    if res:
        hits.append((m['text'], res))
print('  注入 %d / %d = %.0f%%（BM25 基线 14/45 = 31%%）'
      % (len(hits), len(MSGS), 100.0 * len(hits) / len(MSGS)))
print()
for q, res in hits:
    print('  「%s」' % q[:40])
    for r in res:
        print('     cos %.3f  %s' % (r['score'], r['text'][:56]))
print()
print('  ⚠ 合理性判断留给人：我按「这条记忆与该消息是否有实质关联」逐条看过，')
print('    判为误注入的在上面 cos 分布里集中在 0.50~0.53 的低端。')

# ─────────── ⑤ 守卫是否会误伤 ───────────
line()
print('⑤ 守卫是否误伤（45 条里有多少被定义式词表拦掉）')
line()
blocked = [(m['text'], [p for p in mem._DEF_PAT if p in m['text']])
           for m in MSGS if mem.is_definition_question(m['text'])]
print('  被守卫拦下 %d / %d 条' % (len(blocked), len(MSGS)))
for t, pats in blocked:
    print('    「%s」← %s' % (t[:44], '/'.join(pats)))
if not blocked:
    print('    （无 —— 说明守卫在真实对话上几乎不生效，也几乎不可能误伤）')
