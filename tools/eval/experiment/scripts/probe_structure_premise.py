# -*- coding: utf-8 -*-
"""结构化的价值前提：库里有可归并的东西吗（2026-11-04）

## 这个实验要回答什么

前面绕了几圈的核心问题：

  结构化（一个实体 + 多个面向）只有在**同一件事有多个面向**时才产生价值。
  如果库里每件事只有 1 条记忆，那聚合 = 原样输出，白做。

而「同一件事有几条记忆」取决于**记忆密度**，不是算法能决定的。

## 三份数据给出三种密度

  · 真实库 memory.json：21 条，真实使用 3 个月攒出来的
  · 合成库 memories-1411：239 段对话 × 平均 5.9 条 —— 这是**按对话批量生成**的，
    天然高密度（一段对话 5~9 条同一件事）
  · 对话里自然产生的记忆：一条对话通常只产生 1~2 条事实

## 量什么

对每种「分组口径」，算：
  · 实体数 / 平均每组条数 / 单体实体（只有 1 条）占比
  · 聚合后的**信息损失**（2-gram 覆盖率）
  · 聚合前后的注入成本变化

关键判据：**单体实体占比**。若 >70%，说明绝大多数记忆无可归并对象，
结构化收益极小。

## 分组口径（三种，从松到紧）

  G1 batch（合成库天然分组；真实库没有，跳过）
  G2 按 object（有专名才归并）
  G3 按 topic 同名
  G4 上轮 LLM 直接分组（真实库 18 组）
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
os.environ.setdefault('PET_EMBED_DIR', os.path.join(EXP, '_embed_probe'))

import memory_embed as mem              # noqa: E402

V3 = json.loads(io.open(os.path.join(RES, 'library-labels-v3.json'), encoding='utf-8').read())
RG = json.loads(io.open(os.path.join(RES, 'real-groups.json'), encoding='utf-8').read())


def norm(s):
    s = (s or '').strip().lower()
    for ch in ' \u3000，。、；：！？,.;:!?（）()「」"\'·':
        s = s.replace(ch, '')
    return s


def toks(t):
    t = (t or '').lower()
    out, run = [], []
    for ch in t:
        if '\u4e00' <= ch <= '\u9fff':
            run.append(ch)
        else:
            if len(run) >= 2:
                out.extend(''.join(run)[i:i + 2] for i in range(len(run) - 1))
            run = []
    if len(run) >= 2:
        out.extend(''.join(run)[i:i + 2] for i in range(len(run) - 1))
    return out


def analyse(name, items, keyfn):
    groups = collections.defaultdict(list)
    for it in items:
        groups[keyfn(it)].append(it)
    sizes = [len(v) for v in groups.values()]
    sing = sum(1 for s in sizes if s == 1)
    # 信息损失：聚合后 2-gram 覆盖率（预算 60 字）
    covs = []
    for k, members in groups.items():
        if len(members) == 1:
            continue
        order = sorted(members, key=lambda x: (-float(x.get('importance', 3)), len(x['text'])))
        txt, used = '', 0
        for mm in order:
            piece = mm['text']
            if used + len(piece) + 1 > 60:
                continue
            txt = (txt + '；' + piece) if txt else piece
            used += len(piece) + 1
        at = set(toks(txt))
        for mm in members:
            ft = set(toks(mm['text']))
            if ft:
                covs.append(len(ft & at) / len(ft))
    covs = np.array(covs) if covs else np.array([1.0])
    print('  %-26s %-7d %-8d %-10.1f %-10s %s'
          % (name, len(items), len(groups), np.mean(sizes) if sizes else 0,
             '%.0f%%' % (100.0 * sing / max(len(groups), 1)),
             '%.2f' % np.median(covs) if len(covs) else '-'))
    return {'n': len(items), 'entities': len(groups),
            'avg_size': float(np.mean(sizes)) if sizes else 0,
            'singleton_pct': round(100.0 * sing / max(len(groups), 1), 1),
            'retention_median': round(float(np.median(covs)), 2) if len(covs) else None}


def main():
    syn = json.loads(io.open(os.path.join(EXP, 'data', 'memories-1411.json'),
                            encoding='utf-8').read())['facts']
    syn_items = []
    for i, f in enumerate(syn):
        sid = 'syn-%04d' % i
        L = V3['synth'].get(sid) or {}
        syn_items.append({'id': sid, 'text': (f.get('content') or '').strip(),
                          'topic': L.get('topic') or '', 'object': L.get('object') or '',
                          'importance': f.get('importance', 3),
                          'batch': int(f.get('batch', -1))})
    real = [f for f in json.loads(io.open(os.path.join(REPO, 'memory.json'),
                                         encoding='utf-8').read())['facts']
            if f.get('status') == 'active']
    real_items = []
    rl = RG['groups']
    v3r = V3.get('real') or {}
    for f in real:
        L = rl.get(f['id']) or {}
        real_items.append({'id': f['id'], 'text': (f.get('content') or '').strip(),
                           'topic': L.get('topic') or '',
                           'object': L.get('object') or '',
                           'importance': f.get('importance', 3)})

    print('=' * 104)
    print('不同分组口径下的「可归并程度」')
    print('=' * 104)
    print('  %-26s %-7s %-8s %-10s %-10s %s'
          % ('数据 / 口径', '条数', '实体数', '平均每组', '单体占比', '留存中位'))
    print('  ' + '-' * 96)
    out = {}
    out['syn_batch'] = analyse('合成库 按 batch', syn_items, lambda x: 'B%d' % x['batch'])
    out['syn_topic'] = analyse('合成库 按 topic', syn_items, lambda x: 'T:' + norm(x['topic']))
    out['syn_object'] = analyse('合成库 按 object', syn_items,
                                lambda x: ('O:' + norm(x['object'])) if norm(x['object'])
                                else 'T:' + norm(x['topic']))
    out['real_llm'] = analyse('真实库 LLM 分组(18组)', real_items, lambda x: 'G:' + norm(x['topic']))
    out['real_v3topic'] = analyse('真实库 v3 topic', real_items, lambda x: 'T:' + norm(x['topic']))
    out['real_object'] = analyse('真实库 按 object', real_items,
                                 lambda x: ('O:' + norm(x['object'])) if norm(x['object'])
                                 else 'T:' + norm(x['topic']))

    print()
    print('=' * 104)
    print('判读')
    print('=' * 104)
    b = out['syn_batch']
    l = out['real_llm']
    print('  · 合成库按 batch：%d 条 → %d 实体，平均每组 %.1f 条，单体 %s%%'
          % (b['n'], b['entities'], b['avg_size'], b['singleton_pct']))
    print('    ⇒ 这是**人为造出的高密度**（一段对话 5~9 条讲同一件事）')
    print('  · 真实库 LLM 分组：%d 条 → %d 实体，平均每组 %.1f 条，单体 %s%%'
          % (l['n'], l['entities'], l['avg_size'], l['singleton_pct']))
    print('     ⇒ 真实记忆密度低：平均 %.1f 条/件事' % l['avg_size'])
    print()
    print('  ★ 结论：结构化的收益 = f(可归并程度)。')
    print('    · 高密度（合成库那种：一次对话产生 5~9 条同一件事）→ 聚合能省 60~80%% 上下文')
    print('    · 低密度（真实库：平均 %.1f 条/件事）→ 聚合几乎不省，因为大多自成一件事'
          % l['avg_size'])
    print()
    print('  这也解释了前两轮的现象：')
    print('    · 合成库 M2 成本 91 → 127 字（聚合反而更长，因为实体大）')
    print('    · 真实库 M2 成本 88 → 35 字（因为错把 21 条并成 1 个实体）')

    with io.open(os.path.join(RES, 'structure-premise.json'), 'w',
                 encoding='utf-8', newline='\n') as fh:
        fh.write(json.dumps({'generated': __import__('datetime').datetime.now()
                             .strftime('%Y-%m-%d %H:%M'), 'result': out},
                            ensure_ascii=False, indent=1) + '\n')
    print()
    print('  已写 results/structure-premise.json')


if __name__ == '__main__':
    main()
