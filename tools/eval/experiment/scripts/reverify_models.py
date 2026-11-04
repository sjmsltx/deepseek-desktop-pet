# -*- coding: utf-8 -*-
"""int8 vs fp32 量化一致性（2026-11-04）

## 为什么这是决定性的

复验扫出：0.51 向上只剩 **0.005** 余量（0.515 还 11/12，0.520 就掉 10/12）。
所以真问题是：**余弦值本身有多稳？**

如果换一份等价的模型文件（同权重、只是量化精度不同）余弦就漂 0.01+，
那 0.51 这个数就是「在特定文件上碰巧合适」，不能写进常量。

## 测法

同一批文本，分别用 int8（22.9MB）与 fp32（90.5MB）编码，比：
  ① 逐条余弦差（同一条查询 vs 同一条记忆）
  ② top1 是否换了对象（排序是否稳定）
  ③ 各自的最优阈值区间（要不要为不同量化各配一个阈值）
"""
import io
import json
import os
import sys
import urllib.request

REPO = r'D:\ai工作站\desktop-pet'
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, 'tools', 'eval', 'gate_study'))

import numpy as np                      # noqa: E402
import onnxruntime as ort               # noqa: E402
from tokenizers import Tokenizer        # noqa: E402

import memory_embed as mem              # noqa: E402
import run_study as rs                  # noqa: E402

CACHE = os.path.join(REPO, 'tools', 'eval', 'experiment', '_embed_probe')
URL = 'https://huggingface.co/Xenova/bge-small-zh-v1.5/resolve/main/onnx/model.onnx'
FP32 = os.path.join(CACHE, 'model_fp32.onnx')


def fetch_fp32():
    if os.path.exists(FP32) and os.path.getsize(FP32) > 10_000_000:
        return FP32
    print('  下载 fp32（约 90MB）…')
    req = urllib.request.Request(URL, headers={'User-Agent': 'eval/1.0'})
    with urllib.request.urlopen(req, timeout=300) as r, open(FP32, 'wb') as f:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)
    print('  完成 %.1f MB' % (os.path.getsize(FP32) / 1024 / 1024))
    return FP32


def make_session(path):
    tok = Tokenizer.from_file(os.path.join(CACHE, 'tokenizer.json'))
    tok.enable_truncation(max_length=mem.MAX_TOKENS)
    tok.enable_padding(length=mem.MAX_TOKENS)
    sess = ort.InferenceSession(path, providers=['CPUExecutionProvider'])
    names = [i.name for i in sess.get_inputs()]

    def enc(texts):
        items = [str(t or ' ') for t in texts]
        e = tok.encode_batch(items)
        ids = np.array([x.ids for x in e], dtype=np.int64)
        m = np.array([x.attention_mask for x in e], dtype=np.int64)
        feed = {}
        for n in names:
            feed[n] = ids if n == 'input_ids' else (m if n == 'attention_mask'
                                                    else np.zeros_like(ids))
        v = sess.run(None, feed)[0][:, 0, :]
        return (v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)).astype('float32')

    return enc


def line(c='=', n=96):
    print(c * n)


fp32_path = fetch_fp32()
enc_i8 = make_session(os.path.join(CACHE, 'model.onnx'))
enc_f32 = make_session(fp32_path)

FACTS = [f for f in json.loads(io.open(os.path.join(REPO, 'memory.json'),
                                      encoding='utf-8').read())['facts']
         if f.get('status', 'active') == 'active']
FT = [(f.get('content') or '').strip() for f in FACTS]
HOLD = rs.load_cases()['holdout']

line()
print('① 同一条记忆、同一句查询：两种量化的余弦差')
line()
VI, VF = enc_i8(FT), enc_f32(FT)
diffs = []
print('  %-5s %-24s %-9s %-9s %-8s %-9s' % ('id', '问法', 'int8', 'fp32', '差', 'top1 是否同'))
print('  ' + '-' * 76)
same_top1 = 0
for c in HOLD:
    qi = enc_i8([c['query']])[0]
    qf = enc_f32([c['query']])[0]
    si, sf = VI @ qi, VF @ qf
    ii, iff = int(np.argmax(si)), int(np.argmax(sf))
    d = float(sf[iff] - si[ii])
    diffs.append(abs(d))
    same = (ii == iff)
    same_top1 += 1 if same else 0
    print('  %-5s %-24s %-9.4f %-9.4f %+9.4f %s'
          % (c['id'], c['query'][:24], si[ii], sf[iff], d,
             '是' if same else '★否（int8→%s / fp32→%s）'
             % (FT[ii][:10], FT[iff][:10])))
print()
print('  |差| 中位 %.4f / 最大 %.4f' % (float(np.median(diffs)), max(diffs)))
print('  top1 一致 %d/12' % same_top1)

line()
print('② 逐维度余弦的整体分布是否平移（决定阈值要不要跟着挪）')
line()
all_i, all_f = [], []
for c in HOLD:
    si = VI @ enc_i8([c['query']])[0]
    sf = VF @ enc_f32([c['query']])[0]
    all_i.extend(si.tolist())
    all_f.extend(sf.tolist())
ai, af = np.array(all_i), np.array(all_f)
print('  int8  余弦 均值 %.4f / 中位 %.4f / 标准差 %.4f'
      % (ai.mean(), np.median(ai), ai.std()))
print('  fp32  余弦 均值 %.4f / 中位 %.4f / 标准差 %.4f'
      % (af.mean(), np.median(af), af.std()))
print('  整体平移（均值差）%+.4f' % (af.mean() - ai.mean()))
print('  ⇒ %s'
      % ('有系统平移，阈值需要跟着调'
         if abs(af.mean() - ai.mean()) > 0.01 else '无系统平移，阈值可跨量化沿用'))

line()
print('③ 两种量化各自的最优阈值区间（11/12 那一档落在哪）')
line()
MSGS = rs.load_realdist()['messages']


def sweep(enc, vecs):
    out = []
    for t in [round(0.40 + 0.005 * k, 3) for k in range(41)]:
        hit = 0
        for c in HOLD:
            qv = enc([c['query']])[0]
            sims = vecs @ qv
            order = np.argsort(-sims)[:3]
            if rs.hit_any([FT[int(j)] for j in order], c['expect_any']):
                hit += 1
        if hit == 11 or (hit == 12 and not out):
            out.append((t, hit))
    return out


for name, enc, vecs in (('int8', enc_i8, VI), ('fp32', enc_f32, VF)):
    rows = []
    for t in [round(0.40 + 0.005 * k, 3) for k in range(41)]:
        hit = 0
        for c in HOLD:
            qv = enc([c['query']])[0]
            sims = vecs @ qv
            order = np.argsort(-sims)[:3]
            if sims[order[0]] < t:
                continue
            if rs.hit_any([FT[int(j)] for j in order], c['expect_any']):
                hit += 1
        rows.append((t, hit))
    best = max(h for _t, h in rows)
    band = [t for t, h in rows if h == best]
    print('  %-6s 最高 %d/12，区间 %.3f ~ %.3f' % (name, best, band[0], band[-1]))

line()
print('④ 结论（数据算出来的，不是手写）')
line()
