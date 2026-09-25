# -*- coding: utf-8 -*-
"""rt_cost_sandbox.py - 「圆桌/harness」成本沙盘(**可复现** ✓)

为什么要有它(2026-09-25 交叉复核结论):
  我方 token 模型曾被指出两处问题 -- 1 输入/输出**混算** ✗ 2 全量入上下文时输入是
  **二次增长**(第 k 轮送的是累积历史 ≈ k·N·T)✗。本脚本据此**拆开算**并用**精确求和**。

价格**不写死** ✗:单一来源 = 仓库 `api_stats.PRICES`(模型档案/配置可覆盖 ✓)。

用法:
    python tools/rt_cost_sandbox.py                      # 默认 10 角色 × 20 轮 × 300 tok
    python tools/rt_cost_sandbox.py --roles 3 --rounds 50
    python tools/rt_cost_sandbox.py --peak               # 高峰时段(价 ×2)
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import api_stats  # noqa: E402  价表唯一来源 ✓


def _prices():
    """价表(单一来源 = 仓库 `api_stats.ApiStats.PRICES` ✓ 不写死 ✗)"""
    return getattr(getattr(api_stats, 'ApiStats', None), 'PRICES', None) or {}


def _price(model, key, peak=False):
    p = _prices().get(model) or {}
    return float(p.get(key + ('_peak' if peak else '')) or p.get(key) or 0.0)


def _cost(model, in_tok, cache_tok, out_tok, peak=False):
    """费用(元)= (普通输入×input + 缓存命中×cache + 输出×output) / 1e6"""
    return (in_tok * _price(model, 'input', peak)
            + cache_tok * _price(model, 'cache', peak)
            + out_tok * _price(model, 'output', peak)) / 1e6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--roles', type=int, default=10, help='角色数 N')
    ap.add_argument('--rounds', type=int, default=20, help='群聊轮数 R')
    ap.add_argument('--out-tokens', type=int, default=300, help='每轮输出 token T')
    ap.add_argument('--summary-tokens', type=int, default=20, help='每条摘要 token s')
    ap.add_argument('--near-tokens', type=int, default=1500, help='本角色近段 + 其它固定内容 token（对齐交叉复核口径）')
    ap.add_argument('--window-rounds', type=int, default=5, help='B 摘要窗口封顶轮数（我方设计已封顶 ✓；=0 表示不封顶＝全量摘要历史）')
    ap.add_argument('--models', default='deepseek-flash,deepseek-v4-pro')
    ap.add_argument('--peak', action='store_true', help='高峰时段(价 ×2)')
    a = ap.parse_args()

    N, R, T, S, NEAR = a.roles, a.rounds, a.out_tokens, a.summary_tokens, a.near_tokens
    print('场景:角色 %d × 轮次 %d × 每轮输出 %d tok | 摘要 %d tok/条 | 近段 %d tok | %s时段'
          % (N, R, T, S, NEAR, '高峰' if a.peak else '空闲'))
    print('价表来源:api_stats.PRICES(仓库单一来源 ✓ 不写死 ✗)\n')

    out_tot = R * T                                  # 输出：每轮 1 条发言
    a_exact = N * T * (R * (R - 1) // 2)             # A 精确：Σ_{k=1..R}(k-1)·N·T （二次增长 ✓）
    a_ub = N * T * (R - 1) * R                       # A 上界口径：用“最后一轮输入”×轮数
    # B 每轮输入：摘要常驻（可封顶 ✓）+ 近段/其它固定内容
    w = R if a.window_rounds <= 0 else min(a.window_rounds, R)
    b_sum_pick = N * S * w                           # 每轮装入的摘要（封顶后 ✓）
    b_in_pr = b_sum_pick + NEAR                      # 每轮输入
    b_in = b_in_pr * R                               # 全期输入
    b_cache = b_sum_pick * R                         # 其中可走缓存价的部分

    print('%-18s %12s %12s %12s %12s' % ('模型', 'A-精确输入', 'A-上界输入', 'B-输入', 'B-其中缓存'))
    for m in a.models.split(','):
        print('%-18s %12d %12d %12d %12d' % (m, a_exact, a_ub, b_in, b_cache))
    print('\n%-18s %10s %10s %10s %10s' % ('模型', 'A-精确', 'A-上界', 'B', 'B+缓存'))
    for m in a.models.split(','):
        c_exact = _cost(m, a_exact, 0, out_tot, a.peak)
        c_ub = _cost(m, a_ub, 0, out_tot, a.peak)
        c_b = _cost(m, b_in, 0, out_tot, a.peak)          # B（不走缓存）：全部输入按 input 价
        c_bc = _cost(m, b_in - b_cache, b_cache, out_tot, a.peak)
        print('%-18s %9.4f元 %9.4f元 %9.4f元 %9.4f元' % (m, c_exact, c_ub, c_b, c_bc))
        if c_bc > 0:
            print('%-18s  | A上界/B = %.1f× | B/(B+缓存) = %.2f×'
                  % ('', c_ub / c_b if c_b else 0, c_b / c_bc if c_bc else 0))
    print('\n提示:1"输出 token 占比不小"→ 费用差通常 ≈10-20×,**别把 token 的 102 直接当省钱倍数** ✗')
    print('      2常驻摘要内容稳定 → 走缓存价,是第二把杠杆 ✓')
    print('      3高峰时段价 ×2 → 排到空闲时段再省一半 ✓')


if __name__ == '__main__':
    main()
