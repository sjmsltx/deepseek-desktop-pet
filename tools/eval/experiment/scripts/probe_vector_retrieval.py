# -*- coding: utf-8 -*-
"""向量检索能否突破「留出集 R@3 42%」—— 真机实测（2026-11-04）

## 为什么测这个

`memory_engine.py` 的注释写着：

    ⛔ 真正的瓶颈不是这个数：把闸门全关（matched=0、cov=0），留出集也只有 42%。
       字面匹配打不过同义改写（「我大几」vs「用户是大二学生」无共同 2-gram）。
       要往上走必须加同义词表或语义检索，别再指望调 GATE_*。

这是那道天花板。本脚本用真模型（bge-small-zh-v1.5 int8）实测能不能翻过去。

## 必须同时测「契约」，不能只看召回

`test_memory_gate.py` 的语义契约：

    例：「扫雷是什么」只是在问概念，并非问用户的偏好，不该把记忆抬出来。

⚠ 这条与语义检索**天然冲突**：
   「扫雷是什么」的向量和「用户喜欢在桌宠里玩扫雷和 Farkle 骰子」几乎同向。
   字面判据 easy 挡得住（只共享 1 个 2-gram ⇒ coverage 0.25 < 0.30），
   向量判据**没有任何理由**区分「在问概念」和「在问我」。

⇒ 所以本脚本把「召回」和「契约」一起量，不许只挑好看的那个报。

## 口径

严格复用 `tools/eval/gate_study/run_study.py`：
  · 开发集 = cases.json:recall（6 条）、留出集 = cases.json:holdout（12 条）
  · 负样本 = negatives.json（42 条六类 + pure_noise_cases）
  · 真实对话 = realdist.json（45 条）
  · 事实库 = memory.json 的 active facts（与 run_study 同一个 FACTS）
  · 契约 = 扫雷/骰子必须挡住，考研强查询不能死
"""
import io
import json
import os
import sys

REPO = r'D:\ai工作站\desktop-pet'
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, 'tools', 'eval', 'gate_study'))

import numpy as np                      # noqa: E402
import onnxruntime as ort               # noqa: E402
from tokenizers import Tokenizer        # noqa: E402

import memory_engine as me              # noqa: E402
import run_study as rs                  # noqa: E402   复用既有口径，不另造接口

CACHE = os.path.join(REPO, 'tools', 'eval', 'experiment', '_embed_probe')
EVAL = os.path.join(REPO, 'tools', 'eval')

tok = Tokenizer.from_file(os.path.join(CACHE, 'tokenizer.json'))
tok.enable_truncation(max_length=128)
tok.enable_padding(length=128)
sess = ort.InferenceSession(os.path.join(CACHE, 'model.onnx'),
                            providers=['CPUExecutionProvider'])
NAMES = [i.name for i in sess.get_inputs()]


def encode(texts):
    if not texts:
        return np.zeros((0, 512), dtype=np.float32)
    encs = tok.encode_batch([t or ' ' for t in texts])
    ids = np.array([e.ids for e in encs], dtype=np.int64)
    mask = np.array([e.attention_mask for e in encs], dtype=np.int64)
    feed = {}
    for n in NAMES:
        if n == 'input_ids':
            feed[n] = ids
        elif n == 'attention_mask':
            feed[n] = mask
        else:
            feed[n] = np.zeros_like(ids)
    v = sess.run(None, feed)[0][:, 0, :]
    return (v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)).astype(np.float32)


# ---------- 事实库（与 run_study 同源） ----------
FACTS = [f for f in json.loads(io.open(os.path.join(REPO, 'memory.json'),
                                      encoding='utf-8').read())['facts']
         if f.get('status', 'active') == 'active']
FACT_TEXTS = [(f.get('content') or '').strip() for f in FACTS]
FACT_VECS = encode(FACT_TEXTS)
print('事实库 %d 条，向量 %s' % (len(FACT_TEXTS), FACT_VECS.shape))

CASES = rs.load_cases()
DEV, HOLD = CASES['recall'], CASES['holdout']
NEG = rs.load_negatives()
REALDIST = rs.load_realdist()['messages']


# ---------- 三种判据 ----------
def vquery(q, thr, top_k=3):
    """纯向量：cosine ≥ thr 才注入"""
    qv = encode([q])[0]
    sims = FACT_VECS @ qv
    order = np.argsort(-sims)
    out = []
    for i in order:
        if sims[i] < thr:
            break
        out.append((int(i), float(sims[i])))
        if len(out) >= top_k:
            break
    return [FACT_TEXTS[i] for i, _s in out]


#: 定义式提问（在问「这个概念是什么」，不是在问「我」）
_DEF_PAT = ('是什么', '是啥', '啥意思', '什么意思', '介绍一下', '介绍下',
            '怎么回事', '啥玩意', '是什么东西', '讲讲', '科普')


def is_definition_question(q):
    q = (q or '').strip()
    return any(p in q for p in _DEF_PAT)


def vquery_guarded(q, thr, top_k=3):
    """向量 + 句式守卫：定义式提问一律不注入（守住「记忆只作背景不做话题」）"""
    if is_definition_question(q):
        return []
    return vquery(q, thr, top_k)


def bm25_query(q, cov=me.GATE_MIN_COVERAGE, matched=me.GATE_MIN_MATCHED, top_k=3):
    """现况：BM25 + coverage 闸门（直接调产品入口，不复制逻辑）"""
    old = (me.GATE_MIN_MATCHED, me.GATE_MIN_COVERAGE, me.GATE_KEEP_RATIO)
    me.GATE_MIN_MATCHED, me.GATE_MIN_COVERAGE = matched, cov
    try:
        return [str(h.get('text') or '') for h in
                me.search_memory_for_injection(FACTS, q, top_k=top_k)]
    finally:
        me.GATE_MIN_MATCHED, me.GATE_MIN_COVERAGE, me.GATE_KEEP_RATIO = old


def r3(fn, cases):
    hit = 0
    miss = []
    for c in cases:
        texts = fn(c['query'])
        if rs.hit_any(texts[:3], c['expect_any']):
            hit += 1
        else:
            miss.append(c['id'])
    return hit / max(len(cases), 1), miss


def noise_stats(fn):
    """纯噪声注入数 / 总注入行 / 有注入的问句数"""
    pure = 0
    rows = 0
    injq = 0
    for _cat, qs in NEG['categories'].items():
        for q in qs:
            t = fn(q)
            if t:
                injq += 1
                rows += len(t)
    for c in NEG.get('pure_noise_cases', []):
        if not c.get('must_not_hit'):
            continue
        if rs.hit_any(fn(c['query']), c['must_not_hit']):
            pure += 1
    return pure, rows, injq


def contract(fn):
    """(概念提问全挡住, 强查询没死)"""
    blocked = all(len(fn(q)) == 0 for q in rs.CONTRACT_QUERIES)
    strong = len(fn(rs.CONTRACT_STRONG)) > 0
    return blocked, strong


def inject_rate(fn):
    n = sum(1 for m in REALDIST if fn(m['text']))
    return n / max(len(REALDIST), 1), n


def line(c='=', n=104):
    print(c * n)


# ═══════════════════════════════════════════════════
line()
print('① 先复现基线（证明我的口径与 run_study 一致，否则「更好」无从比较）')
line()
b_dev, b_dev_miss = r3(lambda q: bm25_query(q), DEV)
b_hold, b_hold_miss = r3(lambda q: bm25_query(q), HOLD)
b_pure, b_rows, b_injq = noise_stats(lambda q: bm25_query(q))
b_block, b_strong = contract(lambda q: bm25_query(q))
b_rate, b_n = inject_rate(lambda q: bm25_query(q))
print('  BM25 现况（cov=%.2f matched=%d）' % (me.GATE_MIN_COVERAGE, me.GATE_MIN_MATCHED))
print('    devR@3  %d/%d = %.0f%%' % (round(b_dev * 6), 6, b_dev * 100))
print('    holdR@3 %d/%d = %.0f%%   (注释里写的是 42%%)' % (round(b_hold * 12), 12, b_hold * 100))
print('    留出集未中：%s' % (b_hold_miss or '无'))
print('    纯噪声 %d / 注入行 %d / 有注入问句 %d' % (b_pure, b_rows, b_injq))
print('    契约：扫雷挡住=%s 强查询存活=%s' % (b_block, b_strong))
print('    真实对话注入率 %.1f%% (%d/%d)' % (b_rate * 100, b_n, len(REALDIST)))

print()
print('  闸门全关（matched=0, cov=0）——注释说这也只有 42%')
a_dev, _ = r3(lambda q: bm25_query(q, cov=0.0, matched=0), DEV)
a_hold, a_miss = r3(lambda q: bm25_query(q, cov=0.0, matched=0), HOLD)
print('    devR@3 %d/6 = %.0f%%   holdR@3 %d/12 = %.0f%%'
      % (round(a_dev * 6), a_dev * 100, round(a_hold * 12), a_hold * 100))
print('    （全关后仍没召回的：%s）' % (a_miss or '无'))

# ═══════════════════════════════════════════════════
print()
line()
print('② 纯向量：扫阈值（**不带句式守卫**，看代价）')
line()
print('  %-7s %-9s %-9s %-7s %-8s %-8s %-7s' %
      ('阈值', 'devR@3', 'holdR@3', '纯噪声', '扫雷挡住', '强查询', '注入率'))
print('  ' + '-' * 66)
pure_res = {}
for thr in (0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75):
    fn = (lambda t: (lambda q: vquery(q, t)))(thr)
    d, _ = r3(fn, DEV)
    h, hmiss = r3(fn, HOLD)
    p, _rows, _injq = noise_stats(fn)
    blk, stg = contract(fn)
    rate, _n = inject_rate(fn)
    pure_res[thr] = (d, h, p, blk, stg, rate)
    print('  %-7.2f %-9s %-9s %-7d %-8s %-8s %-7s'
          % (thr, '%d/6=%.0f%%' % (round(d * 6), d * 100),
             '%d/12=%.0f%%' % (round(h * 12), h * 100), p,
             '是' if blk else '★否', '是' if stg else '★否', '%.0f%%' % (rate * 100)))

# ═══════════════════════════════════════════════════
print()
line()
print('③ 向量 + 句式守卫（定义式提问不注入）')
line()
print('  %-7s %-9s %-9s %-7s %-8s %-8s %-7s' %
      ('阈值', 'devR@3', 'holdR@3', '纯噪声', '扫雷挡住', '强查询', '注入率'))
print('  ' + '-' * 66)
guard_res = {}
for thr in (0.45, 0.50, 0.55, 0.60, 0.65, 0.70):
    fn = (lambda t: (lambda q: vquery_guarded(q, t)))(thr)
    d, _ = r3(fn, DEV)
    h, hmiss = r3(fn, HOLD)
    p, _r, _i = noise_stats(fn)
    blk, stg = contract(fn)
    rate, _n = inject_rate(fn)
    guard_res[thr] = (d, h, p, blk, stg, rate)
    print('  %-7.2f %-9s %-9s %-7d %-8s %-8s %-7s'
          % (thr, '%d/6=%.0f%%' % (round(d * 6), d * 100),
             '%d/12=%.0f%%' % (round(h * 12), h * 100), p,
             '是' if blk else '★否', '是' if stg else '★否', '%.0f%%' % (rate * 100)))

# ═══════════════════════════════════════════════════
print()
line()
print('④ 留出集逐条：BM25 漏的，向量抓住了吗')
line()
best_thr = 0.60
for c in HOLD:
    b = bm25_query(c['query'])
    v = vquery_guarded(c['query'], best_thr)
    b_ok = rs.hit_any(b[:3], c['expect_any'])
    v_ok = rs.hit_any(v[:3], c['expect_any'])
    tag = '✓✓' if b_ok and v_ok else ('★ B漏V中' if v_ok else ('★ B中V漏' if b_ok else '✗✗ 都漏'))
    print('  %-5s %-24s BM25=%-5s 向量=%-5s  %s'
          % (c['id'], c['query'][:24], '中' if b_ok else '漏', '中' if v_ok else '漏', tag))
    if v_ok and not b_ok:
        print('        向量命中：%s' % v[0][:60])
    if b_ok and not v_ok:
        print('        BM25 命中：%s' % b[0][:60])

# ═══════════════════════════════════════════════════
print()
line()
print('⑤ 契约细节：为什么「扫雷是什么」是向量检索的死结')
line()
for q in rs.CONTRACT_QUERIES + [rs.CONTRACT_STRONG]:
    qv = encode([q])[0]
    sims = FACT_VECS @ qv
    order = np.argsort(-sims)[:3]
    print('  「%s」（判定为定义式=%s）' % (q, is_definition_question(q)))
    for i in order:
        print('     cos %.3f  %s' % (sims[i], FACT_TEXTS[i][:58]))
    print()

# ═══════════════════════════════════════════════════
print()
line()
print('⑥ 真相关但被阈值挡掉的（看误伤）')
line()
for c in HOLD:
    qv = encode([c['query']])[0]
    sims = FACT_VECS @ qv
    order = np.argsort(-sims)
    top_i = int(order[0])
    top_s = float(sims[top_i])
    ok = rs.hit_any([FACT_TEXTS[top_i]], c['expect_any'])
    flag = '' if ok else '  ← top1 不是期望'
    print('  %-5s top1 cos=%.3f %-6s %s%s'
          % (c['id'], top_s, '正确' if ok else '★错', FACT_TEXTS[top_i][:48], flag))
