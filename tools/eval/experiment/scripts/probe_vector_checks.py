# -*- coding: utf-8 -*-
"""向量检索的三个必查项（2026-11-04）

前一个脚本（probe_vector_retrieval.py）证明了两件事：
  · 向量 top1 正确率 11/12，比 BM25 的 25% 高得多
  · 但 cosine 阈值做闸门不行（「介绍一下骰子」0.528 > 好几条真查询）
  · 「向量 + 句式守卫、阈值 0.50」→ holdR@3 92%、零纯噪声、契约全过

这个脚本查三件决定「能不能上」的事：
  ① 延迟：模型加载多久？每次 query 多久？（桌宠启动不能被拖慢）
  ② 注入率 31% → 47% 的那 7 条是什么？是合理召回还是过拟合？
  ③ 大库（1411 条）上还灵不灵？（21 条小库可能是特例）
"""
import io
import json
import os
import sys
import time

REPO = r'D:\ai工作站\desktop-pet'
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, 'tools', 'eval', 'gate_study'))

import numpy as np                      # noqa: E402
import onnxruntime as ort               # noqa: E402
from tokenizers import Tokenizer        # noqa: E402

import memory_engine as me              # noqa: E402
import run_study as rs                  # noqa: E402

CACHE = os.path.join(REPO, 'tools', 'eval', 'experiment', '_embed_probe')
DATA = os.path.join(REPO, 'tools', 'eval', 'experiment', 'data')
THR = 0.50
_DEF_PAT = ('是什么', '是啥', '啥意思', '什么意思', '介绍一下', '介绍下',
            '怎么回事', '啥玩意', '是什么东西', '讲讲', '科普')


def line(c='=', n=100):
    print(c * n)


# ══════════════ ① 延迟 ══════════════
line()
print('① 延迟：能不能放进桌宠主流程')
line()

t0 = time.time()
tok = Tokenizer.from_file(os.path.join(CACHE, 'tokenizer.json'))
tok.enable_truncation(max_length=128)
tok.enable_padding(length=128)
t_tok = time.time() - t0

t0 = time.time()
sess = ort.InferenceSession(os.path.join(CACHE, 'model.onnx'),
                            providers=['CPUExecutionProvider'])
t_sess = time.time() - t0
NAMES = [i.name for i in sess.get_inputs()]
print('  tokenizer 加载      %.0f ms' % (t_tok * 1000))
print('  onnx 会话创建       %.0f ms' % (t_sess * 1000))
print('  合计冷启动          %.0f ms  ← 桌宠启动要多等这么久' % ((t_tok + t_sess) * 1000))


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


encode(['预热'])                                     # 首次推理含图优化，单独不算稳态
t0 = time.time()
encode(['预热2'])
print('  首次推理（已预热后）%.0f ms' % ((time.time() - t0) * 1000))

# 稳态：单条 query = 编码 1 条 + 矩阵点积
for n_facts in (21, 200, 1411, 5000, 20000):
    mat = np.random.rand(n_facts, 512).astype(np.float32)
    mat /= np.linalg.norm(mat, axis=1, keepdims=True)
    ts = []
    for _ in range(30):
        t0 = time.perf_counter()
        qv = encode(['我大几了'])[0]
        _sims = mat @ qv
        _o = np.argsort(-_sims)[:3]
        ts.append((time.perf_counter() - t0) * 1000)
    ts.sort()
    print('  query 延迟（%5d 条事实库）中位 %5.2f ms / p90 %5.2f ms'
          % (n_facts, ts[len(ts) // 2], ts[int(len(ts) * 0.9)]))

# ══════════════ ② 注入率上涨的明细 ══════════════
line()
print('② 注入率 31% → 47%：多出来的 7 条是什么')
line()
FACTS = [f for f in json.loads(io.open(os.path.join(REPO, 'memory.json'),
                                      encoding='utf-8').read())['facts']
         if f.get('status', 'active') == 'active']
FT = [(f.get('content') or '').strip() for f in FACTS]
FV = encode(FT)
msgs = rs.load_realdist()['messages']


def bm25(q):
    old = (me.GATE_MIN_MATCHED, me.GATE_MIN_COVERAGE, me.GATE_KEEP_RATIO)
    try:
        return [str(h.get('text') or '') for h in
                me.search_memory_for_injection(FACTS, q, top_k=3)]
    finally:
        me.GATE_MIN_MATCHED, me.GATE_MIN_COVERAGE, me.GATE_KEEP_RATIO = old


def vec(q):
    if any(p in (q or '') for p in _DEF_PAT):
        return []
    qv = encode([q])[0]
    sims = FV @ qv
    order = np.argsort(-sims)
    out = []
    for i in order:
        if sims[i] < THR:
            break
        out.append((FT[int(i)], float(sims[int(i)])))
        if len(out) >= 3:
            break
    return [t for t, _s in out]


new_only = []
lost = []
for m in msgs:
    b = bm25(m['text'])
    v = vec(m['text'])
    if v and not b:
        new_only.append((m['text'], v, encode([m['text']])[0]))
    if b and not v:
        lost.append((m['text'], b))

print('  新增注入 %d 条（BM25 不注入、向量注入）' % len(new_only))
for q, v, _qv in new_only:
    qv = encode([q])[0]
    sims = FV @ qv
    print('    「%s」' % q[:34])
    print('       → cos %.3f  %s' % (sims.max(), v[0][:56]))
print()
print('  丢失注入 %d 条（BM25 注入、向量不注入）' % len(lost))
for q, b in lost:
    sims = FV @ encode([q])[0]
    print('    「%s」 最高 cos %.3f' % (q[:34], sims.max()))
    print('       BM25 当初注入：%s' % b[0][:52])

# ══════════════ ③ 大库是否还灵 ══════════════
line()
print('③ 大库（1411 条合成记忆）上还灵不灵')
line()
big = json.loads(io.open(os.path.join(DATA, 'memories-1411.json'), encoding='utf-8').read())['facts']
BT = [(f.get('content') or f.get('text') or '').strip() for f in big]
BT = [t for t in BT if t]
t0 = time.time()
BV = encode(BT)
t_enc = time.time() - t0
print('  语料 %d 条，全量编码 %.2f s（%.2f ms/条）' % (len(BT), t_enc, t_enc / len(BT) * 1000))
print('  向量内存 %.2f MB（float32）' % (BV.nbytes / 1024 / 1024))

# 用留出集的问题在大库上查：能不能在 1411 条噪声里找回那 21 条真实记忆的对应项
print()
print('  留出集在大库里的定位（看会不会被合成记忆淹没）')
HOLD = rs.load_cases()['holdout']
for c in HOLD:
    qv = encode([c['query']])[0]
    sims = BV @ qv
    order = np.argsort(-sims)[:5]
    texts = [BT[int(i)] for i in order]
    hit5 = rs.hit_any(texts, c['expect_any'])
    top1_s = float(sims[order[0]])
    print('    %-5s top1 cos=%.3f  top5内找到期望=%s  %s'
          % (c['id'], top1_s, '是' if hit5 else '★否', BT[int(order[0])][:44]))

# 速度：1411 条时单次 query
ts = []
for _ in range(30):
    t0 = time.perf_counter()
    qv = encode(['我大几了'])[0]
    _ = BV @ qv
    ts.append((time.perf_counter() - t0) * 1000)
ts.sort()
print()
print('  1411 条时 query 延迟：中位 %.2f ms / p90 %.2f ms'
      % (ts[len(ts) // 2], ts[int(len(ts) * 0.9)]))
