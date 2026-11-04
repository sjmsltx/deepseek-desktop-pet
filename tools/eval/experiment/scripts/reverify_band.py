# -*- coding: utf-8 -*-
"""修 reverify_threshold.py 的 ② 段：稳健带必须扫出来，不能手推（2026-11-04）

## 为什么改

上一版我在 ② 里写了：

    ⇒ 阈值可安全下探到 0.439
    ★ 稳健带：阈值取 (0.439, 0.439] 之间 —— 上下界印成同一个数
      当前 0.51 距下界仅 0.071 ⇒ 余量够

三个毛病：
  1. 上下界变量写错，印出来是同一个数（无意义）
  2. 拿「最小正确余弦」当唯一边界 ⇒ 只看到向下安全，没看**向上**什么时候崩
     真正危险的方向是往上：h06 只有 0.515，0.51 距它 0.005
  3. 用 top1 余弦推 R@3 是偷换口径 —— R@3 走的是 top3

⇒ 改成**按真实检索行为扫一遍**：每个阈值跑 12 条，数 R@3，
   同时记注入率，把「仍是 11/12 的区间」和「跌到 10/12 的点」都扫出来。
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
import run_study as rs                  # noqa: E402

e = mem.get_embedder()
assert e.ok
CUR = mem.DEFAULT_THRESHOLD

FACTS = [f for f in json.loads(io.open(os.path.join(REPO, 'memory.json'),
                                      encoding='utf-8').read())['facts']
         if f.get('status', 'active') == 'active']
FT = [(f.get('content') or '').strip() for f in FACTS]
FV = e.encode(FT)
HOLD = rs.load_cases()['holdout']
MSGS = rs.load_realdist()['messages']


def run(thr):
    hit = 0
    miss = []
    for c in HOLD:
        res = e.search(c['query'], FV, FT, k=3, threshold=thr)
        if rs.hit_any([r['text'] for r in res][:3], c['expect_any']):
            hit += 1
        else:
            miss.append(c['id'])
    inj = sum(1 for m in MSGS if e.search(m['text'], FV, FT, k=3, threshold=thr))
    return hit, miss, inj


print('=' * 92)
print('② 稳健带（按真实 R@3 扫描，步长 0.005）')
print('=' * 92)
print('  %-8s %-9s %-8s %-8s %s' % ('阈值', 'holdR@3', '注入率', '漏了谁', '备注'))
print('  ' + '-' * 84)

rows = []
thr = 0.40
while thr <= 0.6001:
    t = round(thr, 3)
    h, miss, inj = run(t)
    rows.append((t, h, inj, miss))
    note = ''
    if abs(t - CUR) < 1e-9:
        note = '← 当前'
    print('  %-8.3f %-9s %-8s %-8s %s'
          % (t, '%d/12' % h, '%.0f%%' % (100.0 * inj / len(MSGS)),
             ','.join(miss) or '—', note))
    thr += 0.005

# 结论区：按「当前召回档」算带，不手写结论
cur_row = [r for r in rows if abs(r[0] - CUR) < 1e-9][0]
cur_h = cur_row[1]
band_cur = [t for t, h, _i, _m in rows if h == cur_h]
gap_up = band_cur[-1] - CUR
gap_dn = CUR - band_cur[0]
print()
print('  当前 %.3f 达到 %d/12。' % (CUR, cur_h))
print('  同样 %d/12 的阈值区间：%.3f ~ %.3f（共 %d 档）'
      % (cur_h, band_cur[0], band_cur[-1], len(band_cur)))
print('    向下余量 %.3f（阈值压到 %.3f 以下才开始掉档）' % (gap_dn, band_cur[0]))
nxt = round(band_cur[-1] + 0.005, 3)
nxt_h = [h for t, h, _i, _m in rows if abs(t - nxt) < 1e-9]
print('    向上余量 %.3f（阈值抬到 %.3f 就掉到 %s/12）'
      % (gap_up, nxt, (nxt_h[0] if nxt_h else cur_h)))
if gap_up < 0.02:
    print()
    print('  ⇒ 向上只剩 %.3f，太薄。换量化/换模型/库变化都可能把余弦整体推高，'
          % gap_up)
    print('    一旦越过 %.3f 就掉档 ⇒ 要么把阈值下移到带中段，'
          % nxt)
    print('    要么先证明余弦分布稳定（见 reverify_models.py 的 int8/fp32 对比）。')
else:
    print()
    print('  ⇒ 向上余量 %.3f，可接受。' % gap_up)

same = [r for r in rows if r[1] == cur_h]
lowest_inj = min(same, key=lambda r: r[2])
highest_inj = max(same, key=lambda r: r[2])
print()
print('  同样 %d/12 的范围里：注入率最低 %.0f%%（阈值 %.3f），最高 %.0f%%（阈值 %.3f）'
      % (cur_h, 100.0 * lowest_inj[2] / len(MSGS), lowest_inj[0],
         100.0 * highest_inj[2] / len(MSGS), highest_inj[0]))
print('  ⇒ 召回封顶后，阈值只用来换注入率；往上换余量会变薄，不是免费的。')
