# -*- coding: utf-8 -*-
"""「注入但未引用」统计报告
============================
用法：
    python tools/eval/memory_usage_report.py            # 全量
    python tools/eval/memory_usage_report.py --days 7   # 只看最近 7 天
    python tools/eval/memory_usage_report.py --csv out.csv

数据来源：`logs/memory_ledger.jsonl`（由 memory_usage 写入，见该模块头部的口径说明）。

⛔ 报告里的比例是**词面代理**，不是"准确引用率"：
   · 同义改写会漏判
   · 同名会误判
   · 无针记忆（短、无专名）恒判未引用 —— 所以单列，不进主分母
"""
import argparse
import collections
import csv
import datetime
import io
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import memory_ledger as ledger    # noqa: E402


def _parse_ts(s):
    try:
        return datetime.datetime.fromisoformat(str(s))
    except (TypeError, ValueError):
        return None


def load(days=0):
    rows = ledger.read_all()
    if not days:
        return rows
    cut = datetime.datetime.now() - datetime.timedelta(days=int(days))
    out = []
    for r in rows:
        t = _parse_ts(r.get('ts'))
        if t is None or t >= cut:
            out.append(r)
    return out


def summarize(rows):
    inj = [r for r in rows if r.get('kind') == 'inject']
    use = {r.get('turn'): r for r in rows if r.get('kind') == 'usage'}
    per_fact = collections.defaultdict(lambda: {'injected': 0, 'used': 0, 'text': ''})
    why = collections.Counter()
    n_turn = n_turn_used = 0
    n_fact = n_used = n_no_needle = 0

    for r in inj:
        turn = r.get('turn')
        u = use.get(turn)
        n_turn += 1
        if u and u.get('referenced'):
            n_turn_used += 1
        items = {it.get('id'): it for it in (u or {}).get('items', [])}
        for f in r.get('facts', []):
            fid = str(f.get('id') or '')
            n_fact += 1
            rec = per_fact[fid]
            rec['injected'] += 1
            rec['text'] = rec['text'] or f.get('text', '')
            it = items.get(fid)
            if it:
                why[it.get('why')] += 1
                if it.get('why') == 'no_needle':
                    n_no_needle += 1
                if it.get('referenced'):
                    n_used += 1
                    rec['used'] += 1

    # 有 usage 但没对上 inject 的（例如进程中断），单独提示
    orphan = sum(1 for k in use if k and k not in {r.get('turn') for r in inj})
    return {
        'turns_injected': n_turn,
        'turns_with_use': n_turn_used,
        'fact_injected': n_fact,
        'fact_used': n_used,
        'no_needle': n_no_needle,
        'why': dict(why),
        'per_fact': dict(per_fact),
        'orphan_usage': orphan,
        'usage_rows': len(use),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description='「注入但未引用」统计')
    ap.add_argument('--days', type=int, default=0, help='只看最近 N 天（0=全部）')
    ap.add_argument('--csv', default='', help='把每条记忆的注入/引用次数导出为 CSV')
    ap.add_argument('--top', type=int, default=15, help='按注入次数列前 N 条')
    a = ap.parse_args(argv)

    rows = load(a.days)
    if not rows:
        print('台账里还没有数据（%s）。' % ledger.path())
        print('说明：需要先真实使用一段时间 —— 每次注入写一行 inject，回复落地写一行 usage。')
        return 0

    s = summarize(rows)
    print('=' * 78)
    print('记忆使用台账：%s' % ledger.path())
    print('=' * 78)
    print('  记录行数          %d（inject %d / usage %d）'
          % (len(rows), s['turns_injected'], s['usage_rows']))
    if s['turns_injected']:
        print('  有注入的轮次      %d' % s['turns_injected'])
        print('  其中至少用上一条  %d = %.0f%%'
              % (s['turns_with_use'], 100.0 * s['turns_with_use'] / s['turns_injected']))
    if s['fact_injected']:
        print('  注入条目总数      %d' % s['fact_injected'])
        print('  被判引用          %d = %.0f%%'
              % (s['fact_used'], 100.0 * s['fact_used'] / s['fact_injected']))
        print('  无针（判不了）    %d = %.0f%%  ← 单列，不进上面分母的"应被用上"部分'
              % (s['no_needle'], 100.0 * s['no_needle'] / s['fact_injected']))
    if s['why']:
        print('  判定分布          %s' % s['why'])
    if s['orphan_usage']:
        print('  ⚠ 有 %d 条 usage 找不到对应 inject（多半是进程中途退出）' % s['orphan_usage'])

    per = sorted(s['per_fact'].items(), key=lambda kv: -kv[1]['injected'])
    if per:
        print()
        print('-' * 78)
        print('按注入次数排序（前 %d）' % a.top)
        print('-' * 78)
        for fid, rec in per[:a.top]:
            rate = (100.0 * rec['used'] / rec['injected']) if rec['injected'] else 0.0
            print('  %3d 次注入 / %3d 次引用（%3.0f%%）  %s'
                  % (rec['injected'], rec['used'], rate, rec['text'][:46]))
        never = [(fid, r) for fid, r in per if r['injected'] >= 3 and r['used'] == 0]
        if never:
            print()
            print('  ⚠ 注入 ≥3 次但从未被引用（值得怀疑是"注入了却没用"）：%d 条' % len(never))
            for fid, r in never[:10]:
                print('     %s' % r['text'][:60])

    if a.csv:
        with io.open(a.csv, 'w', encoding='utf-8-sig', newline='') as fh:
            w = csv.writer(fh)
            w.writerow(['id', 'injected', 'used', 'text'])
            for fid, rec in per:
                w.writerow([fid, rec['injected'], rec['used'], rec['text']])
        print()
        print('已导出 %d 条 → %s' % (len(per), a.csv))
    return 0


if __name__ == '__main__':
    sys.exit(main())
