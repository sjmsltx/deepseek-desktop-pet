# -*- coding: utf-8 -*-
"""E7 增量标注：把已有标签当候选喂回去（2026-11-04）

## 为什么必须测这一项

E3 显示：打乱顺序 + temp=0.3 时，标签自一致从 96.6% 掉到 74.5%。
而在真实产品里，标签是**长期累积**的：今天标注的记忆，明天要和三个月前的对齐。
如果每次都由模型自由命名，标签会越拆越碎（v1 的 210 个 key / 235 条就是预演）。

⇒ 生产可用性取决于一件事：**给模型一份已有标签表，它会不会复用**。

## 测法（模拟库增长）

1. 先标前一半（120 条），收集它产生的标签表
2. 再标后一半（115 条），**提示词里带上第 1 步的标签表**，要求能复用就复用
3. 指标：
   - 复用率：后一半里有多少条用了已有标签
   - 新建标签数：新增了几个（越少越好）
   - 跨半一致性：同一个 batch 的条目如果横跨两半，前后是否落到同一 key
   - 判别冲突：拉丁专名互斥的条目是否仍被归为同一 key
"""
import importlib.util
import io
import json
import os
import re
import sys
import collections

P = r'D:\ai工作站\desktop-pet\tools\eval\experiment\scripts\probe_entity_v2.py'
sys.path.insert(0, os.path.dirname(P))
spec = importlib.util.spec_from_file_location('pe2', P)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

RESULTS = m.RESULTS
OUT = os.path.join(RESULTS, 'entity-extraction.json')

PROMPT_C = """你是记忆结构标注器。下面有几条关于同一个人（用户）的记忆。

**已有主题标签表**（请优先复用；只有确实不属于任何已有标签时才新建）：
{labels}

对每一条输出三个字段：
1. `topic`：优先从上面标签表里选一个完全相同的写法；确实都不合适才新建（4~8 字）
2. `object`：这条具体说的是哪个对象（2~10 字，**没有就写空字符串**）
3. `aspect`：只能从下列取值中选一个：%s

只输出 json：
{{"items": [{{"i": 0, "topic": "...", "object": "", "aspect": "preference"}}, ...]}}

记忆列表：
{items}""" % m.ASPECT_DOC


def main():
    key = m._read_key()
    facts = m.load_sample()
    n = len(facts)
    half = n // 2
    print('评测集 %d 条，前半 %d / 后半 %d' % (n, half, n - half))

    # ── 先标前半（不带标签表，用与 B_p1 相同口径）──
    first = list(range(half))
    res1 = {}
    for s in range(0, len(first), m.BATCH):
        chunk = first[s:s + m.BATCH]
        lines = '\n'.join('%d. %s' % (j, facts[gi]['content'])
                          for j, gi in enumerate(chunk))
        txt, _u, fin = m.call(key, m.PROMPT_B.format(items=lines), temperature=0.0)
        got = m.parse(txt, len(chunk), 'B')
        if not got:
            print('  [前半] 第 %d 批失败 %s' % (s // m.BATCH, fin))
        for j, gi in enumerate(chunk):
            res1[gi] = got.get(j, {})
    print('前半完成，%d 条' % sum(1 for v in res1.values() if v.get('topic')))

    vocab = sorted({v['topic'] for v in res1.values() if v.get('topic')})
    print('前半产生 %d 个 topic 标签' % len(vocab))

    # ── 再标后半（带标签表）──
    second = list(range(half, n))
    res2 = {}
    lab = '\n'.join('- ' + t for t in vocab)
    for s in range(0, len(second), m.BATCH):
        chunk = second[s:s + m.BATCH]
        lines = '\n'.join('%d. %s' % (j, facts[gi]['content'])
                          for j, gi in enumerate(chunk))
        txt, _u, fin = m.call(key, PROMPT_C.format(labels=lab, items=lines),
                              temperature=0.0)
        got = m.parse(txt, len(chunk), 'B')
        if not got:
            print('  [后半] 第 %d 批失败 %s' % (s // m.BATCH, fin))
        for j, gi in enumerate(chunk):
            res2[gi] = got.get(j, {})
    print('后半完成，%d 条' % sum(1 for v in res2.values() if v.get('topic')))

    V = set(vocab)
    reused = [i for i, v in res2.items() if v.get('topic') and m.norm(v['topic']) in
              {m.norm(x) for x in V}]
    new_labels = sorted({v['topic'] for v in res2.values()
                         if v.get('topic') and m.norm(v['topic']) not in {m.norm(x) for x in V}})
    ok2 = sum(1 for v in res2.values() if v.get('topic'))
    print()
    print('=' * 96)
    print('E7 结果')
    print('=' * 96)
    print('  后半 %d 条中，复用已有标签 %d 条 = %.1f%%'
          % (ok2, len(reused), 100.0 * len(reused) / max(ok2, 1)))
    print('  新建标签 %d 个：%s' % (len(new_labels), new_labels[:8]))

    # 跨半一致性：同一 batch 横跨前后两半
    by_b1 = collections.defaultdict(list)
    by_b2 = collections.defaultdict(list)
    for i, v in res1.items():
        if v.get('topic'):
            by_b1[int(facts[i]['batch'])].append(m.key_of(v, 'B', 'obj'))
    for i, v in res2.items():
        if v.get('topic'):
            by_b2[int(facts[i]['batch'])].append(m.key_of(v, 'B', 'obj'))
    cross = [b for b in by_b1 if b in by_b2]
    same = sum(1 for b in cross if set(by_b1[b]) & set(by_b2[b]))
    print('  横跨前后两半的 batch：%d 个，其中前后落到同一 key 的 %d 个 = %.1f%%'
          % (len(cross), same, 100.0 * same / max(len(cross), 1)))

    # 判别冲突（后半，用 object 优先判据）
    conf = []
    idx2 = [i for i, v in res2.items() if v.get('topic')]
    for a in range(len(idx2)):
        for b in range(a + 1, len(idx2)):
            ia, ib = idx2[a], idx2[b]
            la = m.latins(facts[ia]['content'])
            lb = m.latins(facts[ib]['content'])
            if not la or not lb or (la & lb):
                continue
            oa = m.norm(res2[ia].get('object'))
            ob = m.norm(res2[ib].get('object'))
            if oa and ob and oa != ob:
                continue
            ka = m.key_of(res2[ia], 'B', 'obj')
            kb = m.key_of(res2[ib], 'B', 'obj')
            if ka and ka == kb:
                conf.append((ia, ib, ka))
    print('  判别冲突 %d 组' % len(conf))
    for a, b, kk in conf[:4]:
        print('    key=%r' % kk)
        print('       %s' % facts[a]['content'][:50])
        print('       %s' % facts[b]['content'][:50])

    print()
    print('  ⇒ 判读（由数据生成）：')
    reuse_pct = 100.0 * len(reused) / max(ok2, 1)
    print('    复用率 %.1f%% %s'
          % (reuse_pct, '⇒ 模型愿意复用，标签不会无限分裂'
             if reuse_pct >= 60 else '⇒ 复用率偏低，标签仍会缓慢膨胀'))
    print('    新建 %d 个 %s'
          % (len(new_labels), '（少量，可接受）' if len(new_labels) <= 0.2 * len(V) else
             '（偏多，需要更硬的约束或事后归并）'))
    print('    跨半一致 %d/%d %s'
          % (same, len(cross), '⇒ 库增长后同类记忆仍能对齐'
             if cross and same == len(cross) else
             '⇒ 有对齐失败，需在抽取时把 object 也纳入候选表'))

    prev = json.loads(io.open(OUT, encoding='utf-8').read())
    prev['E7_incremental'] = {
        'n_first': half, 'n_second': n - half,
        'vocab_size': len(vocab),
        'reuse_pct': round(reuse_pct, 1),
        'new_labels': new_labels[:30], 'n_new_labels': len(new_labels),
        'cross_batches': len(cross), 'cross_aligned': same,
        'conflicts': len(conf),
    }
    with io.open(OUT, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(json.dumps(prev, ensure_ascii=False, indent=1) + '\n')
    print()
    print('  已写入 %s' % OUT)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
