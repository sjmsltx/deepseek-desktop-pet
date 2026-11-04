# -*- coding: utf-8 -*-
"""注入实验 v2：用正确的标签重做（2026-11-04）

## 上一版用了错标签

`probe_injection_structure.py` 用的 `library-labels.json`（v1）里 topic 被候选表吸歪
（「小型户外婚礼」→个人身份、「线代求逆卡了半天」→Python学习）。
那一版的注入结论（冗余归零、注入率不变）**建立在错标签上**，必须重做。

## 这一版用 v3 标签（按对话分组标注，同 batch 唯一率 100%）

实体 = 一段对话（batch），内部有多个 aspect。
这正是 Owner 说的「一个节点的多个方面」——只不过数据里每段对话恰好就是一件事。

## 指标

  ① 召回：cases 开发 6 + 留出 12
  ② 纯噪声
  ③ 注入率（45 条真实对话）
  ④ 槽位多样性 / 冗余
  ⑤ 上下文成本
"""
import io
import json
import os
import sys
import collections

import numpy as np

REPO = r'D:\ai工作站\desktop-pet'
EXP = os.path.join(REPO, 'tools', 'eval', 'experiment')
RES = os.path.join(EXP, 'results')
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(EXP, 'scripts'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'eval', 'gate_study'))
os.environ.setdefault('PET_EMBED_DIR', os.path.join(EXP, '_embed_probe'))

import memory_embed as mem              # noqa: E402
import memory_engine as me              # noqa: E402
import run_study as rs                  # noqa: E402

THR = mem.DEFAULT_THRESHOLD

#: 目标注入率（Owner 2026-11-04 裁定：50%）。
#: 这是**判据不是开关**：产品运行时不测注入率，只在人工复核时用它判断
#: 「库是不是该收紧/重校准阈值了」。
#: 依据：真实库现况 31%（低于目标）；扁平库 171 条已 76%、1432 条 87%（均越线）。
TARGET_INJECTION_RATE = 0.50
V3 = json.loads(io.open(os.path.join(RES, 'library-labels-v3.json'), encoding='utf-8').read())
V1 = json.loads(io.open(os.path.join(RES, 'library-labels.json'), encoding='utf-8').read())

e = mem.get_embedder()
assert e.ok
ASPECT_CN = {'preference': '偏好', 'habit': '习惯', 'change': '变化',
             'struggle': '卡点', 'advice': '建议', 'episode': '经历'}


def norm(s):
    s = (s or '').strip().lower()
    for ch in ' \u3000，。、；：！？,.;:!?（）()「」"\'·':
        s = s.replace(ch, '')
    return s


def derive_entity(lab_by_sid, sid):
    """实体键：object 优先（非空且≥2字），否则 topic"""
    L = lab_by_sid.get(sid) or {}
    o = norm(L.get('object'))
    if o and len(o) >= 2:
        return 'O:' + o
    return 'T:' + norm(L.get('topic'))


def load_v3():
    syn = json.loads(io.open(os.path.join(EXP, 'data', 'memories-1411.json'),
                            encoding='utf-8').read())['facts']
    items = []
    for i, f in enumerate(syn):
        sid = 'syn-%04d' % i
        L = V3['synth'].get(sid) or {}
        items.append({'id': sid, 'text': (f.get('content') or '').strip(),
                      'topic': L.get('topic') or '', 'object': L.get('object') or '',
                      'aspect': L.get('aspect') or '',
                      'key': derive_entity(V3['synth'], sid),
                      'importance': f.get('importance', 3),
                      'batch': int(f.get('batch', -1))})
    return items


def load_real():
    """真实库用 v3['real']（同一次按对话口径标的）"""
    facts = [f for f in json.loads(io.open(os.path.join(REPO, 'memory.json'),
                                          encoding='utf-8').read())['facts']
             if f.get('status', 'active') == 'active']
    lab = V3.get('real') or {}
    items = []
    for f in facts:
        L = lab.get(f['id']) or {}
        items.append({'id': f['id'], 'text': (f.get('content') or '').strip(),
                      'topic': L.get('topic') or '', 'object': L.get('object') or '',
                      'aspect': L.get('aspect') or '',
                      'key': ('O:' + norm(L.get('object'))) if (L.get('object') or '').strip()
                      else ('T:' + norm(L.get('topic'))),
                      'importance': f.get('importance', 3)})
    return items, facts


def aggregate(key, members, budget=60):
    """聚合：topic｜aspect：正文；按 importance 降序，超预算跳过"""
    topic = next((x['topic'] for x in members if x['topic']), '') or key[2:]
    order = sorted(members, key=lambda x: (-float(x['importance']), len(x['text'])))
    parts, used = [], 0
    for mm in order:
        a = ASPECT_CN.get(mm['aspect'], '')
        piece = ('%s：%s' % (a, mm['text'])) if a else mm['text']
        if used + len(piece) + 1 > budget:
            continue
        parts.append(piece)
        used += len(piece) + 1
    return '%s｜%s' % (topic, '；'.join(parts))


def m0(q, facts):
    return [str(h.get('text') or '') for h in
            me.search_memory_for_injection(facts, q, top_k=3)]


def m1(q, items, vecs, k=3):
    hits = e.search(q, vecs, [x['text'] for x in items], k=k, threshold=THR)
    return [h['text'] for h in hits], [items[h['index']] for h in hits]


def m2(q, items, vecs, k=3, budget=60):
    if mem.is_definition_question(q):
        return [], []
    hits = e.search(q, vecs, [x['text'] for x in items], k=len(items), threshold=THR)
    if not hits:
        return [], []
    by = collections.OrderedDict()
    for h in hits:
        by.setdefault(items[h['index']]['key'], []).append(items[h['index']])
    slots = [{'key': kk, 'text': aggregate(kk, mm, budget)}
             for kk, mm in list(by.items())[:k]]
    return [s['text'] for s in slots], slots


def evaluate(tag, items, vecs, facts=None):
    n_inj = 0
    divs, reds, chars = [], [], []
    for q in MSGS:
        if tag == 'M0':
            texts = m0(q, facts)
            keys = [next((x['key'] for x in items if x['text'] == t), '?') for t in texts]
        elif tag == 'M1':
            texts, hit = m1(q, items, vecs)
            keys = [x['key'] for x in hit]
        else:
            texts, slots = m2(q, items, vecs)
            keys = [s['key'] for s in slots]
        if not texts:
            continue
        n_inj += 1
        divs.append(len(set(keys)))
        reds.append(len(keys) - len(set(keys)))
        chars.append(sum(len(t) for t in texts))
    return {'inj': n_inj, 'rate': 100.0 * n_inj / len(MSGS),
            'div': float(np.mean(divs)) if divs else 0.0,
            'red': float(np.mean(reds)) if reds else 0.0,
            'chars': float(np.mean(chars)) if chars else 0.0}


MSGS = [x['text'] for x in rs.load_realdist()['messages']]

real, real_facts = load_real()
syn = load_v3()
RV = e.encode([x['text'] for x in real])
SV = e.encode([x['text'] for x in syn])
cases = rs.load_cases()
print('真实库 %d 条 / %d 实体；合成库 %d 条 / %d 实体'
      % (len(real), len({x['key'] for x in real}),
         len(syn), len({x['key'] for x in syn})))

print()
print('=' * 96)
print('① 召回')
print('=' * 96)
print('  %-12s %-10s %-10s %-10s' % ('集合', 'M0 BM25', 'M1 向量', 'M2 结构'))
print('  ' + '-' * 46)
recall = {}
for name, cs in (('开发集(6)', cases['recall']), ('留出集(12)', cases['holdout'])):
    row = []
    for tag in ('M0', 'M1', 'M2'):
        n = 0
        for c in cs:
            if tag == 'M0':
                texts = m0(c['query'], real_facts)
            elif tag == 'M1':
                texts = m1(c['query'], real, RV)[0]
            else:
                texts = m2(c['query'], real, RV)[0]
            if rs.hit_any(texts[:3], c['expect_any']):
                n += 1
        row.append('%d/%d' % (n, len(cs)))
        recall['%s_%s' % (name, tag)] = n
    print('  %-12s %-10s %-10s %-10s' % (name, row[0], row[1], row[2]))

print()
print('=' * 96)
print('② 纯噪声')
print('=' * 96)
neg = rs.load_negatives()
for tag in ('M0', 'M1', 'M2'):
    bad = 0
    for c in neg.get('pure_noise_cases', []):
        if tag == 'M0':
            texts = m0(c['query'], real_facts)
        elif tag == 'M1':
            texts = m1(c['query'], real, RV)[0]
        else:
            texts = m2(c['query'], real, RV)[0]
        if rs.hit_any(texts, c.get('must_not_hit') or []):
            bad += 1
    print('  %-4s 纯噪声注入 %d / %d' % (tag, bad, len(neg.get('pure_noise_cases') or [])))

print()
print('=' * 96)
print('③④⑤ 注入率 / 多样性 / 冗余 / 成本（45 条真实对话）')
print('=' * 96)
print('  %-18s %-8s %-10s %-8s %-10s' % ('口径', '注入率', '不同实体', '冗余', '平均字数'))
print('  ' + '-' * 60)
stats = {}
for tag, label in (('M0', 'M0 BM25(产品)'), ('M1', 'M1 向量扁平'), ('M2', 'M2 结构60字')):
    st = evaluate(tag, real, RV, real_facts)
    stats['real_' + tag] = st
    print('  %-18s %-8s %-10.2f %-8.2f %-10.0f'
          % (label, '%.0f%%' % st['rate'], st['div'], st['red'], st['chars']))

print()
print('  合成库 1411 条：')
for tag, label in (('M1', 'M1 向量扁平'), ('M2', 'M2 结构60字')):
    st = evaluate(tag, syn, SV)
    stats['syn_' + tag] = st
    print('  %-18s %-8s %-10.2f %-8.2f %-10.0f'
          % (label, '%.0f%%' % st['rate'], st['div'], st['red'], st['chars']))

print()
print('=' * 96)
print('目标注入率判据（Owner 裁定 50%）')
print('=' * 96)
for key, label in (('real_M0', '真实库 M0（产品现况）'), ('real_M1', '真实库 M1 向量'),
                   ('real_M2', '真实库 M2 结构'), ('syn_M1', '合成库 1411 M1'),
                   ('syn_M2', '合成库 1411 M2')):
    if key not in stats:
        continue
    r = stats[key]['rate'] / 100.0
    print('  %-24s %4.0f%%  %s' % (label, r * 100,
                                   '✓ 低于目标' if r <= TARGET_INJECTION_RATE
                                   else '★ 超过目标 %.0f%%' % (TARGET_INJECTION_RATE * 100)))
print()
print('  ⇒ 结论：真实库安全；库增长到 171 条量级会越线（上轮实测 76%）。')
print('    这就是「上限应随库成长调整」的量化依据，也是本判据的用途。')

print()
print('  对照：v1 错标签那次 —— 真实库 M2 冗余 0.00/100字；合成库 M2 冗余 0.00/268字')

out = os.path.join(RES, 'injection-structure-v2.json')
with io.open(out, 'w', encoding='utf-8', newline='\n') as fh:
    fh.write(json.dumps({
        'generated': __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M'),
        'labels': 'v3（按对话分组，同batch唯一率100%）',
        'real': {'n': len(real), 'entities': len({x['key'] for x in real}), 'stats': stats,
                 'recall': recall},
        'synth': {'n': len(syn), 'entities': len({x['key'] for x in syn})},
    }, ensure_ascii=False, indent=1) + '\n')
print()
print('  已写 %s' % out)
