# -*- coding: utf-8 -*-
"""真实库的分组标注（2026-11-04）

## 问题

v3 对真实库是**逐条**标的（21 条各自一个 topic），而合成库是**按对话分组**标的。
结果真实库的 topic 落得极散，按 topic 聚合后 21 条几乎全落进同一类 ⇒ 1 个实体 ⇒ 召回从 11/12 掉到 8/12。

## 为什么真实库不能直接套 batch

真实库 `memory.json` 没有 batch 字段（它是一条条攒起来的，不是分批生成的）。
所以得先分组：「这几条在说同一件事」。

## 分组依据（可解释、可复核）

按 object 分组（有专名的先各自成组），再按 topic 名称归一。
但真实库 object 覆盖率低 ⇒ 主要靠 topic 名称。

⇒ 更稳的办法：**用现有标签做一次"两两是否同一件事"的判定**，
    让模型看 21 条，直接输出分组。21 条一次调用就够。

## 验收

  · 分组数（应在 5~14 之间：小于 5 = 过并，大于 15 = 过碎）
  · 每组内是否真在说同一件事（逐组打印）
  · 用这个分组重跑注入，召回能否回到 11/12
"""
import importlib.util
import io
import json
import os
import sys

P = r'D:\ai工作站\desktop-pet\tools\eval\experiment\scripts\probe_entity_v2.py'
sys.path.insert(0, os.path.dirname(P))
spec = importlib.util.spec_from_file_location('pe2', P)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

OUT = os.path.join(m.RESULTS, 'real-groups.json')

PROMPT = """下面是一个人的 21 条记忆。请你把它们**按「说的是不是同一件事」分组**。

分组规则：
1. 同一件事 → 同一组（例：「爱吃桃片」「吃桃片要现切的」是同一件事）
2. 不同的事 → 不同组（例：「爱吃桃片」与「在学 Python」是两件事）
3. 每组给一个 `topic`（4~8 字，这件事是什么）
4. 每组给一个 `object`（2~10 字，具体对象；没有就写空字符串）
5. 组数不限，但**不要为了凑数把无关的东西并在一起**

只输出 json：
{{"groups": [{{"topic": "...", "object": "", "items": [0, 1, 2]}}, ...]}}

记忆列表：
<<ITEMS>>"""


def main():
    key = m._read_key()
    real = [f for f in json.loads(io.open(os.path.join(m.REPO, 'memory.json'),
                                         encoding='utf-8').read())['facts']
            if f.get('status', 'active') == 'active']
    print('真实库 %d 条' % len(real))
    for i, f in enumerate(real):
        print('  %2d. %s' % (i, (f.get('content') or '')[:58]))

    lines = '\n'.join('%d. %s' % (i, (f.get('content') or '').strip())
                      for i, f in enumerate(real))
    txt, usage, fin = m.call(key, PROMPT.replace('<<ITEMS>>', lines), temperature=0.0)
    print()
    print('finish=%s' % fin)
    try:
        d = json.loads(txt)
    except ValueError:
        print('解析失败，原始返回：')
        print((txt or '')[:800])
        return 1

    groups = d.get('groups') or []
    ASPECT_OF = {}
    try:
        prev = json.loads(io.open(os.path.join(m.RESULTS, 'library-labels-v3.json'),
                                  encoding='utf-8').read())
        ASPECT_OF = {k: (v.get('aspect') or 'episode')
                     for k, v in (prev.get('real') or {}).items()}
    except (OSError, ValueError):
        ASPECT_OF = {}
    print('（沿用之前标注的 aspect，%d 条有值）' % len(ASPECT_OF))
    lab = {}
    print()
    print('=' * 96)
    print('分成 %d 组' % len(groups))
    print('=' * 96)
    seen = set()
    for g in groups:
        topic = str(g.get('topic') or '').strip()
        obj = str(g.get('object') or '').strip()
        idxs = [int(x) for x in (g.get('items') or []) if isinstance(x, (int, float, str))]
        print()
        print('  【%s｜%s】%d 条' % (topic, obj or '(无对象)', len(idxs)))
        for i in idxs:
            if not (0 <= i < len(real)):
                continue
            seen.add(i)
            print('     %s' % (real[i].get('content') or '')[:60])
            lab[real[i]['id']] = {'topic': topic, 'object': obj,
                                  'aspect': ASPECT_OF.get(real[i]['id'], 'episode')}
    miss = [i for i in range(len(real)) if i not in seen]
    print()
    print('  未分组：%d 条 %s' % (len(miss), miss))
    for i in miss:
        lab[real[i]['id']] = {'topic': '未分组', 'object': '',
                              'aspect': 'episode'}

    n_g = len({v['topic'] for v in lab.values()})
    print('  最终 topic 种类 %d（21 条）' % n_g)
    print('  判读：%s'
          % ('组数合理' if 5 <= n_g <= 15 else
             ('过并（%d 组太少）' % n_g if n_g < 5 else '过碎（%d 组太多）' % n_g)))

    with io.open(OUT, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(json.dumps({'generated': __import__('time').strftime('%Y-%m-%d %H:%M'),
                             'groups': lab, 'n_groups': n_g,
                             'usage': usage}, ensure_ascii=False, indent=1) + '\n')
    print()
    print('  已写 %s' % OUT)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
