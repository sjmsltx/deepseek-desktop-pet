# -*- coding: utf-8 -*-
"""给真实库 + 合成语料打 topic/object/aspect 标签（2026-11-04）

## 为什么

实验五只验了**标注质量**（模型能不能稳定给出结构），没验**注入效果**
（这个结构到底让注入变好还是变坏）。

要验注入，先得把库标上结构。两个库都标：
  · 真实库 memory.json 的 21 条 active —— 小规模真实场景
  · 合成库 memories-1411 —— 大规模，用来验「结构能不能治库变大的注入噪声」

## 标签口径（沿用实验五的 B 方案，object 主键 + topic 兜底）

- topic：这件事属于哪一类（粗粒度、可复用）
- object：具体对象（有专名就写，泛指留空）
- aspect：6 个枚举之一

## 可续跑

结果落 results/library-labels.json，按 id 存，中断后从断点继续。
"""
import importlib.util
import io
import json
import os
import random
import sys

P = r'D:\ai工作站\desktop-pet\tools\eval\experiment\scripts\probe_entity_v2.py'
sys.path.insert(0, os.path.dirname(P))
spec = importlib.util.spec_from_file_location('pe2', P)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

REPO = m.REPO
OUT = os.path.join(m.RESULTS, 'library-labels.json')
REAL = os.path.join(REPO, 'memory.json')
SYNTH = os.path.join(m.EXP, 'data', 'memories-1411.json')

#: 候选表：用实验五前半段的标签表（已证明能提高复用率）
PROMPT = """你是记忆结构标注器。下面有几条关于同一个人（用户）的记忆。

**已有标签表**（请优先复用完全相同的写法，只有确实不属于任何一项时才新建）：
主题：{topics}
对象：{objects}

对每一条输出三个字段：
1. `topic`：优先从「主题」表选一项；都不合适才新建（4~8 字）
2. `object`：优先从「对象」表选一项；没有具体对象写空字符串
3. `aspect`：只能从下列取值中选一个：{aspects}

只输出 json：
{{"items": [{{"i": 0, "topic": "...", "object": "", "aspect": "preference"}}, ...]}}

记忆列表：
<<ITEMS>>"""


def label(key, items, vocab_t, vocab_o, tag):
    """items = [(id, text)]，返回 {id: {...}}"""
    out = {}
    total = (len(items) + m.BATCH - 1) // m.BATCH
    for s in range(0, len(items), m.BATCH):
        chunk = items[s:s + m.BATCH]
        lines = '\n'.join('%d. %s' % (j, t) for j, (_i, t) in enumerate(chunk))
        prompt = PROMPT.format(
            topics='、'.join(vocab_t) if vocab_t else '（空）',
            objects='、'.join(vocab_o) if vocab_o else '（空）',
            aspects=m.ASPECT_DOC).replace('<<ITEMS>>', lines)
        txt, _u, fin = m.call(key, prompt, temperature=0.0)
        got = m.parse(txt, len(chunk), 'B')
        if not got:
            print('    [%s] 第 %d 批失败 fin=%s' % (tag, s // m.BATCH, fin))
        for j, (fid, _t) in enumerate(chunk):
            out[fid] = got.get(j) or {}
        if (s // m.BATCH) % 10 == 0:
            print('    [%s] %d/%d' % (tag, s // m.BATCH + 1, total))
    return out


def main():
    key = m._read_key()
    prev = {}
    if os.path.exists(OUT):
        try:
            prev = json.loads(io.open(OUT, encoding='utf-8').read())
        except ValueError:
            prev = {}
    real_lab = prev.get('real', {})
    synth_lab = prev.get('synth', {})

    # ---------- 真实库 ----------
    real = [f for f in json.loads(io.open(REAL, encoding='utf-8').read())['facts']
            if f.get('status', 'active') == 'active']
    todo = [(f['id'], (f.get('content') or '').strip()) for f in real
            if f['id'] not in real_lab]
    print('真实库 %d 条，待标 %d 条' % (len(real), len(todo)))
    if todo:
        vt = sorted({v['topic'] for v in real_lab.values() if v.get('topic')})
        vo = sorted({v['object'] for v in real_lab.values() if v.get('object')})
        real_lab.update(label(key, todo, vt, vo, 'real'))
        _save(prev, real_lab, synth_lab)

    # ---------- 合成库 ----------
    syn = json.loads(io.open(SYNTH, encoding='utf-8').read())['facts']
    for i, f in enumerate(syn):
        f['_id'] = 'syn-%04d' % i
    todo2 = [(f['_id'], (f.get('content') or '').strip()) for f in syn
             if f['_id'] not in synth_lab]
    print('合成库 %d 条，待标 %d 条' % (len(syn), len(todo2)))
    if todo2:
        vt = sorted({v['topic'] for v in list(real_lab.values()) + list(synth_lab.values())
                     if v.get('topic')})
        vo = sorted({v['object'] for v in list(real_lab.values()) + list(synth_lab.values())
                     if v.get('object')})
        print('  候选表：topic %d 个 / object %d 个' % (len(vt), len(vo)))
        # 分 4 段跑，每段落盘一次（防中断丢太多）
        step = max(1, len(todo2) // 4)
        for s in range(0, len(todo2), step):
            part = todo2[s:s + step]
            got = label(key, part, vt, vo, 'synth%d' % (s // step + 1))
            synth_lab.update(got)
            _save(prev, real_lab, synth_lab)
            # 更新候选表，让后续段能复用前面新建的标签
            vt = sorted({v['topic'] for v in synth_lab.values() if v.get('topic')} | set(vt))
            vo = sorted({v['object'] for v in synth_lab.values() if v.get('object')} | set(vo))

    print()
    print('真实库已标 %d / %d；合成库已标 %d / %d'
          % (len(real_lab), len(real), len(synth_lab), len(syn)))
    vt = {v['topic'] for v in list(real_lab.values()) + list(synth_lab.values()) if v.get('topic')}
    vo = {v['object'] for v in list(real_lab.values()) + list(synth_lab.values()) if v.get('object')}
    print('标签体系：topic %d 个 / object %d 个' % (len(vt), len(vo)))
    return 0


def _save(prev, real_lab, synth_lab):
    os.makedirs(m.RESULTS, exist_ok=True)
    prev['real'] = real_lab
    prev['synth'] = synth_lab
    prev['generated'] = __import__('time').strftime('%Y-%m-%d %H:%M')
    with io.open(OUT, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(json.dumps(prev, ensure_ascii=False, indent=1) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
