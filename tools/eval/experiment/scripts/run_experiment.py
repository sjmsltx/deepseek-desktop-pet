# -*- coding: utf-8 -*-
"""1200 条记忆实验：生成 + 抽取 + 时间回填（2026-11-03）

## Owner 的要求

「整个 1200 条算了，然后你要人工加快时间进展，不然那个测试不出来」

## 设计

### ① 语料 → 对话 → 记忆（三步，都走真实链路）

```
corpus.json（1200 条种子）
   ↓ 每 5 条种子拼成一段「像真的」对话（模型展开）
写成 240 段对话
   ↓ memory_engine.extract_memories() —— **产品自己的抽取函数**
240 次抽取 → 约 1200 条 facts + events
   ↓ timeline_plan.json 的年龄表
回填时间戳（跨 730 天）
```

### ② 为什么是「5 条种子→1 段对话→多次抽取」

试过直接 1 种子 1 次调用：1200 次调用 ≈ ¥2.5，但每次只有 1 句话，抽出来全是碎片。
拼成对话后，抽取器能看到上下文，产出更接近真实记忆（一条对话里带出相关事实）。

### ③ 断点续传

1200 条要跑 40+ 分钟。每 10 批落盘一次，中断后从 `progress.json` 续跑。

### ④ 成本控制

| 阶段 | 调用数 | 单价 | 小计 |
|---|---|---|---|
| 展开对话（240 段） | 240 | ¥0.0025 | ¥0.60 |
| 抽取（240 次） | 240 | ¥0.0021 | ¥0.50 |
| **合计** | **480** | | **≈¥1.1** |

比直接 1200 次调用便宜一半，且产出质量更好。

## ⛔ 边界

- 输出写本目录 `experiment.json`，**绝不碰真实 memories.json / memory.json**
- 只调 deepseek-flash
"""
import io
import json
import os
import random
import re
import sys
import time

import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
OUT = _os.path.dirname(_HERE)                  # 本实验目录（data/ 与 results/ 的父目录）
DATA = _os.path.join(OUT, 'data')              # 只读：语料 / 时间轴 / 1411 条记忆
RESULTS = _os.path.join(OUT, 'results')        # 只写：各脚本的分析结果
REPO = _os.path.dirname(_os.path.dirname(_os.path.dirname(OUT)))  # 仓库根（上溯 3 层）
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import deepseek_client  # noqa: E402
import memory_engine as me  # noqa: E402

def _rjson(path):
    """读 JSON。with 包裹 —— 产品代码禁止一行式 open（长驻进程里是真实句柄泄漏）。"""
    with io.open(path, encoding='utf-8') as _f:
        return json.loads(_f.read())


def _wjson(path, obj, **kw):
    """写 JSON（同 _rjson 的理由）。默认 ensure_ascii=False、indent=1。"""
    kw.setdefault('ensure_ascii', False)
    kw.setdefault('indent', 1)
    with io.open(path, 'w', encoding='utf-8', newline='\n') as _f:
        _f.write(json.dumps(obj, **kw) + '\n')



CFG = json.loads(io.open(os.path.join(REPO, 'config.json'), encoding='utf-8').read())
KEY = CFG.get('deepseek_api_key') or ''
ENDPOINT = 'https://api.deepseek.com/chat/completions'
MODEL = 'deepseek-flash'
PRICE_IN, PRICE_OUT = 1.0, 4.0

CORPUS = os.path.join(DATA, 'corpus.json')
PLAN = os.path.join(DATA, 'timeline_plan.json')
EXP = os.path.join(DATA, 'memories-1411.json')
PROG = os.path.join(OUT, '.progress.json')      # 断点续传状态，不进仓库

USAGE = {'in': 0, 'out': 0, 'calls': 0}

# ══════════════ 阶段一：把 5 条种子展开成一段对话 ══════════════
EXPAND_PROMPT = """你是对话生成器。把下面 5 个「记忆要点」编成一段**自然的朋友聊天**。

要求：
1. 用户（自称"我"）说出这些信息，桌宠自然回应；桌宠的话要短、口语
2. 每个要点都必须被用户**明确说出**（不能只暗示），但措辞要自然、不要像清单
3. 共 12~16 轮（我/桌宠交替），最后可以用一句收尾
4. 不要输出任何解释、标题、编号，只输出对话本身
5. 格式严格：每行 `我：...` 或 `桌宠：...`

记忆要点：
{points}

对话："""


def call(prompt, max_tokens=1200, temperature=0.8, as_json=False):
    body = {'model': MODEL,
            'messages': [{'role': 'user', 'content': prompt}],
            'max_tokens': max_tokens, 'temperature': temperature}
    if as_json:
        body['response_format'] = {'type': 'json_object'}
    data = json.dumps(body).encode('utf-8')
    resp = deepseek_client.chat_completions(KEY, data, endpoint=ENDPOINT)
    USAGE['calls'] += 1
    u = resp.get('usage') or {}
    USAGE['in'] += int(u.get('prompt_tokens') or 0)
    USAGE['out'] += int(u.get('completion_tokens') or 0)
    ch = resp['choices'][0]
    return (ch['message'].get('content') or ''), ch.get('finish_reason')


def load(p, default=None):
    if os.path.exists(p):
        return _rjson(p)
    return default


def save(p, d):
    _wjson(p, d, indent=1)


def main():
    if not KEY:
        print('✗ 没有 api key')
        return 1

    corpus = load(CORPUS)['corpus']
    plan = load(PLAN)
    stamps = plan['timestamps']
    print('语料 %d 条 / 时间轴 %d 个时间戳' % (len(corpus), len(stamps)))

    # 每 5 条种子 = 1 批
    batches = [corpus[i:i + 5] for i in range(0, len(corpus), 5)]
    print('共 %d 批（每批 5 条种子 → 1 段对话 → 1 次抽取）\n' % len(batches))

    limit = None
    for a in sys.argv[1:]:
        if a.startswith('--limit='):
            limit = int(a.split('=', 1)[1])
    if limit:
        batches = batches[:limit]
        print('⚠ 限定 %d 批（试跑）' % limit)
    if limit:
        prog = {'done': 0, 'facts_n': 0, 'events_n': 0, 'fail': 0}

    exp = load(EXP, {'meta': {}, 'facts': [], 'events': [], 'batches': []})
    prog = load(PROG, {'done': 0, 'facts_n': 0, 'events_n': 0, 'fail': 0})
    start = prog.get('done', 0)
    print('续跑：已完成 %d 批，现有 facts %d / events %d'
          % (start, len(exp['facts']), len(exp['events'])))

    t0 = time.time()
    for bi in range(start, len(batches)):
        batch = batches[bi]
        points = '\n'.join('- [%s/%s] %s' % (c['cat'], c['aspect'], c['text'])
                           for c in batch)
        # ── ① 展开成对话
        # ⚠ 试跑 10 批里 2 批 `finish=length` 且 content 为空 —— 与之前诊断的
        #   「max_tokens 被思考 token 吃掉」是同一形状。deepseek-flash 是推理型，
        #   1200 预算下思考可占满 ⇒ content 空。
        #   ⇒ 改 2400 + 失败自动重试一次（重试时降 temperature，减少发散）。
        dialogue, fin = call(EXPAND_PROMPT.format(points=points),
                             max_tokens=2400, temperature=0.85)
        if not dialogue or len(dialogue) < 60:
            print('  批 %3d：展开首试失败（%s，%d 字），重试…'
                  % (bi + 1, fin, len(dialogue or '')))
            dialogue, fin = call(EXPAND_PROMPT.format(points=points),
                                 max_tokens=2400, temperature=0.5)
        if not dialogue or len(dialogue) < 60:
            prog['fail'] = prog.get('fail', 0) + 1
            prog['done'] = bi + 1
            save(PROG, prog)
            print('  批 %3d：★ 展开两次都失败（%s，%d 字）'
                  % (bi + 1, fin, len(dialogue or '')))
            continue
        # ── ② 走产品自己的抽取
        existing = '；'.join(f['content'][:50] for f in exp['facts'][-10:])
        got = me.extract_memories(
            lambda msgs, mt: call(msgs[0]['content'], max_tokens=2400,
                                  temperature=0.3, as_json=True)[0],
            dialogue, existing=existing)
        nf = len(got.get('facts') or [])
        ne = len(got.get('events') or [])
        if nf == 0 and ne == 0:
            prog['fail'] = prog.get('fail', 0) + 1

        # ── ③ 落盘（带类别标签 + 时间戳占位，稍后回填）
        cats = [c['cat'] for c in batch]
        for f in (got.get('facts') or []):
            c = (f.get('content') or '').strip()
            if c:
                exp['facts'].append({
                    'content': c,
                    'importance': f.get('importance', 3),
                    'status': 'active',
                    'cats': cats,
                    'batch': bi,
                    'age_days': None,     # 稍后按 timeline_plan 回填
                    'created_at': None,
                })
        for e in (got.get('events') or []):
            exp['events'].append({
                'title': (e.get('title') or '').strip(),
                'detail': (e.get('detail') or '').strip(),
                'emotion': (e.get('emotion') or '').strip(),
                'cats': cats, 'batch': bi,
                'age_days': None, 'created_at': None,
            })
        exp['batches'].append({'i': bi, 'dialogue_len': len(dialogue),
                               'facts': nf, 'events': ne, 'finish': fin})

        prog['done'] = bi + 1
        prog['facts_n'] = len(exp['facts'])
        prog['events_n'] = len(exp['events'])

        if (bi + 1) % 10 == 0 or bi == len(batches) - 1:
            save(EXP, exp)
            save(PROG, prog)
            cost = USAGE['in'] / 1e6 * PRICE_IN + USAGE['out'] / 1e6 * PRICE_OUT
            el = time.time() - t0
            done_since = bi + 1 - start
            eta = (len(batches) - bi - 1) * (el / max(done_since, 1)) / 60
            print('  %3d/%d 批  facts %4d  events %3d  失败 %d  ¥%.2f  剩 %.0f 分钟'
                  % (bi + 1, len(batches), len(exp['facts']), len(exp['events']),
                     prog.get('fail', 0), cost, eta))

    save(EXP, exp)
    save(PROG, prog)
    cost = USAGE['in'] / 1e6 * PRICE_IN + USAGE['out'] / 1e6 * PRICE_OUT
    print()
    print('=' * 66)
    print('抽取完成')
    print('=' * 66)
    print('  facts  %d 条' % len(exp['facts']))
    print('  events %d 条' % len(exp['events']))
    print('  失败批 %d / %d' % (prog.get('fail', 0), len(batches)))
    print('  本次调用 %d 次 / ¥%.3f / %.1f 分钟'
          % (USAGE['calls'], cost, (time.time() - t0) / 60))
    print()
    print('  下一步：python backfill_time.py  （回填时间戳）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
