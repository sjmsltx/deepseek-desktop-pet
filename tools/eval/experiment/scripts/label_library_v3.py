# -*- coding: utf-8 -*-
"""标签重标 v3：按 batch 分组标注（2026-11-04）

## v1 / v2 都错在哪

| 版本 | 做法 | 同 batch topic 唯一率 | topic 数 |
|---|---|---|---|
| v1 | 给 86 个 topic 候选表 | 59.4% | 86（过并） |
| v2 | 不给候选表 | 26.4% | 618（过碎） |

两边都错，而且方向相反。根因不是给不给候选表，而是**标注单位错了**：

  ❌ 逐条标：每条记忆各自决定一个 topic ⇒ 同一段对话里的 5 条会得到 5 个 topic
  ✅ 按顿标：**一段对话（batch）先命名一个 topic，再给其中每条分配 aspect**

「一件事的多个面向」这个概念本来就是「一个实体 + 多个 aspect」。
因此正确做法是先定实体（按 batch），再定面向（逐条）。

## v3 做法

1. 按 batch 分组，每批 3~9 条
2. 一次调用处理 2~3 个 batch（同一次上下文里，模型能看到「这几条是一段对话」）
3. 输出：每个 batch 一个 topic + object（可为空）+ 每条一个 aspect
4. 指标：同 batch topic 唯一率、topic 数、aspect 分布

## 这同时解决了 object 覆盖率的问题

object 从「逐条记忆的对象」变成「这段对话谈的对象」——
「和桌宠聊鱼香肉丝」这种对话的 object 就是「鱼香肉丝」，比逐条猜更稳。
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

OUT = os.path.join(m.RESULTS, 'library-labels-v3.json')
BATCHES_PER_CALL = 3

PROMPT = """你在整理一个人的记忆库。下面按「一段对话」分组，每组 3~9 条记忆。

请你**先为每组命名一个主题**，再给组内每条分配一个面向。

规则：
1. `topic`（每组一个，4~8 字）：这段对话整体在说哪一类事。
   - 同组内所有记忆共享这个 topic —— 因为它们是同一次对话里聊出来的
   - ⛔ 不用「用户」「事情」「记录」这类没信息量的词
2. `object`（每组一个，2~10 字，没有就写空字符串）：这段对话具体围绕哪个对象/专名。
   - 例：「合川桃片」「VS Code」「鱼香肉丝」「ArcGIS Pro」
   - 泛泛聊天、没有具体对象时留空
3. `aspect`（每条一个）：这条记忆说的是这件事的哪个面向，只能取：
   {aspects}

只输出 json：
{{"groups": [{{"g": 0, "topic": "...", "object": "", "items": [{{"i": 0, "aspect": "preference"}}, ...]}}, ...]}}

记忆列表：
<<GROUPS>>"""


def make_groups(syn, group_ids, need):
    """把若干 batch 拼成一次调用的素材。

    返回 (文本, 结构)：结构 = [(batch, [(sid, text), ...]), ...]
    """
    lines = []
    shape = []
    for gi, b in enumerate(group_ids):
        members = [(sid, (syn[int(sid[4:])].get('content') or '').strip())
                   for sid in need if sid_batch[sid] == b]
        if not members:
            continue
        shape.append((b, members))
        lines.append('【第 %d 组】' % len(shape))
        for j, (_sid, t) in enumerate(members):
            lines.append('  %d. %s' % (j, t))
    return '\n'.join(lines), shape


def label_groups(key, syn, batches, tag):
    """按 batch 分组标注，返回 {sid: {topic, object, aspect}}"""
    out = {}
    total = (len(batches) + BATCHES_PER_CALL - 1) // BATCHES_PER_CALL
    for s in range(0, len(batches), BATCHES_PER_CALL):
        gids = batches[s:s + BATCHES_PER_CALL]
        need = [sid for sid, b in sid_batch.items() if b in gids]
        block, shape = make_groups(syn, gids, need)
        if not shape:
            continue
        prompt = PROMPT.format(aspects=m.ASPECT_DOC).replace('<<GROUPS>>', block)
        txt, _u, fin = m.call(key, prompt, temperature=0.0)
        got = parse_groups(txt, shape)
        if not got:
            print('    [%s] 第 %d 批失败 fin=%s' % (tag, s // BATCHES_PER_CALL, fin))
        out.update(got)
        if (s // BATCHES_PER_CALL) % 10 == 0:
            print('    [%s] %d/%d' % (tag, s // BATCHES_PER_CALL + 1, total))
    return out


def parse_groups(txt, shape):
    """解析分组结果，宽松处理 g/i 索引"""
    res = {}
    try:
        d = json.loads(txt)
    except ValueError:
        import re
        mm = re.search(r'\{.*\}', txt or '', re.S)
        if not mm:
            return res
        try:
            d = json.loads(mm.group(0))
        except ValueError:
            return res
    groups = d.get('groups') if isinstance(d, dict) else None
    if not isinstance(groups, list):
        return res
    for g in groups:
        if not isinstance(g, dict):
            continue
        try:
            gi = int(g.get('g'))
        except (TypeError, ValueError):
            continue
        if not (0 <= gi < len(shape)):
            continue
        topic = str(g.get('topic') or '').strip()
        obj = str(g.get('object') or '').strip()
        members = shape[gi][1]
        items = g.get('items') if isinstance(g.get('items'), list) else []
        asp = {}
        for it in items:
            if not isinstance(it, dict):
                continue
            try:
                j = int(it.get('i'))
            except (TypeError, ValueError):
                continue
            if 0 <= j < len(members):
                asp[j] = str(it.get('aspect') or '').strip().lower()
        for j, (sid, _t) in enumerate(members):
            res[sid] = {'topic': topic, 'object': obj, 'aspect': asp.get(j, '')}
    return res


sid_batch = {}


def main():
    key = m._read_key()
    syn = json.loads(io.open(os.path.join(m.EXP, 'data', 'memories-1411.json'),
                            encoding='utf-8').read())['facts']
    global sid_batch
    sid_batch = {'syn-%04d' % i: int(f.get('batch', -1)) for i, f in enumerate(syn)}
    batches = sorted({b for b in sid_batch.values()})
    print('合成库 %d 条 / %d 段对话（每段 3~9 条）' % (len(syn), len(batches)))

    prev = {}
    if os.path.exists(OUT):
        try:
            prev = _rjson(OUT)
        except ValueError:
            prev = {}
    lab = prev.get('synth', {})
    todo = [b for b in batches
            if not any(sid_batch[s] == b and s in lab for s in sid_batch)]
    print('待标 %d 段' % len(todo))
    if todo:
        step = max(1, len(todo) // 5)
        for s in range(0, len(todo), step):
            got = label_groups(key, syn, todo[s:s + step], 'g%d' % (s // step + 1))
            lab.update(got)
            prev['synth'] = lab
            prev['generated'] = __import__('time').strftime('%Y-%m-%d %H:%M')
            with io.open(OUT, 'w', encoding='utf-8', newline='\n') as fh:
                fh.write(json.dumps(prev, ensure_ascii=False, indent=1) + '\n')
            print('    已存 %d 条' % len(lab))

    # ---------- 质量 ----------
    print()
    print('=' * 88)
    print('v3 质量')
    print('=' * 88)
    byb = collections.defaultdict(set)
    for sid, b in sid_batch.items():
        L = lab.get(sid) or {}
        if L.get('topic'):
            byb[b].add(L['topic'])
    uniq = sum(1 for v in byb.values() if len(v) == 1)
    topics = collections.Counter((L.get('topic') or '') for L in lab.values() if L.get('topic'))
    n_obj = sum(1 for L in lab.values() if (L.get('object') or '').strip())
    ac = collections.Counter((L.get('aspect') or '') for L in lab.values() if L.get('aspect'))
    print('  同 batch 内 topic 唯一率：%.1f%%（%d/%d）' % (100.0 * uniq / len(byb), uniq, len(byb)))
    print('  topic 总数：%d' % len(topics))
    print('  object 覆盖：%d / %d = %.1f%%' % (n_obj, len(lab), 100.0 * n_obj / max(len(lab), 1)))
    print('  aspect 分布：%s' % ac.most_common())
    print()
    print('  三版对比：')
    print('    %-10s %-14s %-10s %s' % ('版本', '同batch唯一率', 'topic数', 'object覆盖'))
    old = json.loads(io.open(os.path.join(m.RESULTS, 'library-labels.json'),
                             encoding='utf-8').read())
    for name, data in (('v1 给候选', old['synth']), ('v3 按对话', lab)):
        bb = collections.defaultdict(set)
        for sid, b in sid_batch.items():
            L = data.get(sid) or {}
            if L.get('topic'):
                bb[b].add(L['topic'])
        u = sum(1 for v in bb.values() if len(v) == 1) / max(len(bb), 1)
        tc = len({L.get('topic') for L in data.values() if L.get('topic')})
        no = sum(1 for L in data.values() if (L.get('object') or '').strip())
        print('    %-10s %-14s %-10s %s'
              % (name, '%.1f%%' % (100 * u), tc,
                 '%.1f%%' % (100.0 * no / max(len(data), 1))))
    print('    %-10s %-14s %-10s %s'
          % ('v2 自由命名', '26.4%', 618, '4.1%'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
