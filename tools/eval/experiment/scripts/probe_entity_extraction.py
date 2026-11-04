# -*- coding: utf-8 -*-
"""抽取侧实体/面向标注 —— 可行性验证（2026-11-04）

## 要回答的问题

多维节点原型证明：**事后用余弦聚类分不清「同一件事」和「不同对象同句式」**
（ArcGIS Pro vs MATLAB 余弦 0.866，因为句式都是「长期使用 X，习惯保持好几年」）。

⇒ 假设：把实体判定挪到抽取侧，让 LLM 显式输出 `entity`（这是哪件事）+ `aspect`（哪个面向）。
本脚本就是验这个假设成不成立。

## 六项指标（缺一不可）

  E1 覆盖率：是否每条都能给出 entity / aspect（有没有大量「不知道」）
  E2 稳定性：同一批输入跑两次，entity 标签一致率
  E3 顺序无关：换分组/换顺序重跑，标签是否漂移
  E4 判别力：**关键**。那几组「同句式不同对象」能否给出不同 entity
  E5 结构质量：entity → batch 的纯度/召回（与余弦聚类的 0.758/0.502 对比）
  E6 成本与延迟

## 口径

- 模型 deepseek-flash，**关掉 thinking**（本项目踩过：reasoning_tokens 计入 max_tokens，
  250 预算会被吃光、content 为空）
- 分批 12 条/次，JSON 输出（提示词里必须出现 "json" 字样，否则 400）
- 全量结果落 results/entity-extraction.json，可续跑
"""
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

REPO = r'D:\ai工作站\desktop-pet'
EXP = os.path.join(REPO, 'tools', 'eval', 'experiment')
RESULTS = os.path.join(EXP, 'results')
DATA = os.path.join(EXP, 'data', 'memories-1411.json')

MODEL = 'deepseek-flash'
ENDPOINT = 'https://api.deepseek.com/chat/completions'
BATCH = 12                  # 每次调用的条目数
OUT = os.path.join(RESULTS, 'entity-extraction.json')

PROMPT = """你是记忆结构标注器。下面有几条关于同一个人（用户）的记忆。

对**每一条**输出两个字段：
1. `entity`：这件事「是什么」（一个短语，4~10 字）。要求：
   - **同一件事必须用完全相同的写法**。例如两条都在说喝咖啡，都写「咖啡偏好」
   - 不同对象必须写成不同 entity。例如「编辑器偏好」与「操作系统偏好」是两个
   - 不要用「用户」「偏好」这种太泛的词单独作 entity
2. `aspect`：这条说的是这件事的哪个面向，只能从下列取值中选一个：
   preference（偏好/喜好）、habit（长期习惯/坚持多久）、change（前后变化/态度转变）、
   struggle（困难/卡点）、advice（他人建议/外部信息）、episode（某次具体经历/聊天）

只输出 json，格式：
{{"items": [{{"i": 0, "entity": "...", "aspect": "preference"}}, ...]}}

记忆列表：
{items}"""


def _read_key():
    p = os.path.join(REPO, 'config.json')
    for name in ('config.json', 'config_backup_20261007.json'):
        q = os.path.join(REPO, name)
        if not os.path.exists(q):
            continue
        try:
            cfg = json.loads(io.open(q, encoding='utf-8').read())
        except (OSError, ValueError):
            continue
        k = (cfg.get('deepseek_api_key') or '').strip()
        if k:
            return k
    return ''


def call(key, prompt, max_tokens=1500, temperature=0.0):
    payload = {
        'model': MODEL,
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': temperature,
        'max_tokens': max_tokens,
        'thinking': {'type': 'disabled'},
        'response_format': {'type': 'json_object'},
    }
    body = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(ENDPOINT, data=body, headers={
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + key,
    })
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            d = json.loads(r.read().decode('utf-8'))
        ch = d['choices'][0]
        txt = (ch['message'].get('content') or '').strip()
        usage = d.get('usage') or {}
        if not txt:
            return '', usage, ch.get('finish_reason')
        return txt, usage, ch.get('finish_reason')
    except urllib.error.HTTPError as e:
        return '', {}, 'HTTP %d: %s' % (e.code, e.read().decode('utf-8', 'replace')[:120])
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        return '', {}, '%s: %s' % (type(e).__name__, str(e)[:100])


def parse_items(txt, n):
    """把模型返回解析成 {i: (entity, aspect)}，缺的留空。"""
    out = {}
    try:
        d = json.loads(txt)
    except ValueError:
        m = re.search(r'\{.*\}', txt, re.S)
        if not m:
            return out
        try:
            d = json.loads(m.group(0))
        except ValueError:
            return out
    items = d.get('items') if isinstance(d, dict) else None
    if not isinstance(items, list):
        return out
    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            i = int(it.get('i'))
        except (TypeError, ValueError):
            continue
        if 0 <= i < n:
            out[i] = (str(it.get('entity') or '').strip(),
                      str(it.get('aspect') or '').strip().lower())
    return out


def norm_entity(s):
    """轻归一：去空白/标点、小写拉丁，不做语义改写（否则等于自己帮它对齐）"""
    s = (s or '').strip().lower()
    s = re.sub(r'[\s，。、；：！？,.;:!?（）()「」"\'`]', '', s)
    return s


ASPECTS = {'preference', 'habit', 'change', 'struggle', 'advice', 'episode'}


def load_sample():
    """取 60 个 batch × 3 条 + 全部硬样例 batch，构成评测集"""
    d = json.loads(io.open(DATA, encoding='utf-8').read())
    fs = d['facts']
    for i, f in enumerate(fs):
        f['_i'] = i
    by_b = {}
    for f in fs:
        by_b.setdefault(int(f.get('batch', -1)), []).append(f)
    hard = [86, 87, 79, 60, 85, 92, 81, 97, 47, 48]
    picked = []
    used_b = []
    for b in sorted(by_b):
        v = by_b[b]
        if len(v) >= 3 and len(used_b) < 60:
            picked.extend(v[:3])
            used_b.append(b)
    extra = [f for b in hard if b in by_b for f in by_b[b]]
    ids = {f['_i'] for f in picked}
    for f in extra:
        if f['_i'] not in ids:
            picked.append(f)
            ids.add(f['_i'])
    return picked


def run_pass(key, facts, order_seed=None, temp=0.0, tag='pass'):
    """跑一遍标注。order_seed 不为 None 时打乱顺序（测顺序无关性）。"""
    idx = list(range(len(facts)))
    if order_seed is not None:
        import random
        rnd = random.Random(order_seed)
        rnd.shuffle(idx)
    res = {}
    n_calls = 0
    tok_in = tok_out = 0
    t0 = time.time()
    for s in range(0, len(idx), BATCH):
        chunk = idx[s:s + BATCH]
        lines = []
        for j, gi in enumerate(chunk):
            lines.append('%d. %s' % (j, (facts[gi].get('content') or '').strip()))
        prompt = PROMPT.format(items='\n'.join(lines))
        txt, usage, fin = call(key, prompt, temperature=temp)
        n_calls += 1
        tok_in += int(usage.get('prompt_tokens') or 0)
        tok_out += int(usage.get('completion_tokens') or 0)
        got = parse_items(txt, len(chunk))
        if not got:
            print('    [%s] 第 %d 批解析失败 fin=%s' % (tag, s // BATCH, fin))
        for j, gi in enumerate(chunk):
            e, a = got.get(j, ('', ''))
            res[gi] = {'entity': e, 'aspect': a}
        if (s // BATCH) % 5 == 0:
            print('    [%s] %d/%d 批' % (tag, s // BATCH + 1, (len(idx) + BATCH - 1) // BATCH))
    dt = time.time() - t0
    return res, {'calls': n_calls, 'tok_in': tok_in, 'tok_out': tok_out, 'sec': round(dt, 1)}


def main():
    key = _read_key()
    if not key:
        print('✗ 无 API key')
        return 1
    facts = load_sample()
    print('评测集 %d 条（来自 %d 个 batch，另含 %d 组硬样例）'
          % (len(facts), len({f.get('batch') for f in facts}),
             len({f.get('batch') for f in facts if int(f.get('batch')) in
                  (86, 87, 79, 60, 85, 92, 81, 97, 47, 48)})))

    # 断点续跑
    prev = {}
    if os.path.exists(OUT):
        try:
            prev = json.loads(io.open(OUT, encoding='utf-8').read())
            print('已有结果：%s' % ', '.join(sorted(prev.get('passes', {}))))
        except ValueError:
            prev = {}
    passes = prev.get('passes', {})

    if 'p1' not in passes:
        print('\n[E2 第 1 遍] temperature=0，原始顺序')
        r, u = run_pass(key, facts, None, 0.0, 'p1')
        passes['p1'] = {'res': {str(k): v for k, v in r.items()}, 'usage': u}
        _save(prev, passes, facts)
    if 'p2' not in passes:
        print('\n[E2 第 2 遍] temperature=0，同样顺序（测自一致性）')
        r, u = run_pass(key, facts, None, 0.0, 'p2')
        passes['p2'] = {'res': {str(k): v for k, v in r.items()}, 'usage': u}
        _save(prev, passes, facts)
    if 'p3' not in passes:
        print('\n[E3 第 3 遍] 打乱顺序 + temperature=0.3（测顺序/温度敏感性）')
        r, u = run_pass(key, facts, 20261104, 0.3, 'p3')
        passes['p3'] = {'res': {str(k): v for k, v in r.items()}, 'usage': u}
        _save(prev, passes, facts)

    analyse(facts, passes)
    return 0


def _save(prev, passes, facts):
    os.makedirs(RESULTS, exist_ok=True)
    prev['passes'] = passes
    prev['generated'] = time.strftime('%Y-%m-%d %H:%M')
    prev['n_facts'] = len(facts)
    with io.open(OUT, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(json.dumps(prev, ensure_ascii=False, indent=1) + '\n')
    print('    已存 %s' % OUT)


def analyse(facts, passes):
    import collections

    def rec(p):
        return {int(k): v for k, v in passes[p]['res'].items()}

    r1, r2, r3 = rec('p1'), rec('p2'), rec('p3')
    n = len(facts)

    def line(c='=', k=96):
        print(c * k)

    line()
    print('E1 覆盖率')
    line()
    for tag, r in (('p1', r1), ('p2', r2), ('p3', r3)):
        e_ok = sum(1 for v in r.values() if v['entity'])
        a_ok = sum(1 for v in r.values() if v['aspect'] in ASPECTS)
        a_bad = sum(1 for v in r.values() if v['aspect'] and v['aspect'] not in ASPECTS)
        print('  %s：entity 有值 %d/%d（%.1f%%）；aspect 合法 %d；aspect 越界 %d'
              % (tag, e_ok, n, 100.0 * e_ok / n, a_ok, a_bad))

    line()
    print('E2 稳定性：同一输入跑两次（temp=0，同顺序）')
    line()
    both = [i for i in range(n) if r1.get(i, {}).get('entity') and r2.get(i, {}).get('entity')]
    exact = sum(1 for i in both if r1[i]['entity'] == r2[i]['entity'])
    norm = sum(1 for i in both if norm_entity(r1[i]['entity']) == norm_entity(r2[i]['entity']))
    print('  可比对 %d 条：原文一致 %d（%.1f%%）；归一后一致 %d（%.1f%%）'
          % (len(both), exact, 100.0 * exact / max(len(both), 1),
             norm, 100.0 * norm / max(len(both), 1)))
    diff = [i for i in both if norm_entity(r1[i]['entity']) != norm_entity(r2[i]['entity'])]
    if diff:
        print('  不一致样例（前 6）：')
        for i in diff[:6]:
            print('    「%s」' % (facts[i]['content'] or '')[:40])
            print('       p1=%r  p2=%r' % (r1[i]['entity'], r2[i]['entity']))

    line()
    print('E3 顺序/温度敏感性（p3 打乱 + temp=0.3）')
    line()
    both3 = [i for i in range(n)
             if r1.get(i, {}).get('entity') and r3.get(i, {}).get('entity')]
    same3 = sum(1 for i in both3 if norm_entity(r1[i]['entity']) == norm_entity(r3[i]['entity']))
    print('  与 p1 相比一致 %d / %d = %.1f%%'
          % (same3, len(both3), 100.0 * same3 / max(len(both3), 1)))
    asp3 = sum(1 for i in both3 if r1[i]['aspect'] == r3[i]['aspect'])
    print('  aspect 一致 %d / %d = %.1f%%'
          % (asp3, len(both3), 100.0 * asp3 / max(len(both3), 1)))

    line()
    print('E4 判别力：同句式不同对象，entity 是否分得开（关键）')
    line()
    # 用之前的机械判据：两边都有拉丁专名且无交集 ⇒ 不同对象
    LATIN = re.compile(r'[A-Za-z][A-Za-z0-9\.\+\-]{1,}')
    GENERIC = {'user', 'ai', 'llm', 'api', 'pdf', 'excel', 'ppt', 'word'}

    def latins(t):
        return {w.lower() for w in LATIN.findall(t or '')
                if w.lower() not in GENERIC and len(w) >= 2}

    pairs = []
    for a in range(n):
        la = latins(facts[a].get('content'))
        if not la:
            continue
        for b in range(a + 1, n):
            lb = latins(facts[b].get('content'))
            if not lb or (la & lb):
                continue
            if norm_entity(r1[a]['entity']) == norm_entity(r1[b]['entity']):
                pairs.append((a, b, r1[a]['entity']))
    print('  entity 被写成同一标签、但拉丁专名互不相交的对：%d 组' % len(pairs))
    for a, b, e in pairs[:8]:
        print('    entity=%r' % e)
        print('       %s' % (facts[a]['content'] or '')[:52])
        print('       %s' % (facts[b]['content'] or '')[:52])
    verdict4 = ('✗ 仍有 %d 组不同对象被归为同一 entity' % len(pairs)) if pairs else \
        '✓ 不同对象没有出现同 entity'
    print('  ⇒ %s' % verdict4)

    line()
    print('E5 结构质量：entity → batch（真值）的纯度/召回')
    line()
    # 准度：同一 batch 内 3 条是否落到同一 entity
    by_b = collections.defaultdict(list)
    for i, f in enumerate(facts):
        by_b[int(f.get('batch'))].append(i)
    pure_hits = []
    for b, idxs in by_b.items():
        if len(idxs) < 2:
            continue
        es = [norm_entity(r1[i]['entity']) for i in idxs if r1.get(i, {}).get('entity')]
        if len(es) < 2:
            continue
        c = collections.Counter(es)
        pure_hits.append(max(c.values()) / float(len(es)))
    print('  同 batch 内 entity 一致的批次占比：中位 %.2f（%d 个 batch）'
          % (sorted(pure_hits)[len(pure_hits) // 2] if pure_hits else 0, len(pure_hits)))

    # entity → batch 的纯度（每个 entity 里最多的 batch 占多少）
    e2b = collections.defaultdict(collections.Counter)
    b2e = collections.defaultdict(collections.Counter)
    for i, f in enumerate(facts):
        e = norm_entity(r1.get(i, {}).get('entity'))
        if not e:
            continue
        e2b[e][int(f['batch'])] += 1
        b2e[int(f['batch'])][e] += 1
    tot = sum(sum(c.values()) for c in e2b.values())
    purity = sum(max(c.values()) for c in e2b.values()) / float(tot) if tot else 0
    ent_rec = (sum(1 for c in b2e.values()
                   if max(c.values()) >= 0.5 * sum(c.values())) / float(len(b2e))) if b2e else 0
    print('  entity 纯度 %.3f / 实体召回 %.3f / entity 数 %d（对比余弦聚类 0.758 / 0.502 / 576）'
          % (purity, ent_rec, len(e2b)))
    print('  ⇒ 纯度 %s 余弦聚类；召回 %s'
          % ('高于' if purity > 0.758 else '不高于',
             '高于' if ent_rec > 0.502 else '不高于'))

    line()
    print('E6 成本与延迟')
    line()
    for tag in ('p1', 'p2', 'p3'):
        u = passes[tag]['usage']
        print('  %s：%d 次调用，输入 %d tok / 输出 %d tok，%.1f s'
              % (tag, u['calls'], u['tok_in'], u['tok_out'], u['sec']))
    tot_calls = sum(passes[t]['usage']['calls'] for t in passes)
    tot_s = sum(passes[t]['usage']['sec'] for t in passes)
    per = tot_s / max(tot_calls, 1)
    print('  平均 %.2f s/次（%d 条/次）⇒ 1411 条全量标注约需 %.0f 次调用、%.0f 分钟'
          % (per, BATCH, 1411 / float(BATCH), 1411 / float(BATCH) * per / 60))

    # aspect 分布
    line()
    print('aspect 分布（看枚举是否够用）')
    line()
    ac = collections.Counter(r1[i]['aspect'] for i in r1 if r1[i]['aspect'])
    for k, v in ac.most_common():
        print('  %-12s %4d（%.1f%%）' % (k, v, 100.0 * v / max(sum(ac.values()), 1)))
    bad = [k for k in ac if k not in ASPECTS]
    if bad:
        print('  ⚠ 越界取值：%r' % bad)

    prev = json.loads(io.open(OUT, encoding='utf-8').read()) if os.path.exists(OUT) else {}
    prev['analysis'] = {
        'E1_coverage': {t: round(100.0 * sum(1 for v in rec(t).values() if v['entity']) / n, 1)
                        for t in ('p1', 'p2', 'p3')},
        'E2_exact_pct': round(100.0 * exact / max(len(both), 1), 1),
        'E2_norm_pct': round(100.0 * norm / max(len(both), 1), 1),
        'E3_norm_pct': round(100.0 * same3 / max(len(both3), 1), 1),
        'E4_conflict_pairs': len(pairs),
        'E5_purity': round(purity, 3), 'E5_entity_recall': round(ent_rec, 3),
        'E5_n_entities': len(e2b),
        'E6_sec_per_call': round(per, 2),
        'aspect_dist': dict(ac),
    }
    with io.open(OUT, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(json.dumps(prev, ensure_ascii=False, indent=1) + '\n')
    print()
    print('  分析已并入 %s' % OUT)


if __name__ == '__main__':
    raise SystemExit(main())
