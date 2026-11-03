# -*- coding: utf-8 -*-
"""闸门改机制验证：稀有词计数（2026-11-03）

## 为什么调参不够

`gate_sweep.py` 证明现有配置 (matched>=2 OR cov>=0.30) 已经站在悬崖边：
- 松一档（m>=2 cov>=0.25）：误命中 15% → 26%
- 再松一档（m>=2 cov>=0.20）：34%
- 降到 m>=1：62%（= 全放开，闸门失效）

**任何线性调参都只能在这个悬崖上滑，跳不过去。** 想同时提召回压误报，必须换机制。

## 换什么机制

根因（`search_detailed` 源码）：
```python
matched = len(qt & set(self.doc_tokens[i]))   # 每个词记 1 分
```

「我」「的」「什么」和「桃片」「Python」**权重完全相同**。密库里高频词遍地都是，
凑够 2 个几乎没有门槛。

**稀有词计数**：只有 `idf(w) > median(idf(query词))` 的命中才算数。
- 「我爱吃啥」→ tokenize 后「我」「爱」「吃」「啥」，全是高频词 ⇒ 一个都不算稀有 ⇒ 不注入（正确）
- 「我叫什么名字」→ 命中「名字」，若「名字」在库里稀有 ⇒ 算 1 分
- 代价：「桃片」类查询若答案是常见词，也会被挡（漏召回）

## 判据

同 `gate_sweep`：容量固定 200 条、5 个随机种子、看 recall / holdout / 误命中三列。
好机制必须在**误命中明显低于 26%** 的前提下，recall 明显高于 2.0/6。
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



CAP = 200
REPEATS = 5


def median(xs):
    s = sorted(xs)
    n = len(s)
    if not n:
        return 0.0
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def rare_matched(qt, doc_tokens, idx):
    """只数「比 query 中位 IDF 更稀有」的命中词"""
    hit = [w for w in set(qt) if w in set(doc_tokens)]
    if not hit:
        return 0, 0.0
    idfs = {w: idx._idf(w) for w in set(qt)}
    q_idf = [v for v in idfs.values()]
    thr = median(q_idf) if q_idf else 0.0
    rare = [w for w in hit if idfs[w] > thr]
    denom = sum(idfs[w] for w in rare) or 1e-9
    doc_tok = set(doc_tokens)
    cov = sum(idfs[w] for w in rare if w in doc_tok) / denom
    return len(rare), cov


def run_recipe(mixed, query, recipe, thr, top_k=3):
    active = [f for f in mixed if f.get('status', 'active') == 'active']
    docs = [{'id': f.get('id', str(i)), 'text': f.get('content', '')} for i, f in enumerate(active)]
    idx = me.BM25Index(docs)
    qt = me.tokenize(query)
    det = idx.search_detailed(query, top_k=8)
    if not det:
        return []
    best = det[0]['score']
    kept = []
    for d in det:
        if recipe == 'rare':
            n_rare, _ = rare_matched(qt, idx.doc_tokens[d['index']], idx)
            ok = n_rare >= thr and d['score'] >= 0.25 * best
        elif recipe == 'rare_any':
            n_rare, _ = rare_matched(qt, idx.doc_tokens[d['index']], idx)
            # 退一步：稀有词命中 1 个即可，但要求覆盖率也有底
            ok = n_rare >= 1 and d['coverage'] >= thr
        elif recipe == 'rare_and_cov':
            n_rare, _ = rare_matched(qt, idx.doc_tokens[d['index']], idx)
            ok = n_rare >= 1 and d['coverage'] >= thr and d['score'] >= 0.25 * best
        else:
            ok = True
        if ok:
            kept.append(d)
    kept.sort(key=lambda x: -x['score'])
    return [docs[d['index']] for d in kept[:top_k]]


def main():
    real = [f for f in json.loads(io.open(os.path.join(REPO, 'memory.json'),
                                          encoding='utf-8').read())['facts']
            if f.get('status') == 'active']
    noise = json.loads(io.open(os.path.join(DATA, 'memories-1411.json'), encoding='utf-8').read())['facts']
    cases = json.loads(io.open(os.path.join(REPO, 'tools', 'eval', 'cases.json'),
                               encoding='utf-8').read())
    neg = json.loads(io.open(os.path.join(REPO, 'tools', 'eval', 'negatives.json'),
                             encoding='utf-8').read())
    neg_qs = [q for cat, qs in neg['categories'].items() for q in qs]
    real_text = '\n'.join(str(f.get('content') or '') for f in real)
    usable = {g: [c for c in cases[g] if any(n in real_text for n in c['expect_any'])]
              for g in ('recall', 'holdout')}

    libs = []
    for rep in range(REPEATS):
        rnd = random.Random(20261103 + rep * 104729)
        pool = noise[:]
        rnd.shuffle(pool)
        mixed = [{'id': str(f.get('id') or 'r'), 'content': str(f.get('content') or ''),
                  'status': 'active', 'importance': float(f.get('importance', 3) or 3)} for f in real]
        for i, f in enumerate(pool[:CAP - len(real)]):
            mixed.append({'id': 'n%05d' % i, 'content': f.get('content', ''),
                          'status': 'active', 'importance': float(f.get('importance', 3) or 3)})
        libs.append(mixed)

    print('容量固定 %d 条 / %d 个随机种子 / 用例 recall %d holdout %d 负样本 %d'
          % (CAP, REPEATS, len(usable['recall']), len(usable['holdout']), len(neg_qs)))
    print()
    print('  %-26s %-12s %-12s %s' % ('机制', 'recall', 'holdout', '负样本误命中'))
    print('  ' + '-' * 74)

    # 基线：现状
    me.GATE_MIN_MATCHED, me.GATE_MIN_COVERAGE, me.GATE_KEEP_RATIO = 2, 0.30, 0.25
    rl, hl, nl = [], [], []
    for mixed in libs:
        def run(q):
            return me.search_memory_for_injection(mixed, q, top_k=3)
        rl.append(sum(1 for c in usable['recall']
                      if any(n in ' '.join(x['text'] for x in run(c['query'])) for n in c['expect_any'])))
        hl.append(sum(1 for c in usable['holdout']
                      if any(n in ' '.join(x['text'] for x in run(c['query'])) for n in c['expect_any'])))
        nl.append(sum(1 for q in neg_qs if run(q)))
    avg = lambda x: sum(x) / len(x)  # noqa: E731
    print('  %-26s %-12s %-12s %.1f/42 (%.0f%%) ← 现状' % (
        'matched>=2 OR cov>=0.30', '%.1f/6' % avg(rl), '%.1f/12' % avg(hl),
        avg(nl), avg(nl) / 42 * 100))

    out = [{'recipe': 'baseline', 'thr': None, 'recall': round(avg(rl), 2),
            'holdout': round(avg(hl), 2), 'neg_inject': round(avg(nl), 2)}]
    for recipe, thrs in (('rare', (1, 2)), ('rare_any', (0.30, 0.40)),
                         ('rare_and_cov', (0.30, 0.40))):
        for thr in thrs:
            rl, hl, nl = [], [], []
            for mixed in libs:
                def run(q, _r=recipe, _t=thr):
                    return run_recipe(mixed, q, _r, _t, top_k=3)
                rl.append(sum(1 for c in usable['recall']
                              if any(n in ' '.join(x['text'] for x in run(c['query']))
                                     for n in c['expect_any'])))
                hl.append(sum(1 for c in usable['holdout']
                              if any(n in ' '.join(x['text'] for x in run(c['query']))
                                     for n in c['expect_any'])))
                nl.append(sum(1 for q in neg_qs if run(q)))
            print('  %-26s %-12s %-12s %.1f/42 (%.0f%%)  [%d~%d]' % (
                '%s thr=%s' % (recipe, thr), '%.1f/6' % avg(rl), '%.1f/12' % avg(hl),
                avg(nl), avg(nl) / 42 * 100, min(nl), max(nl)))
            out.append({'recipe': recipe, 'thr': thr, 'recall': round(avg(rl), 2),
                        'holdout': round(avg(hl), 2), 'neg_inject': round(avg(nl), 2),
                        'range': [min(nl), max(nl)]})

    p = os.path.join(RESULTS, 'gate_mechanism.json')
    _wjson(p, {
        'note': '容量 %d 条，%d 种子；rare = 只数 IDF 高于 query 中位数的命中词' % (CAP, REPEATS),
        'rows': out}, indent=2)
    print()
    print('  已写 %s' % p)
    return 0


if __name__ == '__main__':
    sys.exit(main())
