# -*- coding: utf-8 -*-
"""
memory_events.py — 回忆日志（事件记忆层）

三层记忆架构中的「事件记忆」：
- 对话记忆（chat_memory*.json）：近期对话，滚动压缩 —— 现有
- 事实记忆（memory.json）：用户偏好/事实，memorize 工具 —— 现有
- 事件记忆（本模块）：共同经历时间线，长期，上限 MAX_MEMORIES 条滚动淘汰 —— 新增

回忆条目结构：
{id, time, role, type, title, detail, emotion, affection_at}
type: milestone(成就/里程碑) | event(事件) | user_mark(用户标记) | memory(事实记忆双写)
"""
import json
import logging
import os
import re
import threading
import time

_log = logging.getLogger('pet.memory_events')

MAX_MEMORIES = 200          # 滚动淘汰上限
INJECT_COUNT = 3            # prompt 注入最近 N 条
HALF_LIFE_DAYS = 30.0           # 权重衰减半衰期（天）
#: 每次被检索命中时权重上升的幅度（Owner：「被反复提及的记忆权重上升」）
WEIGHT_BUMP = 0.06
#: 权重上限
WEIGHT_MAX = 1.0
#: 新条目的初始权重（还没被用过，不该一上来满分）
WEIGHT_NEW = 0.55
#: 每次命中衰减的「保鲜」作用：命中一次把年龄按此折算（天）
ACCESS_REFRESH_DAYS = 3.0

_TYPES = {'milestone', 'event', 'user_mark', 'memory'}

# ---------- 可重算播报过滤（v3.1 P0 止血，2026-10-31）----------
# 背景：余额盯梢每 5 分钟上报一次 → 写进回忆 → prompt_hint 原样注入 system prompt，
#   且提示词写着「可以自然提及」⇒ 模型每轮被喂三条过期账，并被鼓励说出口。
# Owner 第一原则：能自己查到的不许进记忆；余额 / 花费属于此列。
# 纪律：这条判据只用来「排除」噪声，不用来「保留」内容 ——
#   排除错了顶多丢一条噪声，保留错了会每轮污染 prompt。
# 金额类：需同时出现 ¥ 才判（避免把「生活费 1500 元」这类真事实误滤）
_MONEY_PATTERNS = (
    re.compile(r'别处用了'),                        # 「别处用了约 ¥0.1500（12:29 → 12:34）」
    re.compile(r'用了约\s*[¥￥]'),                    # 「用了约 ¥0.1200」
    re.compile(r'[¥￥]\s*[\d.]+\s*[（(]\s*\d{1,2}:\d{2}'),   # 金额紧跟时间段 ⇒ 机械播报
    re.compile(r'余额\s*[¥￥]'),                      # 「余额 ¥29.62」
)

_ID_LOCK = threading.Lock()


def decayed_weight(base: float, age_days: float, pinned: bool = False) -> float:
    """时间衰减后的权重。半衰期 30 天，与 memory_engine.score_recency 同口径。

    pinned（钉住）不衰减 —— 核心事实（名字 / 忌口 / 雷区）不能因久不提及而消失，
    这是 Owner 原话「重要的东西会记下来」的落点。
    """
    if pinned:
        return float(base)
    try:
        a = max(0.0, float(age_days))
        b = max(0.0, min(WEIGHT_MAX, float(base)))
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, b * (0.5 ** (a / HALF_LIFE_DAYS)))


def entry_age_days(entry, now=None) -> float:
    """条目年龄（天）。解析不了按 0 天算（当新条目），不猜一个假的旧值。"""
    import datetime
    ts = str((entry or {}).get('time') or '').strip()
    if not ts:
        return 0.0
    now = now or datetime.datetime.now()
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            t = datetime.datetime.strptime(ts[:len(fmt) + 6], fmt)
            return max(0.0, (now - t).total_seconds() / 86400.0)
        except (ValueError, OverflowError) as _exc:
            # 逐格式试播：不匹配是预期分支，记 debug 便于排查真格式问题
            _log.debug('时间格式不匹配（%s）：%s', fmt, _exc)
            continue
    _log.debug('条目时间格式不认识（按新条目处理）：%r', ts)
    return 0.0


def effective_weight(entry, now=None) -> float:
    """有效权重 = 落盘 weight × 时间衰减；pinned 不衰减。

    旧条目没有 weight 字段 ⇒ 按 1.0 起算（不擅自回写用户数据）。
    """
    e = entry or {}
    try:
        base = float(e.get('weight', WEIGHT_NEW))
    except (TypeError, ValueError):
        base = 1.0
    return decayed_weight(base, entry_age_days(e, now), bool(e.get('pinned')))


def _next_id(used):
    """生成不撞号的回忆 id。

    原实现 `int(time.time() * 1000) % 10000000` 在同一毫秒内必然撞号 ——
    同一次抽取写两条事件正是这个场景（存量已有 3 组重复 id：35/36、39/40、41/42）。
    """
    cand = int(time.time() * 1000) % 10000000
    for _ in range(1000):
        if cand not in used:
            return cand
        cand = (cand + 1) % 10000000
    return cand          # 兜底：极端情况下不阻塞写入


# 自动播报类：句式本身足够特化，不需要 ¥
#   日期与提醒条数是实时可查值，写死即过期（2026-10-31 线上实测 ×2）
_AUTO_PATTERNS = (
    re.compile(r'今天是\s*\d{1,2}\s*月\s*\d{1,2}\s*日'),    # 「今天是 10月31日 星期六」
    re.compile(r'当前设置了\s*\d+\s*条提醒'),           # 「当前设置了 0 条提醒」
)


def is_recomputable_notice(title: str, detail: str = '') -> bool:
    """这条回忆是不是「随时能重算的机械播报」（余额 / 花费 / 问候模板）

    是 → 不入库、不注入 prompt。判据只用于排除，宁可多排。
    无金额、非模板句的普通回忆返回 False（防过滤过宽）。
    """
    text = '%s %s' % (title or '', detail or '')
    if any(p.search(text) for p in _AUTO_PATTERNS):
        return True
    if '¥' not in text and '￥' not in text:
        return False
    return any(p.search(text) for p in _MONEY_PATTERNS)


class MemoryEvents:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._memories = self._load()

    # ---------- 持久化 ----------
    def _load(self) -> list:
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except Exception:
            pass
        return []

    def _save(self):
        tmp = self.path + '.tmp'
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self._memories, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.remove(tmp)
            except Exception:
                pass

    # ---------- 写入 ----------
    def add(self, role: str, type_: str, title: str, detail: str = '',
            emotion: str = '', affection_at=None) -> dict:
        """新增一条回忆。超上限滚动淘汰最旧。

        v3.1：可重算的机械播报（余额 / 花费）**不入库**，直接返回 {}。
          —— 这类信息随时能查（api_stats.day_breakdown / balance_text），
             留在库里只会把真回忆挤出去，并被注入 prompt 当成旧账说出口。
          调用方若要展示（气泡 / 日志），请自行处理，不要依赖本函数落盘。
        """
        if type_ not in _TYPES:
            type_ = 'event'
        if is_recomputable_notice(title, detail):
            return {}          # 不入库；调用方保留自己的展示路径
        entry = {
            'id': 0,                      # 进锁后由 _next_id 赋真值（防同毫秒撞号）
            'time': time.strftime('%Y-%m-%d %H:%M'),
            'role': role,
            'type': type_,
            'title': title,
            'detail': detail,
            'emotion': emotion,
            'affection_at': affection_at,
            # v3.2 权重体系（Owner：「权重引入并且权重本身还会变化」）
            # 基础权重从 0.55 起（不是 1.0）：新条目还没被用过，不该一上来就是满分；
            #   被检索命中才涨（每次 +WEIGHT_BUMP），这才叫「权重可变」。
            'weight': WEIGHT_NEW,
            'access_count': 0,      # 被检索命中次数
            'last_access': '',      # 最近一次被命中的时间
            'pinned': False,        # 钉住：不衰减、不被淘汰
        }
        with self._lock:
            entry['id'] = _next_id({m.get('id') for m in self._memories})
            self._memories.append(entry)
            if len(self._memories) > MAX_MEMORIES:
                # v3.2：钉住的条目不参与淘汰 —— 核心事实不能因条数满被挤掉。
                #   先占掉 pinned 的位子，剩余名额给其余条目按「旧→新」淘汰。
                pinned = [m for m in self._memories if m.get('pinned')]
                others = [m for m in self._memories if not m.get('pinned')]
                keep = max(0, MAX_MEMORIES - len(pinned))
                kept = others[-keep:] if keep else []
                merged = [m for m in self._memories if m in pinned or m in kept]
                self._memories = merged[-MAX_MEMORIES:] if len(merged) > MAX_MEMORIES else merged
            self._save()
            return entry

    # ---------- 读取 ----------
    def recent(self, role: str, n: int = INJECT_COUNT) -> list:
        """该角色最近 n 条（时间倒序）"""
        with self._lock:
            items = [m for m in self._memories if m.get('role') == role]
            return list(reversed(items[-n:]))

    def all(self, role=None) -> list:
        """全部（时间倒序）。role 为空返回所有角色。"""
        with self._lock:
            items = self._memories if role is None else [m for m in self._memories if m.get('role') == role]
            return list(reversed(items))

    def clear(self, role=None):
        """清空（可按角色）"""
        with self._lock:
            if role is None:
                self._memories = []
            else:
                self._memories = [m for m in self._memories if m.get('role') != role]
            self._save()

    # ---------- 钉住 ----------
    def pin(self, entry_id) -> bool:
        """钉住一条：不衰减、不被淘汰。返回是否命中。"""
        with self._lock:
            for m in self._memories:
                if m.get('id') == entry_id:
                    m['pinned'] = True
                    self._save()
                    return True
        return False

    def unpin(self, entry_id) -> bool:
        """取消钉住。返回是否命中。"""
        with self._lock:
            for m in self._memories:
                if m.get('id') == entry_id:
                    m['pinned'] = False
                    self._save()
                    return True
        return False

    def _bump(self, pool, idx):
        """命中加权：在锁内改原条目（pool 里的 dict 就是 self._memories 的元素）"""
        m = pool[idx]
        try:
            m['access_count'] = int(m.get('access_count') or 0) + 1
        except (TypeError, ValueError):
            m['access_count'] = 1
        m['last_access'] = time.strftime('%Y-%m-%d %H:%M')
        try:
            base = float(m.get('weight', WEIGHT_NEW))
        except (TypeError, ValueError):
            base = 1.0
        # 命中即加权；同时把「年龄」折算掉一部分（说明它在被用，不该按老算）
        m['weight'] = min(WEIGHT_MAX, base + WEIGHT_BUMP)
        return m

    # ---------- 按内容检索 ----------
    def search(self, query: str, role=None, top_k: int = 3) -> list:
        """按内容检索共同经历（BM25 + 与事实记忆同一套相关性闸门）

        v3.2：原来只有 recent(3) —— 问「上次我们一起玩扫雷」时永远找不到，
              因为只按时间取最近几条，从不按内容找。这是「记不住」的根因。

        返回 [{'title','detail','time','score','matched','coverage'}]，时间正序。
        """
        if not query or not str(query).strip():
            return []
        with self._lock:
            pool = [m for m in self._memories
                    if (role is None or m.get('role') == role)]
        pool = [m for m in pool
                if not is_recomputable_notice(m.get('title', ''), m.get('detail', ''))]
        if not pool:
            return []
        try:
            from memory_engine import (BM25Index, GATE_MIN_MATCHED,
                                       GATE_MIN_COVERAGE, GATE_KEEP_RATIO)
        except Exception as _exc:
            _log.debug('事件检索不可用（memory_engine 导入失败）：%s', _exc)
            return []
        # S1：避免 title/detail 重复计分，但也不能丢掉其中一段的信息。
        #   写入侧 title 是 detail 的前 28 字（一方包含另一方）⇒ 只索引长的那一方；
        #   两者互不包含 ⇒ 都索引（否则 title 里的关键信息会检索不到）。
        docs = []
        for m in pool:
            _d = (m.get('detail') or '').strip()
            _t = (m.get('title') or '').strip()
            if _d and _t and _t not in _d and _d not in _t:
                text = '%s %s' % (_t, _d)
            else:
                text = _d if len(_d) >= len(_t) else _t
            docs.append({'id': m.get('id'), 'text': text})
        idx = BM25Index(docs)
        detailed = idx.search_detailed(query, top_k=max(top_k * 4, 12))
        # 相关性闸门：与 facts 同一套判据，治「问什么都往记忆上靠」
        kept = [d for d in detailed
                if d['matched'] >= GATE_MIN_MATCHED or d['coverage'] >= GATE_MIN_COVERAGE]
        if not kept:
            return []
        # S3：基准取**全部候选**的最高分，与 facts 侧 memory_engine 口径一致
        best = detailed[0]['score'] or 1.0
        kept = [d for d in kept if d['score'] >= best * GATE_KEEP_RATIO]
        kept.sort(key=lambda d: -d['score'])
        # M1c：按 (title, detail) 去重 —— 同一句模板曾占满全部 3 个槽位
        out, seen, seen_ids = [], set(), set()
        for d in kept:
            m = pool[d['index']]
            key = ((m.get('title') or '').strip(), (m.get('detail') or '').strip())
            if key in seen:
                continue
            _id = m.get('id')
            if _id is not None and _id in seen_ids:
                continue
            seen.add(key)
            if _id is not None:
                seen_ids.add(_id)
            out.append({'title': m.get('title', ''), 'detail': m.get('detail', ''),
                        'time': m.get('time', ''), 'score': d['score'],
                        'matched': d['matched'], 'coverage': d['coverage'],
                        'id': _id, 'weight': effective_weight(m)})
            if len(out) >= top_k:
                break
        # v3.2 权重可变：被检索命中即计次 + 加权（Owner：「权重本身还会变化」）。
        #   在锁内改原条目并落盘；只对真正要返回的 top_k 加权，不撒胡椒面。
        if out:
            with self._lock:
                bumped = False
                for h in out:
                    for i2, m in enumerate(self._memories):
                        if h.get('id') is not None and m.get('id') == h.get('id'):
                            self._bump(self._memories, i2)
                            bumped = True
                            break
                if bumped:
                    self._save()
        out.sort(key=lambda h: h.get('time', ''))
        return out

    # ---------- prompt 注入 ----------
    def prompt_hint(self, role: str, query: str = '') -> str:
        """拼成注入 system prompt 的回忆提示段（无回忆返回空串）

        v3.1：跳过可重算的机械播报，并**继续往前找**真回忆填满 INJECT_COUNT。
          —— 原实现直接取最近 3 条；库存被余额播报刷满后，注入的全是过期账。
        v3.2：传 query 时改走内容检索（相关的老回忆能压过无关的新回忆）；
              不传 query 时保持原行为，退回「最近几条」。
        """
        if query:
            hits = self.search(query, role=role, top_k=INJECT_COUNT)
            if not hits:
                # M2：给出 query 却没命中 ⇒ 本轮不注入（不退回 recent）。
                #     退回 recent 会把闸门整个绕掉，等于「问什么都往旧事上靠」。
                return ''
            lines = []
            for h in hits:
                detail = (h.get('detail') or '').strip()
                lines.append('- %s' % h['title'] + ('（%s）' % detail if detail else ''))
            return ('\n\n【我们的回忆（可以自然提及，不要生硬罗列）】\n'
                    + '\n'.join(lines))
        with self._lock:
            items = [m for m in self._memories if m.get('role') == role]
        picked = []
        seen = set()
        for m in reversed(items):          # 时间倒序往前找
            if is_recomputable_notice(m.get('title', ''), m.get('detail', '')):
                continue
            key = (m.get('title', ''), m.get('detail', ''))
            if key in seen:                 # 同句重复只留最近一条
                continue
            seen.add(key)
            picked.append(m)
            if len(picked) >= INJECT_COUNT:
                break
        if not picked:
            return ''
        # picked 已是「时间倒序」（从最新往前找），这里反一次得到时间正序；
        #   下方拼接不要再 reversed —— 原写法反了两次，注入顺序变成最新在前。
        items = list(reversed(picked))
        lines = []
        for m in items:            # 已是时间正序（只在此处反一次）
            title = m.get('title', '')
            detail = m.get('detail', '')
            lines.append(f"- {title}" + (f"（{detail}）" if detail else ""))
        return '\n\n【我们的回忆（可以自然提及，不要生硬罗列）】\n' + '\n'.join(lines)
