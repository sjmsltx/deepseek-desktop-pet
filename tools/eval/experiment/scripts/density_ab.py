# -*- coding: utf-8 -*-
"""受控实验：语料稠密度对检索的因果影响（2026-11-03）

## 为什么必须做这个

上一轮得到「21 条 33% → 1411 条 0%」，**但那不是受控对比**：
- 用例判据是「期望词出现在 top3」
- 1411 条合成语料里，「小蓝/大蓝/小龙虾」这些期望词**根本不存在**
- 查询「我爱吃什么东西」不含「桃片」二字，BM25 天然匹配不到

⇒ 直接说「语料变密导致检索崩了」是**用 n=1 讲故事**（错误 ⑥）。

## 这个实验怎么做

| 变量 | 控制方式 |
|---|---|
| 语料 | **只用 21 条真实 facts 作底**，逐步混入 N 条合成噪声（N=0/50/200/800/1400） |
| 用例 | **只留期望词在 21 条真库里存在的那些**（桃片/Python/战争雷霆/大二）—— 保证答案真的在库里 |
| 指标 | top3 命中率 + 负样本误命中率 + 平均返回条数 |

这样每次只动「语料条数」一个变量，才能归因。
"""
import io
import json
import os
import random
import sys

import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
OUT = _os.path.dirname(_HERE)                  # 本实验目录（data/ 与 results/ 的父目录）
DATA = _os.path.join(OUT, 'data')              # 只读：语料 / 时间轴 / 1411 条记忆
RESULTS = _os.path.join(OUT, 'results')        # 只写：各脚本的分析结果
REPO = _os.path.dirname(_os.path.dirname(_os.path.dirname(OUT)))  # 仓库根（上溯 3 层）
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import memory_engine as me  # noqa: E402

def _rjson(path):
    """读 JSON。with 包裹 —— 产品代码禁止一行式 open（长驻进程里是真实句柄泄漏）。"""
    with io.open(path, encoding='utf-8') as _f:
        return json.loads(_f.read())


def _wjson(path, obj, **kw):
    """写 JSON（同 _rjson 的理由）。默认 ensure_ascii=False、indent=1。"""
    kw.setdefault('ensure_ascii', False)
    kw.setdefault('indent', 1)
    with io.open(path, 'w', encoding='utf-8', newline='\n') as _f:
        _f.write(json.dumps(obj, **kw) + '\n')




def load_real_facts():
    """21 条真实库（memory.json 的 active 条目）"""
    cands = [os.path.join(REPO, 'memory', 'memory.json'),
             os.path.join(REPO, 'memory.json'),
             os.path.join(REPO, 'data', 'memory.json')]
    for p in cands:
        if os.path.exists(p):
            raw = _rjson(p)
            items = (raw.get('facts') or raw.get('items')) if isinstance(raw, dict) else raw
            if not items:
                continue
            out = [it for it in items if it.get('status') == 'active']
            print('  真实库：%s（%d 条）' % (p, len(out)))
            return out
    raise SystemExit('✗ 找不到 memory.json')


def main():
    print('=' * 78)
    print('受控实验：只改「语料条数」一个变量')
    print('=' * 78)
    real = load_real_facts()
    exp = json.loads(io.open(os.path.join(DATA, 'memories-1411.json'), encoding='utf-8').read())
    noise_pool = exp['facts']
    print('  噪声池：%d 条合成 facts' % len(noise_pool))
    print()

    cases = json.loads(io.open(os.path.join(REPO, 'tools', 'eval', 'cases.json'),
                               encoding='utf-8').read())
    neg = json.loads(io.open(os.path.join(REPO, 'tools', 'eval', 'negatives.json'),
                             encoding='utf-8').read())
    neg_qs = [q for cat, qs in neg['categories'].items() for q in qs]

    # 只留「期望词在真实库文本中存在」的用例 —— 否则答案根本不在库里，测的是幻觉
    real_text = '\n'.join(str(f.get('content') or f.get('text') or '') for f in real)
    usable = {'recall': [], 'holdout': []}
    print('  用例筛选（期望词必须在真实库里出现）：')
    for grp in ('recall', 'holdout'):
        for c in cases[grp]:
            got = [n for n in c['expect_any'] if n in real_text]
            if got:
                usable[grp].append(c)
                print('     ✓ %-5s %-22s → %s' % (c['id'], c['query'][:20], '/'.join(got)))
            else:
                print('     ✗ %-5s %-22s （期望 %s 不在库里，剔除）'
                      % (c['id'], c['query'][:20], '/'.join(c['expect_any'])))
    n_case = sum(len(v) for v in usable.values())
    print('  可用用例 %d 条' % n_case)
    if n_case == 0:
        raise SystemExit('✗ 没有可用用例')

    print()
    print('  %-8s %-8s %-14s %-14s %-12s %s' % (
        '噪声数', '总条数', 'recall命中', 'holdout命中', '负样本误命中', '平均返回条数'))
    print('  ' + '-' * 76)

    rnd = random.Random(20261103)
    rows = []
    for n_noise in (0, 50, 200, 800, 1400):
        pool = noise_pool[:]
        rnd.shuffle(pool)
        # ⚠ 字段名必须是 content —— search_memory 内部读 f['content']，
        #   写成 text 会让整库内容为空，全部用例假性 0 命中（已踩过一次）
        mixed = []
        for f in real:
            mixed.append({'id': str(f.get('id') or 'r'),
                          'content': str(f.get('content') or ''),
                          'status': 'active', 'importance': f.get('importance', 3),
                          'updated_at': f.get('updated_at', '')})
        for i, f in enumerate(pool[:n_noise]):
            mixed.append({'id': 'n%05d' % i, 'content': f.get('content', ''),
                          'status': 'active', 'importance': f.get('importance', 3),
                          'updated_at': f.get('created_at', '')})

        def hit_rate(lst):
            ok = 0
            ret_tot = 0
            for c in lst:
                hits = me.search_memory_for_injection(mixed, c['query'], top_k=3)
                ret_tot += len(hits)
                joined = ' '.join(str(h.get('content') or h.get('text') or '') for h in hits)
                if any(n in joined for n in c['expect_any']):
                    ok += 1
            return ok, ret_tot

        ok_r, ret_r = hit_rate(usable['recall'])
        ok_h, ret_h = hit_rate(usable['holdout'])
        neg_inj = sum(1 for q in neg_qs if me.search_memory_for_injection(mixed, q, top_k=3))
        avg_ret = (ret_r + ret_h) / max(len(usable['recall']) + len(usable['holdout']), 1)
        print('  %-8d %-8d %-14s %-14s %-12s %.1f' % (
            n_noise, len(mixed),
            '%d/%d' % (ok_r, len(usable['recall'])),
            '%d/%d' % (ok_h, len(usable['holdout'])),
            '%d/%d' % (neg_inj, len(neg_qs)), avg_ret))
        rows.append({'noise': n_noise, 'total': len(mixed), 'recall_hit': ok_r,
                     'holdout_hit': ok_h, 'neg_inject': neg_inj, 'avg_returned': round(avg_ret, 2)})

    p = os.path.join(RESULTS, 'density_ab.json')
    _wjson(p, {
        'note': '只改语料条数一个变量；用例限定为期望词在真实库中存在的那些',
        'n_usable_cases': n_case, 'rows': rows}, indent=2)
    print()
    print('  已写 %s' % p)
    return 0


if __name__ == '__main__':
    sys.exit(main())
