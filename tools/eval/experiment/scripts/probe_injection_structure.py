# -*- coding: utf-8 -*-
"""注入效果实验（2026-11-04）—— 结构到底让注入变好还是变坏

## 前面验到哪一步

实验五验了「标注质量」：`topic + object + aspect` 能稳定生成、判别冲突 0、复用率 100%。
但**没验注入效果** —— 结构再好，若注入更吵或更漏，就不该上。

## 三种注入口径

  M0 现况：BM25 + coverage 闸门（产品当前行为）
  M1 向量：cosine top-3（上轮验过的组件行为）
  M2 结构：按实体聚合后注入 —— 每个实体占一个槽位，槽内是该实体的多个面向

M2 的假设：**3 个槽位应该给 3 件不同的事，而不是同一件事的 3 个说法**。
这是「多维节点」真正的收益点 —— 不是压缩，是**槽位效率**。

## 指标（六项）

  ① 召回：cases 开发 6 + 留出 12
  ② 纯噪声：negatives 的 pure_noise_cases
  ③ 注入率：realdist 45 条真实消息
  ④ **槽位多样性**：3 个槽里有多少个不同实体（M2 的结构优势应体现在这里）
  ⑤ **冗余度**：3 个槽里有多少条说的是同一件事
  ⑥ 上下文成本：注入块字符数

## 口径

- 标签来自 library-labels.json（真实 21 条 + 合成 1411 条）
- 聚合文本用「topic + 面向片段」模板拼，不用 LLM 重写（免费、可复现）
- 不接产品，只在实验目录跑
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
LAB = json.loads(io.open(os.path.join(RES, 'library-labels.json'), encoding='utf-8').read())

e = mem.get_embedder()
assert e.ok, mem.status()


def norm(s):
    s = (s or '').strip().lower()
    for ch in ' \u3000，。、；：！？,.;:!?（）()「」"\'`':
        s = s.replace(ch, '')
    return s


def entity_key(lab):
    """实体键：object 优先（有专名时最精确），空则用 topic。

    ⚠ 实测 object 覆盖率只有 4.1%（1411 条里 58 条）——
    所以现实里绝大多数条目靠 topic 承担归并，object 只是少数情况下的细分。
    """
    obj = norm(lab.get('object'))
    if obj:
        return 'O:' + obj
    return 'T:' + norm(lab.get('topic'))


def load_real():
    """返回 (items, product_facts)。

    ⚠ product_facts 必须保留产品原字段（`content`）：
      第一版我把 items（用 `text` 存文本）直接传给 memory_engine，
      而它读 `f['content']` ⇒ BM25 看到全空文本 ⇒ 召回 0/6、注入 0/45。
      实测产品口径是 devR@3 2/6、注入率 14/45 —— 那次是**夹具错**，不是产品错。
    """
    facts = [f for f in json.loads(io.open(os.path.join(REPO, 'memory.json'),
                                          encoding='utf-8').read())['facts']
             if f.get('status', 'active') == 'active']
    lab = LAB['real']
    items = []
    for f in facts:
        L = lab.get(f['id']) or {}
        items.append({'id': f['id'], 'text': (f.get('content') or '').strip(),
                      'topic': L.get('topic') or '', 'object': L.get('object') or '',
                      'aspect': L.get('aspect') or '', 'key': entity_key(L),
                      'importance': f.get('importance', 3)})
    return items, facts


def load_synth():
    syn = json.loads(io.open(os.path.join(EXP, 'data', 'memories-1411.json'),
                            encoding='utf-8').read())['facts']
    lab = LAB['synth']
    items = []
    for i, f in enumerate(syn):
        sid = 'syn-%04d' % i
        L = lab.get(sid) or {}
        items.append({'id': sid, 'text': (f.get('content') or '').strip(),
                      'topic': L.get('topic') or '', 'object': L.get('object') or '',
                      'aspect': L.get('aspect') or '', 'key': entity_key(L),
                      'importance': f.get('importance', 3)})
    return items


ASPECT_CN = {'preference': '偏好', 'habit': '习惯', 'change': '变化',
             'struggle': '卡点', 'advice': '建议', 'episode': '经历'}


def aggregate(key, members, budget=160):
    """把一个实体的多个面向拼成一句（模板法，不调 LLM）。

    排序：importance 降序 → 短句优先（让预算装下更多面向）
    """
    topic = next((m['topic'] for m in members if m['topic']), '') or key[2:]
    order = sorted(members, key=lambda m: (-float(m['importance']),
                                           len(m['text'])))
    parts, used = [], 0
    seen_asp = set()
    for mm in order:
        a = ASPECT_CN.get(mm['aspect'], '')
        t = mm['text']
        piece = ('%s：%s' % (a, t)) if a else t
        if used + len(piece) + 1 > budget:
            continue
        parts.append(piece)
        used += len(piece) + 1
        if a:
            seen_asp.add(a)
    return '%s｜%s' % (topic, '；'.join(parts))


# ═══════════════ 三种口径 ═══════════════
def m0_bm25(query, facts):
    """现况：产品入口（BM25 + coverage 闸门）"""
    return [str(h.get('text') or '') for h in
            me.search_memory_for_injection(facts, query, top_k=3)]


def m1_vector(query, items, vecs, k=3):
    hits = e.search(query, vecs, [x['text'] for x in items], k=k, threshold=THR)
    return [h['text'] for h in hits], [items[h['index']] for h in hits]


def m2_entity(query, items, vecs, k=3):
    """结构：按实体聚合，每个实体占一槽"""
    if mem.is_definition_question(query):
        return [], []
    hits = e.search(query, vecs, [x['text'] for x in items], k=len(items), threshold=THR)
    if not hits:
        return [], []
    by_key = collections.OrderedDict()
    for h in hits:
        it = items[h['index']]
        by_key.setdefault(it['key'], []).append(it)
    slots = []
    for key, members in by_key.items():
        slots.append({'key': key, 'members': members,
                      'text': aggregate(key, members)})
        if len(slots) >= k:
            break
    return [s['text'] for s in slots], slots


def stats_block(texts):
    """④ 槽位多样性 / ⑤ 冗余度 / ⑥ 成本"""
    return {'slots': len(texts), 'chars': sum(len(t) for t in texts)}


def main():
    real, real_facts = load_real()
    print('真实库 %d 条，实体 %d 个' % (len(real), len({x['key'] for x in real})))
    keys = collections.Counter(x['key'] for x in real)
    print('  实体大小分布：%s'
          % [(k[2:][:8], v) for k, v in keys.most_common(6)])

    RV = e.encode([x['text'] for x in real])

    print()
    print('=' * 100)
    print('① 召回（真实库 21 条）')
    print('=' * 100)
    cases = rs.load_cases()
    print('  %-8s %-10s %-10s %-10s' % ('集合', 'M0 BM25', 'M1 向量', 'M2 结构'))
    print('  ' + '-' * 42)
    recall = {}
    for name, cs in (('开发集(6)', cases['recall']), ('留出集(12)', cases['holdout'])):
        row = []
        for tag, fn in (('M0', None), ('M1', None), ('M2', None)):
            n = 0
            for c in cs:
                if tag == 'M0':
                    texts = m0_bm25(c['query'], real_facts)
                elif tag == 'M1':
                    texts = m1_vector(c['query'], real, RV)[0]
                else:
                    texts = m2_entity(c['query'], real, RV)[0]
                if rs.hit_any(texts[:3], c['expect_any']):
                    n += 1
            row.append('%d/%d' % (n, len(cs)))
            recall[name + tag] = n
        print('  %-8s %-10s %-10s %-10s' % (name, row[0], row[1], row[2]))

    print()
    print('=' * 100)
    print('② 纯噪声（negatives pure_noise_cases）')
    print('=' * 100)
    neg = rs.load_negatives()
    pn = neg.get('pure_noise_cases', [])
    for tag in ('M0', 'M1', 'M2'):
        bad = []
        for c in pn:
            if tag == 'M0':
                texts = m0_bm25(c['query'], real_facts)
            elif tag == 'M1':
                texts = m1_vector(c['query'], real, RV)[0]
            else:
                texts = m2_entity(c['query'], real, RV)[0]
            if rs.hit_any(texts, c.get('must_not_hit') or []):
                bad.append(c['query'][:20])
        print('  %-6s 纯噪声注入 %d / %d  %s' % (tag, len(bad), len(pn), bad[:3]))

    print()
    print('=' * 100)
    print('③④⑤⑥ 真实对话 45 条：注入率 / 槽位多样性 / 冗余度 / 成本')
    print('=' * 100)
    msgs = [m['text'] for m in rs.load_realdist()['messages']]
    rows = {}
    for tag in ('M0', 'M1', 'M2'):
        n_inj = 0
        divs, reds, chars = [], [], []
        for q in msgs:
            if tag == 'M0':
                texts = m0_bm25(q, real_facts)
                keys_hit = []
                for t in texts:
                    hit = next((x for x in real if x['text'] == t), None)
                    keys_hit.append(entity_key(hit) if hit else '?')
            elif tag == 'M1':
                texts, items = m1_vector(q, real, RV)
                keys_hit = [x['key'] for x in items]
            else:
                texts, slots = m2_entity(q, real, RV)
                keys_hit = [s['key'] for s in slots]
            if not texts:
                continue
            n_inj += 1
            divs.append(len(set(keys_hit)))
            reds.append(len(keys_hit) - len(set(keys_hit)))
            chars.append(sum(len(t) for t in texts))
        rows[tag] = {'inj': n_inj, 'div': np.mean(divs) if divs else 0,
                     'red': np.mean(reds) if reds else 0,
                     'chars': np.mean(chars) if chars else 0}
        print('  %-6s 注入 %2d/%d = %4.0f%% ｜ 平均不同实体 %.2f ｜ 平均冗余 %.2f ｜ 平均 %3.0f 字'
              % (tag, n_inj, len(msgs), 100.0 * n_inj / len(msgs),
                 rows[tag]['div'], rows[tag]['red'], rows[tag]['chars']))

    print()
    print('=' * 100)
    print('规模测试：合成库 1411 条（实体 %d 个）'
          % len({x['key'] for x in load_synth()}))
    print('=' * 100)
    syn = load_synth()
    SV = e.encode([x['text'] for x in syn])
    srow = {}
    for tag in ('M1', 'M2'):
        n_inj = 0
        divs, reds, chars = [], [], []
        for q in msgs:
            if tag == 'M1':
                texts, items = m1_vector(q, syn, SV)
                keys_hit = [x['key'] for x in items]
            else:
                texts, slots = m2_entity(q, syn, SV)
                keys_hit = [s['key'] for s in slots]
            if not texts:
                continue
            n_inj += 1
            divs.append(len(set(keys_hit)))
            reds.append(len(keys_hit) - len(set(keys_hit)))
            chars.append(sum(len(t) for t in texts))
        srow[tag] = {'inj': n_inj, 'div': np.mean(divs) if divs else 0,
                     'red': np.mean(reds) if reds else 0,
                     'chars': np.mean(chars) if chars else 0}
        print('  %-6s 注入 %2d/%d = %4.0f%% ｜ 平均不同实体 %.2f ｜ 平均冗余 %.2f ｜ 平均 %3.0f 字'
              % (tag, n_inj, len(msgs), 100.0 * n_inj / len(msgs),
                 srow[tag]['div'], srow[tag]['red'], srow[tag]['chars']))
    print()
    print('  对照（上一轮实测的扁平库注入率）：21 条 36%% / 171 条 76%% / 1432 条 87%%')

    # ---------- 案例检查 ----------
    print()
    print('=' * 100)
    print('逐案例看：结构化注入到底长什么样')
    print('=' * 100)
    for q in ('我爱吃啥', '我平时玩什么游戏解压', '我大几', '你还记得我喜欢吃那种甜甜的老式切片吗'):
        t1 = m1_vector(q, real, RV)[0]
        t2, slots = m2_entity(q, real, RV)
        print('  「%s」' % q)
        print('    M1 扁平：')
        for t in t1:
            print('      · %s' % t[:64])
        print('    M2 结构：')
        for t in t2:
            print('      ◆ %s' % t[:78])
        print()

    # ---------- 落盘 ----------
    out = os.path.join(RES, 'injection-structure.json')
    with io.open(out, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(json.dumps({
            'generated': __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M'),
            'threshold': THR,
            'object_coverage_pct': round(
                100.0 * sum(1 for v in LAB['synth'].values() if v.get('object'))
                / max(len(LAB['synth']), 1), 1),
            'real_scale': {'n': len(real), 'entities': len({x['key'] for x in real}),
                           'recall': recall, 'stats': rows},
            'synth_scale': {'n': len(syn), 'entities': len({x['key'] for x in syn}),
                            'stats': srow},
        }, ensure_ascii=False, indent=1) + '\n')
    print('  已写 %s' % out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
