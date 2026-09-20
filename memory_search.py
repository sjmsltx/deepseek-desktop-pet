# -*- coding: utf-8 -*-
"""memory_search.py — 「搜共同经历」检索（v6.63）
================================================

背景
----
桌宠已经有两套记忆：`memory_facts`（事实：偏好/身份/日程…）与 `memories`（事件：一次性的共同经历）。
两者此前都只能**浏览**（回忆相册按时间线翻），想找「那次一起玩扫雷的事」得自己一层层翻。

本模块只做一件事：**给用户一个搜索入口** ——
- 事实类：复用既有检索管线 `memory_engine.search_memory`（BM25 + 重要度/新旧综合）；
  **刻意不过闸门**（闸门是为“注入”设计的，宁缺毋滥；用户主动搜就该尽量给结果）
- 事件类：对标题+描述做 2-gram 关键词匹配打分（中文友好、零依赖、即时）
- 两者**不混排**（BM25 分与我方关键词分不可比），而是分组返回，由展示层分组显示

设计约束
--------
- **纯本地、不花 API**：默认不调 LLM 重排（`rerank=None`）→ 即时返回、零成本；
  需要更聪明排序时可传 `rerank=`（沿用宿主的 `_rerank_memories`）。
- 不依赖 PySide6，纯函数，便于单测。
"""
import re

from memory_engine import search_memory

MAX_HITS = 20


def _tokens(query):
    """查询切词：中文按 2-gram（与 BM25 侧一致），英文/数字按词。返回去重小写列表。"""
    s = str(query or '').strip().lower()
    if not s:
        return []
    toks = set()
    for word in re.findall(r'[a-z0-9_]+', s):
        if len(word) >= 2:
            toks.add(word)
    cjk = re.sub(r'[^\u4e00-\u9fff]+', '', s)
    for i in range(len(cjk) - 1):
        toks.add(cjk[i:i + 2])
    if not toks and cjk:
        toks.add(cjk)
    return sorted(toks)


def score_event(event, toks):
    """事件关键词得分：命中词数 / 总词数，标题命中加权。返回 (score, matched)"""
    try:
        title = str(event.get('title') or '')
        detail = str(event.get('detail') or '')
        hay = (title + ' ' + detail).lower()
        matched = sum(1 for t in toks if t in hay)
        if not matched:
            return 0.0, 0
        title_hit = sum(1 for t in toks if t in title.lower())
        score = matched / max(1, len(toks)) + 0.25 * (title_hit / max(1, len(toks)))
        return round(min(score, 2.0), 4), matched
    except Exception:
        return 0.0, 0


def search_memories(memory_facts, events, query, top_k=8, rerank=None):
    """检索「记住的事」与「共同经历」。

    返回 {'facts': [...], 'events': [...], 'query': str}
    - facts 项：{'kind':'fact','id','text','importance','time','score','matched','coverage'}
    - events 项：{'kind':'event','type','title','detail','time','affection_at','score','matched'}
    """
    q = str(query or '').strip()
    out = {'facts': [], 'events': [], 'query': q}
    if not q:
        return out
    toks = _tokens(q)
    # ① 事实：复用既有检索管线（不过闸门）
    try:
        hits = search_memory(list(memory_facts or []), q, top_k=int(top_k), rerank=rerank)
        for h in hits:
            out['facts'].append({'kind': 'fact', 'id': h.get('id', ''),
                                 'text': h.get('text', ''), 'importance': h.get('importance', 3),
                                 'time': h.get('updated_at', ''), 'score': h.get('score', 0),
                                 'matched': h.get('matched', 0), 'coverage': h.get('coverage', 0)})
    except Exception:
        pass
    # ①b 子串兜底：单字查询（如「猫」）在 BM25 的 2-gram 索引下会漏，用户却期望搜到
    if len(out['facts']) < max(1, int(top_k) // 2):
        seen = {f.get('id') for f in out['facts']}
        needle = q.lower()
        for f in (memory_facts or []):
            try:
                if f.get('status', 'active') != 'active' or f.get('id') in seen:
                    continue
                if needle and needle in str(f.get('content') or '').lower():
                    out['facts'].append({'kind': 'fact', 'id': f.get('id', ''),
                                         'text': f.get('content', ''),
                                         'importance': f.get('importance', 3),
                                         'time': f.get('updated_at', ''), 'score': 0.0,
                                         'matched': 1, 'coverage': 1.0, 'via': 'substring'})
            except Exception:
                continue
    # ② 事件：关键词打分（只收真的有命中的）
    scored = []
    for ev in (events or []):
        sc, mt = score_event(ev, toks)
        if sc > 0:
            scored.append({'kind': 'event', 'type': ev.get('type', 'event'),
                           'title': ev.get('title', ''), 'detail': ev.get('detail', ''),
                           'time': ev.get('time', ''), 'affection_at': ev.get('affection_at'),
                           'score': sc, 'matched': mt})
    scored.sort(key=lambda e: (-e['score'], e.get('time', '')))
    out['events'] = scored[:int(top_k)]
    return out


def total_hits(result):
    return len((result or {}).get('facts') or []) + len((result or {}).get('events') or [])


def format_hits(result, is_en=False, limit=MAX_HITS):
    """结果 → 给用户看的文本（聊天列表 / 回忆相册都能用）"""
    res = result or {}
    q = res.get('query') or ''
    facts = (res.get('facts') or [])[:limit]
    events = (res.get('events') or [])[:limit]
    if not facts and not events:
        return ('🔍 没找到和「%s」有关的回忆（换个关键词试试）' % q) if not is_en else \
               ('🔍 Nothing found for "%s"' % q)
    lines = []
    if not is_en:
        lines.append('🔍 关于「%s」找到 %d 条回忆：' % (q, len(facts) + len(events)))
        if facts:
            lines.append('')
            lines.append('🧠 记住的事：')
            for f in facts:
                t = ('（%s）' % f['time']) if f.get('time') else ''
                lines.append('  ★%s %s%s' % (f.get('importance', 3), f.get('text', ''), t))
        if events:
            lines.append('')
            lines.append('✨ 共同经历：')
            for e in events:
                t = ('[%s]' % e['time']) if e.get('time') else ''
                aff = ('·当时好感 %s' % e['affection_at']) if e.get('affection_at') is not None else ''
                lines.append('  %s %s %s' % (t, e.get('title', ''), aff))
                if e.get('detail'):
                    lines.append('      %s' % e['detail'])
    else:
        lines.append('🔍 %d memories about "%s":' % (len(facts) + len(events), q))
        if facts:
            lines.append('🧠 Facts:')
            for f in facts:
                lines.append('  ★%s %s %s' % (f.get('importance', 3), f.get('text', ''), f.get('time', '')))
        if events:
            lines.append('✨ Shared experiences:')
            for e in events:
                lines.append('  [%s] %s' % (e.get('time', ''), e.get('title', '')))
    return '\n'.join(lines)
