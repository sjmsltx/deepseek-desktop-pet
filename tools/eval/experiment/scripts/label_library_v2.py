# -*- coding: utf-8 -*-
"""标签重标（2026-11-04）—— 修「候选表把 topic 吸走」

## 上一版错在哪

`label_library.py` 给了完整的 topic 候选表（87 个），模型为避免新建标签，
把内容不同的事也塞进就近的候选桶。实测证据：

  · batch 0 讲的是「遥感原理课程」，5 条全被标成「地理数据分析」
  · batch 2 有 7 条不同内容，全进同一个 topic
  · 「用户喜欢小型户外婚礼」→ 个人身份；「线性代数分块矩阵求逆卡了半天」→ Python学习

⇒ **复用率 100% 是买来的，用归并正确性换的。** 这是上一轮没测出的代价。

## 这一版怎么改

  · **不给 topic 候选表**（自由命名，宁可碎也别乱并）
  · 只给 object 候选表（object 是专名，歧义小；且覆盖率仅 4.1%，影响面小）
  · 增加「同 batch 内 topic 唯一性」作为质量指标（这才是真正的归并正确性）

## 为什么不是完全不给候选

如果两个批次的标签不一致，`object` 就失去了复用价值。
object 只占 4.1%，给候选不会造成大面积吸附。

## 指标

  · 同 batch 内 topic 唯一率（越高越好）
  · topic 总数（太少=过并，太多=过碎）
  · 与上一版对比
"""
import importlib.util
import io
import json
import os
import sys
import collections

P = r'D:\ai工作站\desktop-pet\tools\eval\experiment\scripts\probe_entity_v2.py'
sys.path.insert(0, os.path.dirname(P))
spec = importlib.util.spec_from_file_location('pe2', P)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

OUT = os.path.join(m.RESULTS, 'library-labels-v2.json')

PROMPT = """你是记忆结构标注器。下面有几条关于同一个人（用户）的记忆。

{objblock}
对每一条输出三个字段：
1. `topic`：这件事属于哪一类（**4~8 字**，粗粒度）。
   - 说的是「哪一类事」，不是「哪一次」；同一类事要尽量用相同写法
   - ⛔ 不要为了复用而硬套：「婚礼」「驾考」「线性代数」「话费」是不同类别，不能合并
   - 不用「用户」「事情」「记录」这类没有信息量的词
2. `object`：这条具体说的是哪个对象（2~10 字，**没有就写空字符串**）。
   - 有明确专名写专名：「VS Code」「ArcGIS Pro」「合川桃片」
   - 泛指偏好、没有具体对象时留空
3. `aspect`：只能从下列取值中选一个：{aspects}

只输出 json：
{{"items": [{{"i": 0, "topic": "...", "object": "", "aspect": "preference"}}, ...]}}

记忆列表：
<<ITEMS>>"""

OBJ_BLOCK = """**已有对象表**（有对应专名时请复用同一写法）：
{objects}

"""


def label(key, items, vocab_o, tag):
    out = {}
    total = (len(items) + m.BATCH - 1) // m.BATCH
    for s in range(0, len(items), m.BATCH):
        chunk = items[s:s + m.BATCH]
        lines = '\n'.join('%d. %s' % (j, t) for j, (_i, t) in enumerate(chunk))
        objblock = (OBJ_BLOCK.format(objects='、'.join(vocab_o)) if vocab_o else '')
        prompt = (PROMPT.format(objblock=objblock, aspects=m.ASPECT_DOC)
                  .replace('<<ITEMS>>', lines))
        txt, _u, fin = m.call(key, prompt, temperature=0.0)
        got = m.parse(txt, len(chunk), 'B')
        if not got:
            print('    [%s] 第 %d 批失败 fin=%s' % (tag, s // m.BATCH, fin))
        for j, (fid, _t) in enumerate(chunk):
            out[fid] = got.get(j) or {}
        if (s // m.BATCH) % 20 == 0:
            print('    [%s] %d/%d' % (tag, s // m.BATCH + 1, total))
    return out


def quality(items_with_batch, labs):
    """同 batch 内 topic 唯一率（真正的归并正确性指标）"""
    byb = collections.defaultdict(set)
    for fid, b in items_with_batch:
        L = labs.get(fid) or {}
        if L.get('topic'):
            byb[b].add(L['topic'])
    if not byb:
        return 0.0, 0
    uniq = sum(1 for v in byb.values() if len(v) == 1)
    return uniq / float(len(byb)), len(byb)


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

    # 老库（v1）用于对比
    old = json.loads(io.open(os.path.join(m.RESULTS, 'library-labels.json'),
                             encoding='utf-8').read())

    # ---------- 真实库 ----------
    real = [f for f in json.loads(io.open(os.path.join(m.REPO, 'memory.json'),
                                         encoding='utf-8').read())['facts']
            if f.get('status', 'active') == 'active']
    todo = [(f['id'], (f.get('content') or '').strip()) for f in real
            if f['id'] not in real_lab]
    print('真实库 %d 条，待标 %d' % (len(real), len(todo)))
    if todo:
        vo = sorted({v['object'] for v in real_lab.values() if v.get('object')})
        real_lab.update(label(key, todo, vo, 'real'))
        _save(prev, real_lab, synth_lab)

    # ---------- 合成库 ----------
    syn = json.loads(io.open(os.path.join(m.EXP, 'data', 'memories-1411.json'),
                            encoding='utf-8').read())['facts']
    pairs = [('syn-%04d' % i, int(f.get('batch', -1))) for i, f in enumerate(syn)]
    todo2 = [(sid, (syn[int(sid[4:])].get('content') or '').strip()) for sid, _b in pairs
             if sid not in synth_lab]
    print('合成库 %d 条，待标 %d' % (len(pairs), len(todo2)))
    if todo2:
        step = max(1, len(todo2) // 5)
        for s in range(0, len(todo2), step):
            part = todo2[s:s + step]
            vo = sorted({v['object'] for v in list(real_lab.values())
                         + list(synth_lab.values()) if v.get('object')})
            got = label(key, part, vo, 'syn%d' % (s // step + 1))
            synth_lab.update(got)
            _save(prev, real_lab, synth_lab)

    # ---------- 质量对比 ----------
    q_new, nb = quality(pairs, synth_lab)
    q_old, _ = quality(pairs, old['synth'])
    tn = len({v['topic'] for v in synth_lab.values() if v.get('topic')})
    to = len({v['topic'] for v in old['synth'].values() if v.get('topic')})
    print()
    print('=' * 92)
    print('质量对比（合成库 %d 个 batch）' % nb)
    print('=' * 92)
    print('  %-28s %-12s %-12s' % ('指标', 'v1(给topic候选)', 'v2(不给topic候选)'))
    print('  ' + '-' * 56)
    print('  %-28s %-12s %-12s' % ('同 batch 内 topic 唯一率', '%.1f%%' % (100 * q_old),
                                   '%.1f%%' % (100 * q_new)))
    print('  %-28s %-12s %-12s' % ('topic 总数', to, tn))
    print()
    print('  （唯一率越高 = 同一段对话里的记忆没被拆到不同主题；也说明没被别处吸走）')

    prev['quality'] = {'v1_batch_pure_pct': round(100 * q_old, 1),
                       'v2_batch_pure_pct': round(100 * q_new, 1),
                       'v1_topics': to, 'v2_topics': tn,
                       'n_batches': nb}
    _save(prev, real_lab, synth_lab)

    # ---------- 真实库逐条 ----------
    print()
    print('真实库 21 条 v2 标注：')
    for f in real:
        L = real_lab.get(f['id']) or {}
        print('  [%-10s] %-14s %s' % (L.get('aspect', '')[:10], (L.get('topic') or '')[:14],
                                      (f.get('content') or '')[:44]))
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
