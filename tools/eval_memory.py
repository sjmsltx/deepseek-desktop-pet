# -*- coding: utf-8 -*-
"""tools/eval_memory.py —— 记忆质量回归集（只读，不改任何记忆文件）

## 为什么有这个文件

WX-168 §五 建议2 / WX-170 §三 第1条：本项目**全仓 0 条**记忆质量回归用例，
改 BM25 阈值、改闸门、改衰减，全靠手感 —— 而记忆系统最容易「改着改着就悄悄变差」：
不报错，召回却开始给错答案。

上游项目 whale-card 的 `tools/eval/cases.json` 是这套做法的来源（22 条 + 四类指标）。
本文件按同样的四类分法，但用例全部用**本机真实库**写，不是编的样例。

## 五类指标

| 键 | 测什么 | 判据 |
|---|---|---|
| R@1 / R@3 | 该命中的有没有进前 1 / 前 3 | 期望片段出现在 content 里 |
| EVID | 召回的必须是**原文** | 每条 content 必须与库里某条逐字一致 |
| FALSE | 无关的话不许命中 | 返回必须为空 |
| NOISE | 可重算播报不许当记忆召回 | must_not_hit 一条都不许出现 |
| SUPERSEDED | 失效事实不许冒充现状 | 同上 |

## 用法

    python tools\\eval_memory.py            # 人读
    python tools\\eval_memory.py --json     # 机器读（tests/test_memory_eval.py 用）

⛔ 只读：本文件不写 memory.json / memories.json，也不调 memorize。
"""
import argparse
import io
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

FACTS_PATH = os.path.join(BASE, 'memory.json')
CASES_PATH = os.path.join(BASE, 'tools', 'eval', 'cases.json')


def load_facts():
    """读真实事实库。读不到就返回空表（不造假数据 —— 空表的评估结果是『未测』）。"""
    if not os.path.exists(FACTS_PATH):
        return []
    with io.open(FACTS_PATH, encoding='utf-8') as fh:
        d = json.load(fh)
    facts = d.get('facts') if isinstance(d, dict) else d
    return facts or []


def load_cases():
    with io.open(CASES_PATH, encoding='utf-8') as fh:
        return json.load(fh)


def _has_any(text, needles):
    return any(n in text for n in needles)


def run(facts=None, cases=None, top_k=3):
    import memory_engine as me

    facts = facts if facts is not None else load_facts()
    cases = cases if cases is not None else load_cases()
    active_texts = [str(f.get('content') or '') for f in facts
                    if f.get('status', 'active') == 'active']

    out = {'recall': [], 'holdout': [], 'evidence': [], 'false': [], 'noise': [],
           'superseded': [], 'counts': {}, 'ok': True}

    # ---------- recall（开发集）----------
    for c in cases.get('recall', []):
        hits = me.search_memory_for_injection(facts, c['query'], top_k=top_k)
        texts = [str(h.get('text') or '') for h in hits]
        r1 = bool(texts) and _has_any(texts[0], c['expect_any'])
        r3 = _has_any(' '.join(texts[:3]), c['expect_any'])
        out['recall'].append({'id': c['id'], 'query': c['query'], 'r1': r1, 'r3': r3,
                              'top': [t[:40] for t in texts]})
        # ---------- evidence（与 recall 同源，复用一次检索结果）----------
        bad = [t for t in texts if t not in active_texts]
        out['evidence'].append({'id': c['id'], 'verbatim': not bad, 'bad': bad[:2]})

    # ---------- holdout（选参时不参与，选完才验收；防「对着答案调参」）----------
    for c in cases.get('holdout', []):
        hits = me.search_memory_for_injection(facts, c['query'], top_k=top_k)
        texts = [str(h.get('text') or '') for h in hits]
        out['holdout'].append({'id': c['id'], 'query': c['query'],
                               'r1': bool(texts) and _has_any(texts[0], c['expect_any']),
                               'r3': _has_any(' '.join(texts[:3]), c['expect_any']),
                               'top': [t[:40] for t in texts]})

    # ---------- false ----------
    for c in cases.get('false', []):
        hits = me.search_memory_for_injection(facts, c['query'], top_k=top_k)
        out['false'].append({'id': c['id'], 'query': c['query'],
                             'empty': len(hits) == 0,
                             'top': [str(h.get('text') or '')[:40] for h in hits]})

    # ---------- noise ----------
    for c in cases.get('noise', []):
        hits = me.search_memory_for_injection(facts, c['query'], top_k=top_k)
        texts = [str(h.get('text') or '') for h in hits]
        out['noise'].append({'id': c['id'], 'query': c['query'],
                             'clean': not _has_any(' '.join(texts), c.get('must_not_hit', [])),
                             'top': [t[:40] for t in texts]})

    # ---------- superseded ----------
    for c in cases.get('superseded', []):
        hits = me.search_memory_for_injection(facts, c['query'], top_k=top_k)
        texts = [str(h.get('text') or '') for h in hits]
        out['superseded'].append({'id': c['id'], 'query': c['query'],
                                  'clean': not _has_any(' '.join(texts), c.get('must_not_hit', [])),
                                  'top': [t[:40] for t in texts]})

    n = len(out['recall']) or 1
    hn = len(out['holdout']) or 1
    out['counts'] = {
        'facts_active': len(active_texts),
        'R@1': round(sum(1 for x in out['recall'] if x['r1']) / n, 3),
        'R@3': round(sum(1 for x in out['recall'] if x['r3']) / n, 3),
        'H_R@1': round(sum(1 for x in out['holdout'] if x['r1']) / hn, 3),
        'H_R@3': round(sum(1 for x in out['holdout'] if x['r3']) / hn, 3),
        'EVID': round(sum(1 for x in out['evidence'] if x['verbatim']) / n, 3),
        'FALSE': round(sum(1 for x in out['false'] if x['empty']) / (len(out['false']) or 1), 3),
        'NOISE': round(sum(1 for x in out['noise'] if x['clean']) / (len(out['noise']) or 1), 3),
        'SUPERSEDED': round(sum(1 for x in out['superseded'] if x['clean'])
                            / (len(out['superseded']) or 1), 3),
    }
    out['ok'] = all(v == 1.0 for k, v in out['counts'].items()
                    if k not in ('facts_active', 'R@1', 'R@3', 'H_R@1', 'H_R@3'))
    return out


def main():
    ap = argparse.ArgumentParser(description='记忆质量回归集（只读）')
    ap.add_argument('--json', action='store_true', help='输出 JSON')
    ap.add_argument('--top-k', type=int, default=3)
    a = ap.parse_args()

    r = run(top_k=a.top_k)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0 if r['ok'] else 1

    c = r['counts']
    print('=== 记忆质量回归集（真实库 %d 条 active facts）===' % c['facts_active'])
    print()
    print('%s' % ('-' * 66))
    print('%-12s %-6s %s' % ('指标', '值', '说明'))
    print('%s' % ('-' * 66))
    for k, desc in (('R@1', '开发集：命中的进了第 1 条'), ('R@3', '开发集：命中的进了前 3'),
                    ('H_R@1', '留出集：命中的进了第 1 条'), ('H_R@3', '留出集：命中的进了前 3'),
                    ('EVID', '召回的是原文，不是编的'),
                    ('FALSE', '无关的话没命中'), ('NOISE', '可重算播报没被召回'),
                    ('SUPERSEDED', '失效事实没冒充现状')):
        flag = '✓' if c[k] == 1.0 else '✗'
        print('%-12s %-6s %s %s' % (k, '%.0f%%' % (c[k] * 100), flag, desc))
    print()
    for grp in ('recall', 'holdout', 'false', 'noise', 'superseded'):
        bad = [x for x in r[grp] if not (x.get('r3', x.get('empty', x.get('clean', True))))]
        if bad:
            print('[%s] 未达标 %d 条：' % (grp, len(bad)))
            for x in bad:
                print('   %s  %r  → 实际 %r' % (x['id'], x['query'], x.get('top')))
    print()
    print('结论：%s' % ('✓ 全部达标' if r['ok'] else '✗ 有未达标项（上面已列）'))
    return 0 if r['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
