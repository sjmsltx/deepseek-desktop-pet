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
import hashlib
import json
import logging
import math
import re
import unicodedata

#: 本模块是纯逻辑，但向量组件是可选件 —— 它挂掉时必须留痕，不许静默降级
_log = logging.getLogger('pet.memory_engine')

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

    def search_detailed(self, query, top_k=8):
        """v6.53：带命中统计的检索 —— 供“相关性闸门”使用。
        返回 [{'index','score','matched','coverage'}]；matched=命中的查询词数，
        coverage=命中词占查询词的比例（0~1）。"""
        qt = set(tokenize(query))
        out = []
        for i, s in self.search(query, top_k=top_k):
            matched = len(qt & set(self.doc_tokens[i]))
            out.append({'index': i, 'score': s, 'matched': matched,
                        'coverage': matched / max(len(qt), 1)})
        return out


# ---------- 检索管线 ----------

# v6.53：注入用相关性闸门（治"记忆过拟合"——原先无阈值，凑不出相关的也硬塞 top-3）
# 判据用"命中覆盖率"而不是 BM25 绝对分（绝对分受语料库大小/文档长短影响，无法跨库调）
GATE_MIN_MATCHED = 2      # 至少命中 2 个查询词（2-gram）
#: 命中词占查询词比例的下限。
#:
#: ⚠ 2026-11-02 由 0.34 降到 0.28（Owner「闸门整一下」）。**改善很小，别高估它。**
#:
#: 完整实验（四个脚本在 收件箱/05-闸门实验/，结论如下）：
#:
#:   ① 旧值是按**陈述句**调的，用在自然问句上偏严：中文 2-gram 把「什么/东西/我在/
#:      平时」这类虚词算进分母，coverage 被稀释到 0.11~0.25 ⇒ 偏好类问题问不出来
#:      （「我爱吃什么东西」→ 0 条，而库里明明有「用户爱吃重庆合川桃片」）。
#:
#:   ② 6 条开发集 + 12 条**留出集**分离测（留出集调参时不参与）：
#:      只在开发集选参会选出 devR3 100%、holdR3 42% 的参数 —— 过拟合 58 个点。
#:
#:   ③ 42 条负样本逐条判「纯噪声 vs 相关」：
#:        0.34/0.28 都是「2 条相关注入、0 条纯噪声」（那 2 条是「问 Python 问题 →
#:        注入『用户在学习/练习 Python』」，属真相关）；
#:        0.11 会有 3 条纯噪声（「重庆高铁」← 爱吃桃片、「提醒睡觉」← 提醒注意身体）。
#:
#:   ④ 真实对话 45 条 user 消息：0.11~0.20 注入率**全部 31.1%**，0.34 是 26.7%
#:      ⇒ 放宽在真实分布上几乎不增加注入。
#:
#:   ⑤ ⛔ **最紧的一条约束不是上面任何一项**：`test_memory_gate.py` 的语义契约
#:      「用户问概念时不抬记忆」（docstring 例：「扫雷是什么」不该注入「你爱玩扫雷」，
#:      对应注入点那句「记忆只作背景、不做话题」）。
#:      实测「扫雷是什么」coverage 恰为 0.25 ⇒ **阈值必须 > 0.25 才挡得住**，
#:      所以 0.15/0.20/0.25 全部作废（我第一次就栽在这里，以为可以降到 0.15）。
#:
#:   满足全部约束的只有 0.26~0.32（平台）。
#:
#:   ⚠ 2026-11-03 由 0.28 改 **0.30** —— 原来写「两侧各留余量」是错的，
#:     因为**两种越界的后果不对等**：
#:       · 跌破下界（<0.26）→ 概念提问漏注 → 用户问「扫雷是什么」，
#:         桌宠答「你不是爱玩扫雷吗」→ **明显违反「只作背景不做话题」，用户能感觉到**
#:       · 超过上界（>0.32）→ 召回下降 → 少召回一条 → **用户感觉不到**
#:     ⇒ 该远离下界。余量实测：0.28 是下 0.03/上 0.06；0.30 是下 0.05/上 0.04。
#:     两档在全指标上**完全相同**（dev R@3 2/6、hold R@3 3/12、负样本注入 2/42、
#:     真实对话注入 14/45、扫雷注入 0）⇒ 取余量分配更合理的那档，零代价。
#:
#:   ⛔ 复跑核对：python tools\eval\gate_study\run_study.py
#:      （数据在 tools/eval/negatives.json 与 realdist.json，都在仓库里）
#:
#: 📊 净收益：留出集 R@3 17% → 25%（+8 点），开发集持平 33%，零纯噪声、零概念漏注。
#:
#: ⛔ **真正的瓶颈不是这个数**：把闸门全关（matched=0、cov=0），留出集也只有 42%。
#:    字面匹配打不过同义改写（「我大几」vs「用户是大二学生」无共同 2-gram）。
#:    要往上走必须加同义词表或语义检索，**别再指望调 GATE_***。
GATE_MIN_COVERAGE = 0.30
GATE_KEEP_RATIO = 0.25    # 相对地板：BM25 分低于最佳命中 25% 的丢弃
#: ⚠ keep_ratio 专项扫过 0.0~0.8，在当前数据上结果**完全一样**（top_k=3 时候选本来就少）。
#:   它是「相对地板」，候选多时才生效，所以保留不动 —— 但别以为它在起作用。


def search_memory(facts, query, top_k=3, rerank=None, min_matched=0, min_coverage=0.0,
                  keep_ratio=0.0):
    """检索管线：BM25 粗筛 top-8 → （可选）相关性闸门 → LLM 重排 top-k。

    默认不过闸（min_matched=0/min_coverage=0/keep_ratio=0）—— 保持原有行为兼容；
    注入场景请用 `search_memory_for_injection`（带闸门）。
    返回选中的事实列表（含 score / matched / coverage）。"""
    active = [f for f in facts if f.get('status', 'active') == 'active']
    if not active:
        return []
    docs = [{'id': f.get('id', str(i)), 'text': f.get('content', '')} for i, f in enumerate(active)]
    idx = BM25Index(docs)
    det = idx.search_detailed(query, top_k=8)
    if not det:
        return []
    best = det[0]['score']
    if min_matched or min_coverage:
        det = [d for d in det
               if (d['matched'] >= min_matched or d['coverage'] >= min_coverage)
               and d['score'] >= keep_ratio * best]
        if not det:
            return []          # 闸门：没有“够相关”的记忆 → 本轮不注入
    cands = [{'id': active[d['index']].get('id', str(d['index'])),
              'text': active[d['index']].get('content', ''),
              'importance': active[d['index']].get('importance', 3),
              'updated_at': active[d['index']].get('updated_at', ''),
              'score': round(d['score'], 4), 'matched': d['matched'],
              'coverage': round(d['coverage'], 3)} for d in det]
    if rerank is None:
        # 无重排：按 (BM25分, 重要度, 新旧) 综合取 top_k
        # v6.51：注释里承诺的"新旧"此前根本没实现（score_recency 写了却零调用），现在接上
        picked = cands[:top_k]
        picked.sort(key=lambda c: (-float(c.get('importance', 3)),
                                   -score_recency(c.get('updated_at'))))
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


# ---------------- 向量检索（可选组件，缺失即回退）----------------
#
# 2026-11-06 接入。为什么加它：BM25 的天花板是字面匹配 ——
#   闸门全关时留出集也只有 42%（「我大几」vs「用户是大二学生」没有共同 2-gram）。
# 实测（同一套数据，库 21 条）：BM25 留出 3/12；向量 + 自适应阈值 8/12。
#
# 为什么阈值不能写死：库变大后任何一句都能找到"有点像"的邻居，
#   固定 0.51 的负样本误注入从 7/42 涨到 34/42。改用按本库分布定标的 z 门槛后，
#   同一区间内压回 4/42 → 2/42（细节见 memory_embed.adaptive_z_threshold）。

#: 向量矩阵缓存：facts 内容一变就重建（键是内容指纹，不是文件修改时间）
_VEC_CACHE = {'fp': '', 'mat': None, 'texts': [], 'ids': []}


def _vector_fingerprint(active):
    """按 (id, content) 算指纹。内容被改写但 id 不变时也要重算，所以不能只看 id。"""
    h = hashlib.sha1()
    for f in active:
        h.update(('%s\x00%s\x01' % (f.get('id'), f.get('content'))).encode('utf-8'))
    return h.hexdigest()


def vector_matrix(embedder, active):
    """取（或重建）与 active 逐行对齐的向量矩阵。不可用返回 (None, None)。"""
    if embedder is None or not getattr(embedder, 'ok', False):
        return None, None
    fp = _vector_fingerprint(active)
    if _VEC_CACHE['fp'] == fp and _VEC_CACHE['mat'] is not None:
        return _VEC_CACHE['mat'], _VEC_CACHE['texts']
    texts = [(f.get('content') or '').strip() for f in active]
    mat = embedder.encode(texts)
    if mat is None or len(mat) != len(texts):
        return None, None
    _VEC_CACHE.update({'fp': fp, 'mat': mat, 'texts': texts,
                       'ids': [f.get('id') for f in active]})
    return mat, texts


def search_memory_vector(facts, query, top_k=3, rerank=None, embedder=None):
    """向量检索（自适应阈值）。**组件不可用返回 None** ⇒ 调用方回退 BM25。

    返回形状与 search_memory 一致（id/text/importance/updated_at/score），
    另带 'z'（该条在本库分布里的 z 分数）与 'via'='vector'，便于 UI / 台账显示。
    """
    active = [f for f in facts if f.get('status', 'active') == 'active']
    if not active:
        return []
    try:
        import memory_embed as _me
    except Exception as exc:
        # 组件缺失（没装依赖/文件被删）→ 回退 BM25。必须留痕，否则"怎么突然不准了"无从查
        _log.info('向量组件不可用，本次回退 BM25：%s', exc)
        return None
    emb = embedder or _me.get_embedder()
    if emb is None or not getattr(emb, 'ok', False):
        return None
    if _me.is_definition_question(query):
        return []                        # 契约：问概念时不抬记忆（两条路同口径）
    mat, texts = vector_matrix(emb, active)
    if mat is None:
        return None
    hits = emb.search_adaptive(query, mat, texts, k=max(top_k, 3))
    if not hits:
        return []
    cands = []
    for h in hits:
        f = active[h['index']]
        cands.append({'id': f.get('id'), 'text': (f.get('content') or ''),
                      'importance': f.get('importance', 3),
                      'updated_at': f.get('updated_at', ''),
                      'score': h['score'], 'z': h['z'], 'via': 'vector'})
    if rerank is not None:
        try:
            picked_ids = rerank(query, cands)
            by = {c['id']: c for c in cands}
            picked = [by[i] for i in picked_ids if i in by][:top_k]
            if picked:
                return picked
        except Exception as exc:
            # 重排失败就用原序 —— 但不许静默（否则"重排到底有没有生效"永远查不出来）
            _log.warning('向量重排失败，按原序返回：%s', exc)
    return cands[:top_k]


def search_memory_for_injection(facts, query, top_k=3, rerank=None, vector=None):
    """v6.53：**注入专用**检索 —— 带相关性闸门，没命中就返回空表（调用方本轮不注入）。
    治理目标：不让"勉强相关"的记忆每轮都跑进上下文（记忆过拟合/过依赖）。

    vector（2026-11-06）：
        None / 'auto'（默认）  两条路取并集：字面精确（BM25+闸门）∪ 语义（自适应阈值）。
                          为什么默认并集：单用向量会丢掉字面精确命中 ——
                          实测 r06「我的桌宠模型姐姐叫什么」BM25 命中了「Pro 模型姐姐的
                          名字叫大蓝」，而单向量**不注入**（它认为「我的名字叫小蓝」更像）。
                          并集：开发 6/6、留出 10/12（单向量与纯 BM25 的旧数字未复测，
                          留作对照；2026-11-07 更正：这里原写 9/12，与 BASELINE 常量 10/12 矛盾）。
                          代价：负样本误注入 21 条 5/42、321 条 10/42（单向量 4 / 3）。
        'vector'     只用向量（精度优先；321 条时负样本 3/42，但会丢字面精确命中）
        'off'        强制 BM25（出问题时可一键回到旧行为）
        'union'      与默认同义（显式写法）
    """
    def _bm25():
        return search_memory(facts, query, top_k=top_k, rerank=rerank,
                             min_matched=GATE_MIN_MATCHED,
                             min_coverage=GATE_MIN_COVERAGE,
                             keep_ratio=GATE_KEEP_RATIO)

    mode = 'union' if vector in (None, 'auto', 'union') else str(vector)
    if mode == 'off':
        return _bm25()
    try:
        got = search_memory_vector(facts, query, top_k=top_k, rerank=rerank)
    except Exception as exc:
        # 任何意外都回退，绝不因向量挂掉而不答话 —— 但要留痕
        _log.warning('向量检索异常，本轮回退 BM25：%s', exc)
        got = None
    if got is None:
        return _bm25()
    if mode == 'vector':
        return got
    seen = {str(c.get('id')) for c in (got or [])}
    extra = [c for c in _bm25() if str(c.get('id')) not in seen]
    return (list(got or []) + extra)[:top_k]


# ---------- 自动抽取 ----------

EXTRACT_PROMPT = """你是记忆抽取器。从下面的对话中，提炼值得长期记住的信息，输出 JSON。
规则（faithful 原则）：
1. 只提炼「用户明确表达或可可靠推断」的信息，不脑补；
2. facts 只收**稳定属性**：身份/称呼、长期偏好、常住地、长期习惯、稳定兴趣与能力。
   每条必须做到「脱离这段对话也能独立读懂」——不出现没有先行词的「它/这个/那个」；
3. 下面这些**不要写进 facts**（写进 events，或不写）：
   · 一次性进展/里程碑：今天…、第 N 次…、满分/通关/完成了/拿到了；
   · 正在进行的具体任务：正在做…、这几天在做…、这周在学…（状态会过期）；
   · 我自己（助手）的建议、评价、方案：「适合…」「建议…」「优于…」；
   · 对产品/系统的评测：「实测效果好」「功能正常」；
   · **我们正在讨论的项目/代码本身**：不要因为这段对话在聊某个工具、某个功能、
     就把它记成「用户的兴趣/关注点」。判据：换一个人看这句话，能知道说的是用户
     这个人吗？说的如果是「我们在做什么」，就不写；
   · **一句寒暄或客套**：例如「注意身体健康哟」「早上好」。一句问候不构成稳定人格，
     不要据此写「用户说话语气友善」「用户关心他人」这类属性；
4. events 收「某一次发生的事」：一起做了什么、聊到什么、完成/达成什么、遇到的状况。
   title 写简短标题（≤28 字），detail 保留能回想起来的关键信息；
5. 与已有记忆重复或冲突的 → 在 update_facts 里给 id 和新内容，**不要另起一条**；
6. 用户的表述与旧记忆冲突时，以用户**最新**表述为准；
7. 输出格式（严格 JSON）：
{{"facts": [{{"content": "...", "importance": 1-5}}],
  "events": [{{"title": "简短标题", "detail": "描述",
               "emotion": "这段对话的主导情绪，1-2个词，如 开心/心疼/惊讶/温柔/平静"}}],
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


# 身份判据（2026-10-31 加）：只有这几类才算「人格卡」内容。
# 审核 WX 侧指出：原来 L0 没有任何身份判据，实质只是「重要度前 N 条」，
# 把普通偏好当永久设定，名不副实。这里给显式判据，而不是靠 importance 冒充。
_IDENTITY_PATTERNS = (
    '我的名字叫', '我叫', '名字叫', '用户叫', '称呼为',
    '角色叫', '模型姐姐叫', '的姐姐叫', '是我',
)
_IDENTITY_MAX = 6          # 身份条目上限（防判据过宽把整库吸进来）


def _is_identity(text):
    """这条事实是不是「身份/命名」类（该进人格卡、每次必注入）"""
    t = (text or '').strip()
    if not t or len(t) > 80:
        return False
    return any(p in t for p in _IDENTITY_PATTERNS)


def build_l0_block(facts, current, budget=320):
    """核心记忆块：身份类必进 + 其余高重要度按预算填充。

    返回 (block_text, used_objects)。
      · used_objects 是**对象列表**（不是 id 字段）—— memory.json 里存在
        3 组重复 id（同一次抽取同毫秒写入），按 id 剔除会连带删掉同名 id 的另一条。
      · 身份类不受 budget 限制（身份是极少数短条目，且必须每轮在）；
        其余按重要度降序、**超预算即 break**（原用 continue，会造成长的高重要度
        被跳过、短的低的入选 —— 实测倒挂）。
      · 预算按实际字符计（含「★n 」前缀与换行）。
    """
    fs = [f for f in facts
          if f.get('status') == 'active'
          and (f.get('roles', 'both') == 'both' or f.get('roles') == current)]
    fs.sort(key=lambda x: (-float(x.get('importance', 3)), -score_recency(x.get('updated_at'))))

    ident, rest = [], []
    for f in fs:
        text = (f.get('content') or '').strip()
        if not text:
            continue
        if _is_identity(text):
            if len(ident) < _IDENTITY_MAX:
                ident.append(f)
            continue
        rest.append(f)

    lines, used_objs, used_chars = [], [], 0
    for f in ident:                      # 身份：必进，不占普通预算
        line = '★%s %s' % (f.get('importance', 3), (f.get('content') or '').strip())
        lines.append(line)
        used_objs.append(f)
        used_chars += len(line) + 1
    for f in rest:                       # 其余：按预算，超了就停
        line = '★%s %s' % (f.get('importance', 3), (f.get('content') or '').strip())
        if used_chars + len(line) + 1 > budget:
            break
        lines.append(line)
        used_objs.append(f)
        used_chars += len(line) + 1
    return '\n'.join(lines), used_objs


def build_core_block(facts, current, budget=400):
    """【已弃用，请用 build_l0_block】核心记忆块的旧实现。

    保留它只为兼容 regression_test.py；**生产路径零调用**（评审-155 §4.1 复核）。
    它没有身份特判、按 importance+recency 纯排序，与 build_l0_block 语义不同 ——
    ⛔ 改「核心记忆」时请改 build_l0_block，改这里不会生效。
    """
    """core 记忆块：角色匹配 + 高重要度常驻（≤budget 字符）"""
    lines = []
    used = 0
    fs = [f for f in facts
          if f.get('status', 'active') == 'active'
          and (f.get('roles', 'both') == 'both' or f.get('roles') == current)]
    # v6.51：同重要度时优先"新"记忆——原先按 updated_at 字符串升序排列等于优先最旧的，方向反了
    fs.sort(key=lambda x: (-float(x.get('importance', 3)), -score_recency(x.get('updated_at'))))
    for f in fs:
        text = f.get('content', '').strip()
        if not text:
            continue
        if used + len(text) > budget:
            break
        lines.append(f'★{f.get("importance", 3)} {text}')
        used += len(text)
    return '\n'.join(lines)
