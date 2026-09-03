# -*- coding: utf-8 -*-
"""
memory_engine.py — 记忆引擎（Phase 1 重构）
============================================
四层记忆的「检索 + 抽取」核心（纯逻辑，可独立单测）：
- tokenize：中文 2-gram + 英文/数字词 混合分词（零依赖）
- BM25Index：BM25 关键词检索（词频×逆文档频率×长度归一化）
- search_memory：检索管线入口——BM25 粗筛 → LLM 重排 top-k（可跳过重排）
- extract_memories：对话自动抽取（LLM 提炼事实/事件，faithful 原则）
- score_recency：时间衰减加权（新记忆优先）

设计要点：
- 存储仍是 JSON（memory.json / memories.json），本模块只做「索引 + 检索 + 抽取」
- 注入预算分层（core 常驻 + 检索 top-k + 情景最近）由调用方（主文件）组合
"""
import datetime
import json
import math
import re
import unicodedata

# ---------- 分词 ----------

_WORD_RE = re.compile(r'[a-zA-Z]+|[0-9]+')


def tokenize(text):
    """混合分词：中文连续串按 2-gram 切，英文/数字保留整词。
    例：「我下午上课」→ ['我下','下午','午上','上课']；「python3.14」→ ['python', '3', '14']"""
    text = str(text or '').lower()
    # 中文段（连续 CJK 字符）
    tokens = []
    cjk_run = []
    for ch in text:
        if '\u4e00' <= ch <= '\u9fff':
            cjk_run.append(ch)
        else:
            if len(cjk_run) >= 2:
                tokens.extend(''.join(cjk_run)[i:i + 2] for i in range(len(cjk_run) - 1))
            elif cjk_run:
                tokens.append(cjk_run[0])
            cjk_run = []
    if len(cjk_run) >= 2:
        tokens.extend(''.join(cjk_run)[i:i + 2] for i in range(len(cjk_run) - 1))
    elif cjk_run:
        tokens.append(cjk_run[0])
    tokens.extend(_WORD_RE.findall(text))
    return tokens


# ---------- BM25 ----------

class BM25Index:
    """BM25 检索索引：docs = [{id, text}]。k1=1.2, b=0.75 经典参数。"""

    def __init__(self, docs):
        self.docs = list(docs)
        self.doc_tokens = [tokenize(d.get('text', '')) for d in self.docs]
        self.doc_len = [len(t) for t in self.doc_tokens]
        self.avg_len = sum(self.doc_len) / max(len(self.docs), 1)
        # 词 → 出现过的文档数
        self.doc_freq = {}
        for tokens in self.doc_tokens:
            for w in set(tokens):
                self.doc_freq[w] = self.doc_freq.get(w, 0) + 1
        self.n_docs = len(self.docs)
        self.k1, self.b = 1.2, 0.75

    def _idf(self, w):
        n = self.doc_freq.get(w, 0)
        if n == 0:
            return 0.0
        return math.log(1 + (self.n_docs - n + 0.5) / (n + 0.5))

    def search(self, query, top_k=8):
        """返回 [(index, score)] 按相关度降序"""
        q_tokens = tokenize(query)
        if not q_tokens:
            return []
        scores = []
        for i, tokens in enumerate(self.doc_tokens):
            tf = {}
            for w in q_tokens:
                tf[w] = tokens.count(w)
            score = 0.0
            for w in q_tokens:
                if tf.get(w, 0) == 0:
                    continue
                dl = self.doc_len[i]
                score += (self._idf(w) * tf[w] * (self.k1 + 1) /
                          (tf[w] + self.k1 * (1 - self.b + self.b * dl / max(self.avg_len, 1))))
            if score > 0:
                scores.append((i, score))
        scores.sort(key=lambda x: -x[1])
        return scores[:top_k]


# ---------- 检索管线 ----------

def search_memory(facts, query, top_k=3, rerank=None):
    """检索管线：BM25 粗筛 top-8 → LLM 重排 top-k（rerank 为可调用函数或 None）。
    facts: [{id, content, importance, roles, status, updated_at, ...}]
    rerank 签名：rerank(query, candidates: [{id, text}]) -> 选中的 id 列表（有序）
    返回选中的事实列表（含分数信息）。"""
    active = [f for f in facts if f.get('status', 'active') == 'active']
    if not active:
        return []
    docs = [{'id': f.get('id', str(i)), 'text': f.get('content', '')} for i, f in enumerate(active)]
    idx = BM25Index(docs)
    hits = idx.search(query, top_k=8)
    if not hits:
        return []
    cands = [{'id': active[i].get('id', str(i)), 'text': active[i].get('content', ''),
              'importance': active[i].get('importance', 3),
              'updated_at': active[i].get('updated_at', '')} for i, _ in hits]
    if rerank is None:
        # 无重排：按 (BM25分, 重要度, 新旧) 综合取 top_k
        picked = cands[:top_k]
        picked.sort(key=lambda c: -float(c.get('importance', 3)))
        return picked
    try:
        picked_ids = rerank(query, cands)
        by_id = {c['id']: c for c in cands}
        picked = [by_id[i] for i in picked_ids if i in by_id][:top_k]
        if picked:
            return picked
    except Exception:
        pass
    return cands[:top_k]


# ---------- 自动抽取 ----------

EXTRACT_PROMPT = """你是记忆抽取器。从下面的对话中，提炼值得长期记住的信息，输出 JSON。
规则（faithful 原则）：
1. 只提炼「用户明确表达或可可靠推断」的信息，不脑补；
2. 事实类（用户偏好/身份/日程/重要事件/任务）→ facts；
3. 事件类（一次性的共同经历，如「今天一起玩了扫雷」）→ events；
4. 与已有记忆重复或冲突的 → 在 update_facts 里给 id 和新内容；
5. 输出格式（严格 JSON）：
{{"facts": [{{"content": "...", "importance": 1-5}}],
  "events": [{{"title": "简短标题", "detail": "描述"}}],
  "update_facts": [{{"id": "已有id", "content": "更新后内容"}}]}}

已有记忆：
{existing}

对话：
{dialogue}
"""


def extract_memories(chat_fn, dialogue, existing='', max_tokens=400):
    """调用 LLM 抽取记忆。chat_fn 签名：chat_fn(messages, max_tokens) -> 回复文本。
    返回 dict: {'facts': [...], 'events': [...], 'update_facts': [...]}，失败返回空结构。"""
    try:
        prompt = EXTRACT_PROMPT.format(existing=existing or '（无）', dialogue=dialogue or '（无）')
        reply = chat_fn([{'role': 'user', 'content': prompt}], max_tokens)
        m = re.search(r'\{.*\}', reply or '', re.S)  # 贪婪匹配完整 JSON（允许嵌套花括号）
        if not m:
            return {'facts': [], 'events': [], 'update_facts': []}
        data = json.loads(m.group(0))
        return {
            'facts': data.get('facts') or [],
            'events': data.get('events') or [],
            'update_facts': data.get('update_facts') or [],
        }
    except Exception:
        return {'facts': [], 'events': [], 'update_facts': []}


# ---------- 时效加权 ----------

def score_recency(updated_at, now=None, half_life_days=30.0):
    """时间衰减：距今越近分越高（指数衰减，半衰期默认 30 天）。返回 0~1。"""
    if not updated_at:
        return 0.5
    try:
        t = datetime.datetime.fromisoformat(str(updated_at))
    except Exception:
        return 0.5
    now = now or datetime.datetime.now()
    days = (now - t).total_seconds() / 86400.0
    return 0.5 ** (max(days, 0) / half_life_days)


def build_core_block(facts, current, budget=400):
    """core 记忆块：角色匹配 + 高重要度常驻（≤budget 字符）"""
    lines = []
    used = 0
    fs = [f for f in facts
          if f.get('status', 'active') == 'active'
          and (f.get('roles', 'both') == 'both' or f.get('roles') == current)]
    fs.sort(key=lambda x: (-float(x.get('importance', 3)), str(x.get('updated_at', ''))))
    for f in fs:
        text = f.get('content', '').strip()
        if not text:
            continue
        if used + len(text) > budget:
            break
        lines.append(f'★{f.get("importance", 3)} {text}')
        used += len(text)
    return '\n'.join(lines)
