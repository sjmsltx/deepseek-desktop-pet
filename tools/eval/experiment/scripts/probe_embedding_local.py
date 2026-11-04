# -*- coding: utf-8 -*-
"""embedding 可行性实测（2026-11-04）

## 为什么真的下载模型跑

Owner 问「embedding 评估一下」。只讲理论没用 ——
本地就有 onnxruntime + tokenizers，模型只有 22.9MB（int8），
所以**真的跑一遍**，用同一批数据对比词面与向量的表现。

## 测什么

1. 同义改写对（40+40 条，来自 eval_embedding.py 的实验一）：
   词面 jaccard 只认出 80% / 12%，向量 cosine 能认出多少？
2. 现有强边对（80 条，已有 LLM 判定 related true/false）：
   向量能否区分？现有词面 precision 65%，向量能到多少？
3. 速度与体积：编码 1 条要多久、模型多大。

## 模型

Xenova/bge-small-zh-v1.5 的 int8 量化 ONNX（22.9MB，512 维，中文专用）
tokenizer.json 0.42MB
"""
import io
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(HERE)
RESULTS = os.path.join(EXP, 'results')
CACHE = os.path.join(EXP, '_embed_probe')      # 评测缓存，不进仓库
REPO = os.path.dirname(os.path.dirname(os.path.dirname(EXP)))
sys.path.insert(0, REPO)

BASE = 'https://huggingface.co/Xenova/bge-small-zh-v1.5/resolve/main/'
FILES = {
    'model.onnx': 'onnx/model_quantized.onnx',
    'tokenizer.json': 'tokenizer.json',
}
EVAL_JSON = os.path.join(RESULTS, 'embedding-eval.json')


def fetch(name):
    os.makedirs(CACHE, exist_ok=True)
    dst = os.path.join(CACHE, name)
    if os.path.exists(dst) and os.path.getsize(dst) > 1000:
        return dst
    url = BASE + FILES[name]
    print('  下载 %s ← %s' % (name, url))
    t0 = time.time()
    req = urllib.request.Request(url, headers={'User-Agent': 'eval/1.0'})
    with urllib.request.urlopen(req, timeout=180) as r, open(dst, 'wb') as f:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)
    print('    完成 %.1f MB / %.1fs' % (os.path.getsize(dst) / 1024 / 1024, time.time() - t0))
    return dst


def main():
    import numpy as np
    import onnxruntime as ort
    from tokenizers import Tokenizer

    print('=' * 74)
    print('准备模型')
    print('=' * 74)
    mp = fetch('model.onnx')
    tp = fetch('tokenizer.json')
    tok = Tokenizer.from_file(tp)
    tok.enable_truncation(max_length=128)
    tok.enable_padding(length=128)      # 固定长度：量化模型对动态形状支持不稳
    sess = ort.InferenceSession(mp, providers=['CPUExecutionProvider'])
    in_names = [i.name for i in sess.get_inputs()]
    print('  模型输入：%s' % in_names)
    print('  模型大小 %.2f MB' % (os.path.getsize(mp) / 1024 / 1024))

    def encode(texts):
        encs = tok.encode_batch([t or ' ' for t in texts])
        ids = np.array([e.ids for e in encs], dtype=np.int64)
        mask = np.array([e.attention_mask for e in encs], dtype=np.int64)
        feed = {}
        for n in in_names:
            if n == 'input_ids':
                feed[n] = ids
            elif n == 'attention_mask':
                feed[n] = mask
            elif n == 'token_type_ids':
                feed[n] = np.zeros_like(ids)
        out = sess.run(None, feed)[0]          # last_hidden_state
        v = out[:, 0, :]                        # bge 用 CLS 池化
        v = v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)
        return v

    def cos(a, b):
        return float(np.dot(a, b))

    # ---------- 速度 ----------
    print()
    print('=' * 74)
    print('速度')
    print('=' * 74)
    probe = ['用户爱吃重庆合川桃片，偏好甜味、老工艺、现切的'] * 16
    encode(probe)                               # 预热
    t0 = time.time()
    N = 64
    encode(['测试句子 %d：用户在学习遥感原理课程' % i for i in range(N)])
    dt = (time.time() - t0) / N * 1000
    print('  编码 1 条（batch=64，128 token）：%.2f ms' % dt)
    for n in (400, 1417, 5000, 50000):
        print('    %6d 条 → %.2f s' % (n, n * dt / 1000))

    # ---------- 读评测数据 ----------
    d = _rjson(EVAL_JSON)
    para = d['paraphrase']
    edges = d['edge_precision']

    print()
    print('=' * 74)
    print('① 同义改写：向量能否认出「语义相同」')
    print('=' * 74)
    # 建议阈值：用 B 变体（纯语义改写）的中位数 + 余量。先算分布再定，不拍脑袋。
    for key in para:
        rows = para[key]['rows']
        if not rows:
            continue
        vs = encode([r['src'] for r in rows] + [r['para'] for r in rows])
        n = len(rows)
        sims = [cos(vs[i], vs[n + i]) for i in range(n)]
        arr = sorted(sims)
        med = arr[len(arr) // 2]
        print('  %s（%d 对）' % (key, n))
        print('    词面：认出 %d/%d = %.0f%%'
              % (para[key]['pass'], n, para[key]['recall_pct']))
        print('    向量 cosine：中位 %.3f / 最小 %.3f / 最大 %.3f'
              % (med, arr[0], arr[-1]))
        for thr in (0.70, 0.80, 0.85, 0.90):
            hit = sum(1 for s in sims if s >= thr)
            print('      阈值 %.2f → 认出 %d/%d = %.0f%%' % (thr, hit, n, 100.0 * hit / n))

    # ---------- ② 边的 precision ----------
    print()
    print('=' * 74)
    print('② 现有强边：向量能否区分「真相关 / 误连」')
    print('=' * 74)
    rows = edges['rows']
    if rows:
        va = encode([r['a'] for r in rows])
        vb = encode([r['b'] for r in rows])
        sims = [cos(va[i], vb[i]) for i in range(len(rows))]
        rel = [r['related'] for r in rows]
        npos = sum(1 for x in rel if x)
        nneg = len(rel) - npos
        print('  样本 %d 条（LLM 判定：相关 %d / 不相关 %d），词面 precision = %.0f%%'
              % (len(rows), npos, nneg, edges['precision_pct']))
        if npos and nneg:
            ps = sorted(s for s, r in zip(sims, rel) if r)
            ns = sorted(s for s, r in zip(sims, rel) if not r)
            print('  相关对 cosine：中位 %.3f（最小 %.3f）' % (ps[len(ps) // 2], ps[0]))
            print('  不相关 cosine：中位 %.3f（最大 %.3f）' % (ns[len(ns) // 2], ns[-1]))
            # 选阈值：最大化「precision 提升且不丢太多真边」
            print()
            print('  %-8s %-12s %-12s %s' % ('阈值', '保留相关', '剔除误连', 'precision'))
            print('  ' + '-' * 54)
            for thr in (0.50, 0.60, 0.65, 0.70, 0.75, 0.80):
                kept = [(s, r) for s, r in zip(sims, rel) if s >= thr]
                kr = sum(1 for _s, r in kept if r)
                prec = 100.0 * kr / max(len(kept), 1)
                rec = 100.0 * kr / max(npos, 1)
                drop = 100.0 * (1 - sum(1 for _s, r in kept if not r) / max(nneg, 1))
                print('  %-8.2f %-12s %-12s %.0f%%（召回 %.0f%%）'
                      % (thr, '%d/%d' % (kr, npos), '%.0f%%' % drop, prec, rec))

    # ---------- ③ 混用：词面 + 向量 ----------
    print()
    print('=' * 74)
    print('③ 组合口径（词面 OR 向量 / 词面 AND 向量）')
    print('=' * 74)
    d2 = _rjson(EVAL_JSON)
    rows_a = d2['paraphrase'].get('A_允许保留专名', {}).get('rows', [])
    rows_b = d2['paraphrase'].get('B_连专名也换成描述', {}).get('rows', [])
    for tag, rr in (('A', rows_a), ('B', rows_b)):
        if not rr:
            continue
        vs = encode([r['src'] for r in rr] + [r['para'] for r in rr])
        n = len(rr)
        print('  变体 %s：' % tag)
        for name, fn in (
                ('纯词面（现况）', lambda i: rr[i]['pass']),
                ('纯向量≥0.70', lambda i: cos(vs[i], vs[n + i]) >= 0.70),
                ('词面 OR 向量', lambda i: rr[i]['pass'] or cos(vs[i], vs[n + i]) >= 0.70),
                ('词面 AND 向量', lambda i: rr[i]['pass'] and cos(vs[i], vs[n + i]) >= 0.70),
        ):
            k = sum(1 for i in range(n) if fn(i))
            print('    %-16s 认出 %d/%d = %.0f%%' % (name, k, n, 100.0 * k / n))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
