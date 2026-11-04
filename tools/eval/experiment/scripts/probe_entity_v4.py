# -*- coding: utf-8 -*-
"""E7b 增量标注（修正版，2026-11-04）

## 上一版 E7 的测试设计错误

样本是按 batch 连续排列的（每个 batch 的 3 条挨在一起），于是「前一半 / 后一半」
按索引切分后**没有任何 batch 横跨两半** ⇒ 跨半一致性 0/0 是空指标，
我却把它判成「有对齐失败」。已撤回。

## 这一版怎么改

1. 先用固定种子**打散**样本，让 batch 交错
2. 候选表同时给 **topic 列表 + object 列表**（E2 显示 object 自一致 96.7% > topic 88.1%，
   所以 object 更该被复用）
3. 指标：topic 复用率 / object 复用率 / 跨半 batch 对齐率 / 判别冲突

## 为什么要做这一项

真实产品里标签是长期累积的：今天标的东西明天要和几个月前的对齐。
若每次自由命名，标签会越拆越碎（v1 的 235 条 → 210 个 key 就是预演）。
"""
import collections
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

OUT = os.path.join(m.RESULTS, 'entity-extraction.json')

PROMPT_C2 = """你是记忆结构标注器。下面有几条关于同一个人（用户）的记忆。

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


def label_chunk(key, facts, chunk, prompt):
    """prompt 可能已用 format 填过 topic/object 候选表 ⇒ 条目用哨兵替换，不再 format。"""
    lines = '\n'.join('%d. %s' % (j, (facts[gi].get('content') or '').strip())
                      for j, gi in enumerate(chunk))
    if '<<ITEMS>>' in prompt:
        full = prompt.replace('<<ITEMS>>', lines)
    else:
        full = prompt.format(items=lines)
    txt, _u, fin = m.call(key, full, temperature=0.0)
    got = m.parse(txt, len(chunk), 'B')
    if not got:
        print('    批次失败 fin=%s' % fin)
    return {gi: got.get(j, {}) for j, gi in enumerate(chunk)}


def main():
    key = m._read_key()
    facts = m.load_sample()
    order = list(range(len(facts)))
    random.Random(4242).shuffle(order)          # 打散，让 batch 交错
    half = len(order) // 2
    first, second = order[:half], order[half:]

    # 检查：有多少 batch 横跨两半
    b1 = {int(facts[i]['batch']) for i in first}
    b2 = {int(facts[i]['batch']) for i in second}
    cross = sorted(b1 & b2)
    print('打散后：前 %d / 后 %d；横跨两半的 batch %d 个'
          % (len(first), len(second), len(cross)))
    assert len(cross) >= 10, '横跨 batch 太少（%d），这项测不准' % len(cross)

    print('\n[第 1 步] 标前一半（无候选表）')
    res1 = {}
    for s in range(0, len(first), m.BATCH):
        res1.update(label_chunk(key, facts, first[s:s + m.BATCH], m.PROMPT_B))
        print('   %d/%d' % (s // m.BATCH + 1, (len(first) + m.BATCH - 1) // m.BATCH))
    vocab_t = sorted({v['topic'] for v in res1.values() if v.get('topic')})
    vocab_o = sorted({v['object'] for v in res1.values() if v.get('object')})
    print('   前一半产生 topic %d 个 / object %d 个' % (len(vocab_t), len(vocab_o)))

    print('\n[第 2 步] 标后一半（带 topic + object 候选表）')
    res2 = {}
    for s in range(0, len(second), m.BATCH):
        chunk = second[s:s + m.BATCH]
        prompt = PROMPT_C2.format(
            topics='、'.join(vocab_t) if vocab_t else '（空）',
            objects='、'.join(vocab_o) if vocab_o else '（空）',
            aspects=m.ASPECT_DOC)
        res2.update(label_chunk(key, facts, chunk, prompt))
        print('   %d/%d' % (s // m.BATCH + 1, (len(second) + m.BATCH - 1) // m.BATCH))

    VT = {m.norm(x) for x in vocab_t}
    VO = {m.norm(x) for x in vocab_o}
    ok2 = [i for i, v in res2.items() if v.get('topic')]
    rt = [i for i in ok2 if m.norm(res2[i]['topic']) in VT]
    ro = [i for i in ok2 if res2[i].get('object') and m.norm(res2[i]['object']) in VO]
    with_obj = [i for i in ok2 if res2[i].get('object')]
    new_t = sorted({res2[i]['topic'] for i in ok2 if m.norm(res2[i]['topic']) not in VT})

    print()
    print('=' * 96)
    print('E7b 结果')
    print('=' * 96)
    print('  后半 %d 条有 topic' % len(ok2))
    print('    topic 复用 %d 条 = %.1f%%；新建 %d 个：%s'
          % (len(rt), 100.0 * len(rt) / max(len(ok2), 1), len(new_t), new_t[:6]))
    print('    有 object %d 条，其中复用已有对象 %d 条 = %.1f%%'
          % (len(with_obj), len(ro), 100.0 * len(ro) / max(len(with_obj), 1)))

    # 跨半对齐：同一 batch 的前半 key 与后半 key 是否有交集
    k1 = collections.defaultdict(set)
    k2 = collections.defaultdict(set)
    for i, v in res1.items():
        if v.get('topic'):
            k1[int(facts[i]['batch'])].add(m.key_of(v, 'B', 'obj'))
    for i, v in res2.items():
        if v.get('topic'):
            k2[int(facts[i]['batch'])].add(m.key_of(v, 'B', 'obj'))
    aligned = [b for b in cross if k1.get(b) and k2.get(b) and (k1[b] & k2[b])]
    print('    横跨 batch %d 个，前后落到同一 key 的 %d 个 = %.1f%%'
          % (len(cross), len(aligned), 100.0 * len(aligned) / max(len(cross), 1)))
    fail = [b for b in cross if b not in aligned]
    for b in fail[:4]:
        print('      未对齐 batch %d：前 = %s / 后 = %s'
              % (b, sorted(k1.get(b) or {'(空)'}), sorted(k2.get(b) or {'(空)'})))

    # 判别冲突（后半）
    conf = []
    idx2 = sorted(ok2)
    for a in range(len(idx2)):
        for c in range(a + 1, len(idx2)):
            ia, ib = idx2[a], idx2[c]
            la, lb = m.latins(facts[ia]['content']), m.latins(facts[ib]['content'])
            if not la or not lb or (la & lb):
                continue
            oa, ob = m.norm(res2[ia].get('object')), m.norm(res2[ib].get('object'))
            if oa and ob and oa != ob:
                continue
            ka, kb = m.key_of(res2[ia], 'B', 'obj'), m.key_of(res2[ib], 'B', 'obj')
            if ka and ka == kb:
                conf.append((ia, ib, ka, oa, ob))
    print('    判别冲突 %d 组' % len(conf))
    for ia, ib, kk, oa, ob in conf[:4]:
        print('      key=%r（object=%r / %r）' % (kk, oa, ob))
        print('         %s' % facts[ia]['content'][:48])
        print('         %s' % facts[ib]['content'][:48])

    print()
    reuse_t = 100.0 * len(rt) / max(len(ok2), 1)
    reuse_o = 100.0 * len(ro) / max(len(with_obj), 1)
    align_pct = 100.0 * len(aligned) / max(len(cross), 1)
    print('  ⇒ 判读（由数据生成）：')
    print('    topic 复用 %.1f%% ⇒ %s'
          % (reuse_t, '愿意复用' if reuse_t >= 70 else '仍会膨胀，topic 不能单独当主键'))
    print('    object 复用 %.1f%% ⇒ %s'
          % (reuse_o, '稳定，可当主键' if reuse_o >= 80 else '不够稳，需再加约束'))
    print('    跨半对齐 %.1f%% ⇒ %s'
          % (align_pct, '库增长后同类记忆能对齐' if align_pct >= 80
             else '库增长后会对不上，必须靠 object 对齐'))

    prev = json.loads(io.open(OUT, encoding='utf-8').read())
    prev['E7b_incremental'] = {
        'shuffled': True, 'cross_batches': len(cross),
        'topic_vocab': len(vocab_t), 'object_vocab': len(vocab_o),
        'topic_reuse_pct': round(reuse_t, 1), 'new_topics': len(new_t),
        'object_reuse_pct': round(reuse_o, 1),
        'cross_aligned_pct': round(align_pct, 1),
        'conflicts': len(conf),
    }
    prev.pop('E7_incremental', None)      # 撤掉上一版失效指标，避免被误引
    with io.open(OUT, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(json.dumps(prev, ensure_ascii=False, indent=1) + '\n')
    print()
    print('  已写 %s（并移除上一版失效的 E7_incremental）' % OUT)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
