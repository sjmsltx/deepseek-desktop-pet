# -*- coding: utf-8 -*-
"""精确网格：找阈值帕累托前沿（2026-11-04）

## 为什么再跑一次

前两轮已经知道：
  · 纯向量 0.50 → holdR@3 92%、零纯噪声、契约过，但注入率 47%（BM25 31%）
  · 「hello」以 cos 0.504 注入「用户在学习 Python」← 这是闸门要治的病，不能无视

⇒ 0.50 与 0.55 之间是真正的权衡带（0.55 时 holdR@3 掉到 67%、注入率降到 22%）。
   一次扫 0.46~0.62（步长 0.01）+ 三个方案，把前沿画出来，别拍脑袋选一个数。

## 三个方案

  A 现况      ：BM25 + coverage 闸门（0.30 / matched 2）
  B 纯向量    ：cosine ≥ thr
  C 混合      ：BM25 过闸 → 直接用；否则向量 ≥ thr 才补
               （字面命中可靠，就用它；漏了才让向量补 —— 各用各的长处）

## ⚠ 本轮要修正上一轮的一个测试设计错误

`probe_vector_checks.py` 的 ③「大库」拿**真实库的期望答案**去 1411 条**无关合成库**里找，
找不到是必然的 —— 那个测试不能证明「大库上不灵」，只能说明合成库里没有这些内容。
本脚本改成只测「top1 余弦分布是否随库大小漂移」（这才是阈值能否迁移的真问题）。
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
import run_study as rs                  # noqa: E402

CACHE = os.path.join(REPO, 'tools', 'eval', 'experiment', '_embed_probe')
DATA = os.path.join(REPO, 'tools', 'eval', 'experiment', 'data')

_DEF_PAT = ('是什么', '是啥', '啥意思', '什么意思', '介绍一下', '介绍下',
            '怎么回事', '啥玩意', '是什么东西', '讲讲', '科普')

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


FACTS = [f for f in json.loads(io.open(os.path.join(REPO, 'memory.json'),
                                      encoding='utf-8').read())['facts']
         if f.get('status', 'active') == 'active']
FT = [(f.get('content') or '').strip() for f in FACTS]
FV = encode(FT)

CASES = rs.load_cases()
DEV, HOLD = CASES['recall'], CASES['holdout']
NEG = rs.load_negatives()
MSGS = rs.load_realdist()['messages']


def bm25(q, top_k=3):
    old = (me.GATE_MIN_MATCHED, me.GATE_MIN_COVERAGE, me.GATE_KEEP_RATIO)
    try:
        return [str(h.get('text') or '') for h in
                me.search_memory_for_injection(FACTS, q, top_k=top_k)]
    finally:
        me.GATE_MIN_MATCHED, me.GATE_MIN_COVERAGE, me.GATE_KEEP_RATIO = old


def vec(q, thr, top_k=3):
    if any(p in (q or '') for p in _DEF_PAT):
        return []
    qv = encode([q])[0]
    sims = FV @ qv
    order = np.argsort(-sims)
    out = []
    for i in order:
        if sims[i] < thr:
            break
        out.append(FT[int(i)])
        if len(out) >= top_k:
            break
    return out


def hybrid(q, thr, top_k=3):
    b = bm25(q, top_k)
    if b:
        return b
    return vec(q, thr, top_k)


#: evaluate 内部测契约时要知道当前阈值（fn 是闭包，拿不到 thr）
CUR_THR = [0.50]


def evaluate(fn, label):
    d = sum(1 for c in DEV if rs.hit_any(fn(c['query'])[:3], c['expect_any']))
    h = sum(1 for c in HOLD if rs.hit_any(fn(c['query'])[:3], c['expect_any']))
    pure = 0
    for c in NEG.get('pure_noise_cases', []):
        if c.get('must_not_hit') and rs.hit_any(fn(c['query']), c['must_not_hit']):
            pure += 1
    # ⚠ 契约必须在 CONTRACT_FACTS 上测（run_study 的原始口径）。
    #   第一版我用真实库测 ⇒ 库里没有「扫雷」条目 ⇒ 必然空 ⇒ 假通过。
    cf = [dict(f) for f in rs.CONTRACT_FACTS]
    cft = [f['content'] for f in cf]
    cfv = encode(cft)

    def cfn(q):
        texts = fn(q)                       # 用真实库跑出的行为不适用于契约，
        if texts:                           # 这里重算：只针对这 2 条虚构事实
            pass
        if any(p in (q or '') for p in _DEF_PAT):
            return []
        qv = encode([q])[0]
        sims = cfv @ qv
        order = np.argsort(-sims)
        out = []
        for i in order:
            if sims[i] < CUR_THR[0]:
                break
            out.append(cft[int(i)])
            if len(out) >= 3:
                break
        return out

    blk = all(len(cfn(q)) == 0 for q in rs.CONTRACT_QUERIES)
    stg = len(cfn(rs.CONTRACT_STRONG)) > 0
    inj = sum(1 for m in MSGS if fn(m['text']))
    return {'label': label, 'dev': d, 'hold': h, 'pure': pure,
            'blocked': blk, 'strong': stg, 'inj': inj,
            'inj_rate': 100.0 * inj / len(MSGS)}


def line(c='=', n=104):
    print(c * n)


line()
print('阈值扫描（★ = 满足「零纯噪声 + 契约全过」；holdR@3 越高越好，注入率越低越好）')
line()
hdr = '  %-10s %-9s %-10s %-7s %-7s %-7s %-8s %s'
print(hdr % ('方案', 'devR@3', 'holdR@3', '纯噪声', '扫雷挡', '强查询', '注入率', '判定'))
print('  ' + '-' * 92)

rows = []
CUR_THR[0] = 0.0
r = evaluate(lambda q: bm25(q), 'A 现况BM25')
rows.append(r)
print(hdr % (r['label'], '%d/6' % r['dev'], '%d/12=%.0f%%' % (r['hold'], r['hold'] / 12 * 100),
             r['pure'], '是' if r['blocked'] else '否', '是' if r['strong'] else '★否',
             '%.0f%%' % r['inj_rate'], '← 基线'))

for tag, maker in (('B 纯向量', vec), ('C 混合', hybrid)):
    print()
    for thr in [x / 100 for x in range(46, 63, 1)]:
        fn = (lambda t: (lambda q: maker(q, t)))(thr)
        CUR_THR[0] = thr
        r = evaluate(fn, '%s %.2f' % (tag, thr))
        r['thr'] = thr
        r['kind'] = tag
        rows.append(r)
        ok = r['pure'] == 0 and r['blocked'] and r['strong']
        print(hdr % (r['label'], '%d/6' % r['dev'],
                     '%d/12=%.0f%%' % (r['hold'], r['hold'] / 12 * 100),
                     r['pure'], '是' if r['blocked'] else '★否',
                     '是' if r['strong'] else '★否', '%.0f%%' % r['inj_rate'],
                     '✓' if ok else '✗'))

line()
print('帕累托前沿：合格档位里，「holdR@3 最高」且「注入率最低」')
line()
good = [r for r in rows if r.get('kind') and r['pure'] == 0 and r['blocked'] and r['strong']]
if good:
    best_hold = max(r['hold'] for r in good)
    cands = [r for r in good if r['hold'] == best_hold]
    print('  合格且 holdR@3 最高（%d/12）：' % best_hold)
    for r in cands:
        print('    %-12s 注入率 %.0f%%（%d/%d）' % (r['label'], r['inj_rate'], r['inj'], len(MSGS)))
    pick = min(cands, key=lambda r: r['inj'])
    print()
    print('  ⇒ 推荐：%s（holdR@3 %d/12、注入率 %.0f%%）'
          % (pick['label'], pick['hold'], pick['inj_rate']))
    print('    对比基线：holdR@3 %d/12 → %d/12，注入率 %.0f%% → %.0f%%'
          % (rows[0]['hold'], pick['hold'], rows[0]['inj_rate'], pick['inj_rate']))
else:
    print('  ⚠ 没有合格档位')

# ---------- 大库的阈值可迁移性（只测分布漂移） ----------
line()
print('库大小是否影响 top1 余弦（阈值能否迁移）')
line()
small = [float((FV @ encode([c['query']])[0]).max()) for c in HOLD]
big = json.loads(io.open(os.path.join(DATA, 'memories-1411.json'), encoding='utf-8').read())['facts']
BT = [(f.get('content') or f.get('text') or '').strip() for f in big]
BT = [t for t in BT if t]
BV = encode(BT)
bigs = [float((BV @ encode([c['query']])[0]).max()) for c in HOLD]
for name, arr in (('真实库 21 条', small), ('合成库 1411 条', bigs)):
    a = sorted(arr)
    print('  %-16s top1余弦 最小 %.3f / 中位 %.3f / 最大 %.3f'
          % (name, a[0], a[len(a) // 2], a[-1]))
print()
print('  ⇒ 两列中位数接近 = 库变大不会把余弦整体抬高 ⇒ 阈值可迁移')
print('     （注意：这只证明「分布不漂移」，不证明「大库里能找回答案」——')
print('      1411 条是无关合成库，里面本来没有这些事实）')
