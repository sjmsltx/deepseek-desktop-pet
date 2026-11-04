# -*- coding: utf-8 -*-
"""抽取侧实体/面向标注 —— 可行性验证 v2（2026-11-04）

## 为什么是 v2

v1 用单个 `entity` 字段，最小验证就暴露问题：
同一批「编辑器」的 6 条被拆成 4 个标签（编辑器偏好 / VS Code 配置 / 编辑器使用习惯 /
编辑器更换纠结）—— 模型在「主题」和「具体对象」之间摇摆。

试了变体 B（`topic` + `object` 两维）后看到：
  · `object` 极稳：5 条 PyCharm 全写 PyCharm，WPS 写 WPS
  · `topic` 仍过拆分（编辑器偏好/编辑器使用习惯/编辑器配置调整/编辑器体验/选择决策）

⇒ 假设的可用设计：**object 当主键（有就用），topic 兜底（没 object 时才用）**。
   这样既能把同一件事的多个面向并到一起，又能把「同句式不同对象」分开。

## 本脚本做什么

两套提示词各跑 3 遍，同一批 235 条：
  A：单 entity（v1 方案）
  B：topic + object + aspect（两维方案）
指标：覆盖率 / 稳定性 / 顺序敏感 / **判别力** / 归并质量 / 成本
最后按数据给出「哪个方案能用」。
"""
import importlib.util
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import collections
import random

REPO = r'D:\ai工作站\desktop-pet'
EXP = os.path.join(REPO, 'tools', 'eval', 'experiment')
RESULTS = os.path.join(EXP, 'results')
DATA = os.path.join(EXP, 'data', 'memories-1411.json')
OUT = os.path.join(RESULTS, 'entity-extraction.json')

MODEL = 'deepseek-flash'
ENDPOINT = 'https://api.deepseek.com/chat/completions'
BATCH = 12

ASPECTS = {'preference', 'habit', 'change', 'struggle', 'advice', 'episode'}
ASPECT_DOC = ('preference（偏好/喜好）、habit（长期习惯/坚持多久）、'
              'change（前后变化/态度转变）、struggle（困难/卡点/纠结）、'
              'advice（他人建议/外部信息）、episode（某次具体经历/聊天）')

PROMPT_A = """你是记忆结构标注器。下面有几条关于同一个人（用户）的记忆。

对**每一条**输出两个字段：
1. `entity`：这件事「是什么」（4~10 字）。要求：
   - **同一件事必须用完全相同的写法**。两条都在说喝咖啡，都写「咖啡偏好」
   - 不同对象必须写成不同 entity。例如「编辑器偏好」与「操作系统偏好」是两个
   - 不要用「用户」「偏好」这种太泛的词单独作 entity
2. `aspect`：只能从下列取值中选一个：%s

只输出 json，格式：
{{"items": [{{"i": 0, "entity": "...", "aspect": "preference"}}, ...]}}

记忆列表：
{items}""" % ASPECT_DOC

PROMPT_B = """你是记忆结构标注器。下面有几条关于同一个人（用户）的记忆。

对**每一条**输出三个字段：
1. `topic`：这件事属于哪个**主题桶**（4~8 字，粗粒度、可复用）。
   - 说的是「哪一类事」，不是「哪一次」；同一类事必须用完全相同的写法
   - 不要用「用户」「偏好」「事情」这种没有信息量的词单独作 topic
2. `object`：这条具体说的是**哪个对象**（2~10 字，**没有就写空字符串**）。
   - 有明确专名的写专名：「VS Code」「ArcGIS Pro」「鱼香肉丝」
   - 泛指偏好、没有具体对象时留空
3. `aspect`：只能从下列取值中选一个：%s

只输出 json，格式：
{{"items": [{{"i": 0, "topic": "...", "object": "", "aspect": "preference"}}, ...]}}

记忆列表：
{items}""" % ASPECT_DOC


def _read_key():
    for name in ('config.json', 'config_backup_20261007.json'):
        q = os.path.join(REPO, name)
        if not os.path.exists(q):
            continue
        try:
            cfg = json.loads(io.open(q, encoding='utf-8').read())
        except (OSError, ValueError):
            continue
        k = (cfg.get('deepseek_api_key') or '').strip()
        if k:
            return k
    return ''


def call(key, prompt, max_tokens=2000, temperature=0.0):
    payload = {
        'model': MODEL,
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': temperature,
        'max_tokens': max_tokens,
        'thinking': {'type': 'disabled'},      # 不关会被 reasoning 吃光预算
        'response_format': {'type': 'json_object'},
    }
    req = urllib.request.Request(
        ENDPOINT, data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json',
                 'Authorization': 'Bearer ' + key})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            d = json.loads(r.read().decode('utf-8'))
        ch = d['choices'][0]
        return (ch['message'].get('content') or '').strip(), (d.get('usage') or {}), ch.get('finish_reason')
    except urllib.error.HTTPError as e:
        return '', {}, 'HTTP %d %s' % (e.code, e.read().decode('utf-8', 'replace')[:100])
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        return '', {}, type(e).__name__


def parse(txt, n, variant):
    out = {}
    try:
        d = json.loads(txt)
    except ValueError:
        m = re.search(r'\{.*\}', txt or '', re.S)
        if not m:
            return out
        try:
            d = json.loads(m.group(0))
        except ValueError:
            return out
    items = d.get('items') if isinstance(d, dict) else None
    if not isinstance(items, list):
        return out
    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            i = int(it.get('i'))
        except (TypeError, ValueError):
            continue
        if not (0 <= i < n):
            continue
        if variant == 'A':
            out[i] = {'entity': str(it.get('entity') or '').strip(),
                      'aspect': str(it.get('aspect') or '').strip().lower()}
        else:
            out[i] = {'topic': str(it.get('topic') or '').strip(),
                      'object': str(it.get('object') or '').strip(),
                      'aspect': str(it.get('aspect') or '').strip().lower()}
    return out


def norm(s):
    s = (s or '').strip().lower()
    return re.sub(r'[\s，。、；：！？,.;:!?（）()「」"\'`]', '', s)


def load_sample():
    d = json.loads(io.open(DATA, encoding='utf-8').read())
    fs = d['facts']
    by_b = collections.defaultdict(list)
    for i, f in enumerate(fs):
        f['_i'] = i
        by_b[int(f.get('batch', -1))].append(f)
    picked, used = [], []
    for b in sorted(by_b):
        v = by_b[b]
        if len(v) >= 3 and len(used) < 60:
            picked.extend(v[:3])
            used.append(b)
    ids = {f['_i'] for f in picked}
    hard = (86, 87, 79, 60, 85, 92, 81, 97, 47, 48)
    for b in hard:
        for f in by_b.get(b, []):
            if f['_i'] not in ids:
                picked.append(f)
                ids.add(f['_i'])
    return picked


def run_pass(key, facts, variant, seed=None, temp=0.0, tag=''):
    idx = list(range(len(facts)))
    if seed is not None:
        random.Random(seed).shuffle(idx)
    tmpl = PROMPT_A if variant == 'A' else PROMPT_B
    res, calls, tin, tout = {}, 0, 0, 0
    t0 = time.time()
    total = (len(idx) + BATCH - 1) // BATCH
    for s in range(0, len(idx), BATCH):
        chunk = idx[s:s + BATCH]
        lines = '\n'.join('%d. %s' % (j, (facts[gi].get('content') or '').strip())
                          for j, gi in enumerate(chunk))
        txt, usage, fin = call(key, tmpl.format(items=lines), temperature=temp)
        calls += 1
        tin += int(usage.get('prompt_tokens') or 0)
        tout += int(usage.get('completion_tokens') or 0)
        got = parse(txt, len(chunk), variant)
        if not got:
            print('    [%s] 第 %d 批失败 fin=%s' % (tag, s // BATCH, fin))
        for j, gi in enumerate(chunk):
            res[gi] = got.get(j, {})
        if (s // BATCH) % 5 == 0:
            print('    [%s] %d/%d' % (tag, s // BATCH + 1, total))
    return res, {'calls': calls, 'tok_in': tin, 'tok_out': tout,
                 'sec': round(time.time() - t0, 1)}


LATIN = re.compile(r'[A-Za-z][A-Za-z0-9\.\+\-]{1,}')
GENERIC = {'user', 'ai', 'llm', 'api', 'pdf', 'excel', 'ppt', 'word'}


def latins(t):
    return {w.lower() for w in LATIN.findall(t or '')
            if w.lower() not in GENERIC and len(w) >= 2}


def key_of(v, variant, mode='obj'):
    """v 是单条标注结果；返回用于比较的归一 key"""
    if variant == 'A':
        return norm(v.get('entity'))
    if mode == 'topic':
        return norm(v.get('topic'))
    # mode='obj'：object 优先，空则用 topic 兜底
    obj = norm(v.get('object'))
    return obj if obj else norm(v.get('topic'))


def evaluate(facts, passes, variant):
    n = len(facts)
    r = {p: {int(k): v for k, v in passes[variant + '_' + p]['res'].items()}
         for p in ('p1', 'p2', 'p3')}
    out = {}

    def key(mode, p):
        return {i: key_of(r[p].get(i, {}), variant, mode) for i in range(n)}

    # E1 覆盖率
    if variant == 'A':
        cov = sum(1 for i in range(n) if r['p1'].get(i, {}).get('entity'))
    else:
        cov = sum(1 for i in range(n) if r['p1'].get(i, {}).get('topic'))
    out['coverage_pct'] = round(100.0 * cov / n, 1)
    out['aspect_legal_pct'] = round(
        100.0 * sum(1 for i in range(n) if r['p1'].get(i, {}).get('aspect') in ASPECTS) / n, 1)

    # E2 自一致性
    modes = ['obj'] if variant == 'B' else ['entity']
    for mode in modes:
        k1, k2 = key(mode, 'p1'), key(mode, 'p2')
        both = [i for i in range(n) if k1[i] and k2[i]]
        same = sum(1 for i in both if k1[i] == k2[i])
        out['E2_%s_consistency_pct' % mode] = round(100.0 * same / max(len(both), 1), 1)
    if variant == 'B':
        kt1, kt2 = key('topic', 'p1'), key('topic', 'p2')
        both = [i for i in range(n) if kt1[i] and kt2[i]]
        out['E2_topic_consistency_pct'] = round(
            100.0 * sum(1 for i in both if kt1[i] == kt2[i]) / max(len(both), 1), 1)
        # object 自身的稳定度
        o1 = {i: norm(r['p1'].get(i, {}).get('object')) for i in range(n)}
        o2 = {i: norm(r['p2'].get(i, {}).get('object')) for i in range(n)}
        both_o = [i for i in range(n) if o1[i] or o2[i]]
        out['E2_object_consistency_pct'] = round(
            100.0 * sum(1 for i in both_o if o1[i] == o2[i]) / max(len(both_o), 1), 1)

    # E3 顺序/温度敏感
    for mode in modes:
        k1, k3 = key(mode, 'p1'), key(mode, 'p3')
        both = [i for i in range(n) if k1[i] and k3[i]]
        out['E3_%s_vs_p3_pct' % mode] = round(
            100.0 * sum(1 for i in both if k1[i] == k3[i]) / max(len(both), 1), 1)

    # E4 判别力：拉丁专名互不相交，却被写成同一 key
    conflicts = []
    for a in range(n):
        la = latins(facts[a].get('content'))
        if not la:
            continue
        for b in range(a + 1, n):
            lb = latins(facts[b].get('content'))
            if not lb or (la & lb):
                continue
            if variant == 'B':
                # 两维：先看 object；object 都非空且不同 ⇒ 已分开
                oa, ob = norm(r['p1'].get(a, {}).get('object')), norm(r['p1'].get(b, {}).get('object'))
                if oa and ob and oa != ob:
                    continue
                ka, kb = key('obj', 'p1')[a], key('obj', 'p1')[b]
            else:
                ka, kb = key('entity', 'p1')[a], key('entity', 'p1')[b]
            if ka and ka == kb:
                conflicts.append((a, b, ka))
    out['E4_conflicts'] = len(conflicts)
    out['_conflict_examples'] = conflicts[:6]

    # E5 归并质量（同 batch 是否落到同一 key）
    by_b = collections.defaultdict(list)
    for i, f in enumerate(facts):
        by_b[int(f['batch'])].append(i)
    for mode in modes:
        kk = key(mode, 'p1')
        e2b = collections.defaultdict(collections.Counter)
        b2e = collections.defaultdict(collections.Counter)
        for i, f in enumerate(facts):
            if not kk[i]:
                continue
            e2b[kk[i]][int(f['batch'])] += 1
            b2e[int(f['batch'])][kk[i]] += 1
        tot = sum(sum(c.values()) for c in e2b.values())
        purity = sum(max(c.values()) for c in e2b.values()) / float(tot) if tot else 0
        rec = (sum(1 for c in b2e.values() if max(c.values()) >= 0.5 * sum(c.values()))
               / float(len(b2e))) if b2e else 0
        per_b = []
        for b, idxs in by_b.items():
            if len(idxs) < 2:
                continue
            es = [kk[i] for i in idxs if kk[i]]
            if len(es) < 2:
                continue
            per_b.append(max(collections.Counter(es).values()) / float(len(es)))
        out['E5_%s_purity' % mode] = round(purity, 3)
        out['E5_%s_entity_recall' % mode] = round(rec, 3)
        out['E5_%s_n_keys' % mode] = len(e2b)
        out['E5_%s_same_batch_median' % mode] = round(
            sorted(per_b)[len(per_b) // 2] if per_b else 0.0, 2)

    out['usage'] = {p: passes[variant + '_' + p]['usage'] for p in ('p1', 'p2', 'p3')}
    return out, r


def main():
    key = _read_key()
    if not key:
        print('✗ 无 API key')
        return 1
    facts = load_sample()
    print('评测集 %d 条' % len(facts))
    prev = {}
    if os.path.exists(OUT):
        try:
            prev = json.loads(io.open(OUT, encoding='utf-8').read())
        except ValueError:
            prev = {}
    passes = prev.get('passes', {})
    todo = [('A', 'p1', None, 0.0), ('A', 'p2', None, 0.0), ('A', 'p3', 20261104, 0.3),
            ('B', 'p1', None, 0.0), ('B', 'p2', None, 0.0), ('B', 'p3', 20261104, 0.3)]
    for variant, p, seed, temp in todo:
        k = '%s_%s' % (variant, p)
        if k in passes:
            continue
        print('\n[%s %s] seed=%s temp=%s' % (variant, p, seed, temp))
        res, usage = run_pass(key, facts, variant, seed, temp, k)
        passes[k] = {'res': {str(a): b for a, b in res.items()}, 'usage': usage}
        os.makedirs(RESULTS, exist_ok=True)
        prev['passes'] = passes
        prev['generated'] = time.strftime('%Y-%m-%d %H:%M')
        prev['n_facts'] = len(facts)
        with io.open(OUT, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(json.dumps(prev, ensure_ascii=False, indent=1) + '\n')
        print('    已存（%d 次调用）' % usage['calls'])

    print()
    print('=' * 100)
    print('结果对比')
    print('=' * 100)
    allout = {}
    for variant in ('A', 'B'):
        o, _r = evaluate(facts, passes, variant)
        allout[variant] = o
        print()
        print('【方案 %s】%s' % (variant, '单 entity' if variant == 'A' else 'topic + object'))
        for k in ('coverage_pct', 'aspect_legal_pct'):
            print('  %-34s %s' % (k, o.get(k)))
        for k in sorted(o):
            if k.startswith('E2') or k.startswith('E3') or k.startswith('E5') or k == 'E4_conflicts':
                print('  %-34s %s' % (k, o[k]))
        print('  E4 冲突样例：')
        for a, b, kk in o['_conflict_examples'][:4]:
            print('    key=%r' % kk)
            print('       %s' % (facts[a]['content'] or '')[:50])
            print('       %s' % (facts[b]['content'] or '')[:50])

    print()
    print('=' * 100)
    print('结论（由数据生成）')
    print('=' * 100)
    a, b = allout['A'], allout['B']
    lines = []
    for tag, o, mode in (('A 单entity', a, 'entity'), ('B object主键', b, 'obj')):
        lines.append('%s：覆盖率 %s%%，自一致 %s%%，判别冲突 %d 组，归并纯度 %s / 召回 %s'
                     % (tag, o['coverage_pct'],
                        o.get('E2_%s_consistency_pct' % mode),
                        o['E4_conflicts'],
                        o.get('E5_%s_purity' % mode), o.get('E5_%s_entity_recall' % mode)))
    if 'E2_object_consistency_pct' in b:
        lines.append('B 的 object 字段单独看：自一致 %s%%（比 topic 的 %s%% 高 %s 点）'
                     % (b['E2_object_consistency_pct'], b.get('E2_topic_consistency_pct'),
                        round(b['E2_object_consistency_pct']
                              - b.get('E2_topic_consistency_pct', 0), 1)))
    better = 'B' if (b['E4_conflicts'] <= a['E4_conflicts']
                     and b.get('E5_obj_purity', 0) >= a.get('E5_entity_purity', 0)) else 'A'
    lines.append('⇒ 按「判别冲突更少 且 归并纯度不降」判定，%s 更好' % better)
    for t in lines:
        print('  · ' + t)

    prev['analysis'] = {'A': {k: v for k, v in a.items() if not k.startswith('_')},
                        'B': {k: v for k, v in b.items() if not k.startswith('_')},
                        'verdict': lines}
    with io.open(OUT, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(json.dumps(prev, ensure_ascii=False, indent=1) + '\n')
    print()
    print('  已写 %s' % OUT)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
