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
import hashlib
import json
import logging
import os
import re
import threading
import time

_log = logging.getLogger('pet.memory_events')

MAX_MEMORIES = 200          # 滚动淘汰上限
INJECT_COUNT = 3            # prompt 注入最近 N 条
HALF_LIFE_DAYS = 30.0           # 权重衰减半衰期（天）—— 两种模型下语义相同
#: 衰减模型（Owner 2026-11-02 拍板：改幂律）
#:   'power'       幂律 f(a) = (1 + a/T)^(-d) —— 默认
#:   'exponential' 指数 f(a) = 0.5^(a/HALF_LIFE) —— 旧行为，保留以便对照/回退
DECAY_MODEL = 'power'
#: 幂律指数 d（ACT-R 默认 0.5）。Schooler & Anderson 1997：环境里一个事实
#: 被需要的几率本身按幂函数衰减 —— 不是人碰巧长成幂律，是环境本来如此。
POWER_D = 0.5
#: 每次被检索命中时权重上升的幅度（Owner：「被反复提及的记忆权重上升」）
WEIGHT_BUMP = 0.06
#: 权重上限
WEIGHT_MAX = 1.0
#: 新条目的初始权重（还没被用过，不该一上来满分）
WEIGHT_NEW = 0.55
#: 每次命中衰减的「保鲜」作用：命中一次把年龄按此折算（天）
ACCESS_REFRESH_DAYS = 3.0
#: 淘汰台账文件（与 memories.json 同目录）。追加式 JSONL，一行一条。
#: ⚠ 2026-11-02 新增（Owner「淘汰可以」，评审-168 §五 建议1）：
#:   原来超 200 条直接切片丢弃，**丢了什么没有任何记录**，事后无法回答
#:   「那条记忆是何时、为何没的」。台账让「遗忘」变成可追溯的行为。
EVICTED_NAME = 'memory_evicted.jsonl'
#: 台账最大行数；超过就轮转（旧的存成 .1，只留一代）—— 防止台账自己无限长
EVICTED_MAX_LINES = 5000

_TYPES = {'milestone', 'event', 'user_mark', 'memory'}


def _is_critical_event(m):
    """这条 event 是否属于「失效代价高」（不该被 200 条滚动淘汰挤掉）。

    2026-11-07 加。起因：写入边界会把「用户正在服药，每天两次」这类判进 events，
    而本层原本只认 pinned —— 服药/用药类会按插入顺序被淘汰（评审-183 §一/§1.2）。

    判据复用 memory_fact_evict 的词表，但**只在本层（淘汰保护）使用**，
    不在写入侧用于分层：实测在 classify 里按 critical 返 fact 会新增 6 条误杀。
    """
    try:
        import memory_fact_evict as _mfe
    except Exception as exc:
        # ⛔ 不能裸 return —— test_silent_guard 会判「新增静默失败点」
        #    （2026-11-07 实测：这条正是被护栏抓出来的，基线内已知 510 处、我新增 1 处）
        _log.warning('critical 词表不可用，本条不享受淘汰豁免：%r', exc)
        return False
    title = m.get('title') or ''
    detail = m.get('detail') or ''
    return _mfe.is_critical_text('%s %s' % (title, detail))

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


def decay_factor(age_days: float) -> float:
    """时间衰减因子（0~1）。**全项目唯一一份** —— 星图亮度也从这里取，别再写第二份。

    ⚠ 2026-11-02（Owner 拍板「衰减改幂律」，依据 评审-171 §二 修正二）：

      旧：f(a) = 0.5^(a/30)            指数
      新：f(a) = (1 + a/T)^(-d)        幂律，T 与 d 取到 f(30) == 0.5
               d = POWER_D = 0.5，T = 30/(2^(1/d)-1) = 10

    **为什么要改**（不是喜好，是两个可验的差别）：

    | 年龄 | 指数 | 幂律 |
    |---|---|---|
    | 30 天 | 0.500 | 0.500 | ← 同半衰期，中间点完全一致
    | 90 天 | 0.125 | 0.316 |
    | 1 年 | 0.0002 | 0.163 |
    | 3 年 | 1.6e-10 | 0.0995 |

    ⇒ 指数衰减下「3 年前那件事」权重约等于 0，系统等于认为**它从未发生**；
      幂律永不归零，与「模糊的壳一直留着、只是细节掉了」这种真实记忆形状一致。
      依据是 ACT-R 的 B_i = ln(Σ t_j^(-d))（d 默认 0.5）+ Schooler & Anderson 1997
      的理性分析：环境里一个事实被需要的几率本身按幂函数衰减。

    ⛔ 已知取舍（写清，别当它是免费的）：同类实践项目 CogCor / openfeelz **都用指数**。
       改幂律是走没人走的路 —— 不是补作业，是押注。DECAY_MODEL 保留 'exponential'
       就是为了能一键对照回去。
    """
    try:
        a = max(0.0, float(age_days))
    except (TypeError, ValueError):
        return 0.0
    if DECAY_MODEL != 'power':
        return 0.5 ** (a / HALF_LIFE_DAYS)
    d = float(POWER_D) if POWER_D else 0.5
    # T 取到「半衰期那一点仍为 0.5」，这样 HALF_LIFE_DAYS 的语义不因换模型而变，
    # 配置与既有测试都不用改。
    t = HALF_LIFE_DAYS / (2.0 ** (1.0 / d) - 1.0)
    return (1.0 + a / t) ** (-d)


def decayed_weight(base: float, age_days: float, pinned: bool = False) -> float:
    """时间衰减后的权重。半衰期 30 天，与 memory_engine.score_recency 同口径。

    pinned（钉住）不衰减 —— 核心事实（名字 / 忌口 / 雷区）不能因久不提及而消失，
    这是 Owner 原话「重要的东西会记下来」的落点。
    """
    if pinned:
        return float(base)
    try:
        b = max(0.0, min(WEIGHT_MAX, float(base)))
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, b * decay_factor(age_days))


def entry_age_days(entry, now=None) -> float:
    """条目年龄（天）。解析不了按 0 天算（当新条目），不猜一个假的旧值。

    v3.3（2026-10-31，分流报告暴露）：
      事实侧没有 time 字段，只有 created_at / updated_at。
      原先只按 created_at 算 ⇒「我的名字叫小蓝」年龄 89.8 天、有效权重 0.069，
      和「爱吃桃片」一样低 —— 但身份事实每轮都该在。
      **事实是「状态」不是「事件」**：updated_at 更新过就说明还在被维护，
      所以年龄取 created_at 与 updated_at 中**更近**的那个。
    """
    import datetime
    e = entry or {}
    cands = []
    for k in ('time', 'last_access', 'updated_at', 'created_at'):
        v = str(e.get(k) or '').strip()
        if v:
            cands.append(v)
    if not cands:
        return 0.0
    # 取「最新的那个时间点」= 年龄最小
    ts = max(cands)
    now = now or datetime.datetime.now()
    for fmt in ('%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S',
                '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            t = datetime.datetime.strptime(ts[:len(fmt) + 6], fmt)
            return max(0.0, (now - t).total_seconds() / 86400.0)
        except (ValueError, OverflowError) as _exc:
            # 逐格式试播：不匹配是预期分支，记 debug 便于排查真格式问题
            _log.debug('时间格式不匹配（%s）：%s', fmt, _exc)
            continue
    _log.debug('条目时间格式不认识（按新条目处理）：%r', ts)
    return 0.0


#: 身份判据（与 memory_engine._IDENTITY_PATTERNS 同源，避免两套规则漂移）
_IDENTITY_HINTS = ('我的名字叫', '我叫', '名字叫', '用户叫', '称呼为',
                   '角色叫', '模型姐姐叫', '的姐姐叫', '是我')


def is_identity_entry(entry) -> bool:
    """这条是不是「身份/命名」类（永不衰减，不参与降级）"""
    text = str((entry or {}).get('title') or (entry or {}).get('content') or '').strip()
    if not text or len(text) > 80:
        return False
    return any(p in text for p in _IDENTITY_HINTS)


def effective_weight(entry, now=None) -> float:
    """有效权重 = 落盘 weight x 时间衰减；pinned 与身份类不衰减。

    旧条目没有 weight 字段 => 按 WEIGHT_NEW 起算（不擅自回写用户数据）。

    v3.3（2026-10-31，分流报告暴露）：衰减不能是唯一降级判据。
      实测「我的名字叫小蓝」created_at == updated_at（从没更新过），
      年龄 89.8 天 => 权重 0.069，和「爱吃桃片」一样低 —— 但它每轮都必须在。
      => 身份类一律视为钉住（只在计算时生效，不写盘、不改用户数据）。
    """
    e = entry or {}
    try:
        base = float(e.get('weight', WEIGHT_NEW))
    except (TypeError, ValueError):
        base = WEIGHT_NEW
    pinned = bool(e.get('pinned')) or is_identity_entry(e)
    return decayed_weight(base, entry_age_days(e, now), pinned)


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
        # 台账与记忆库同目录（不放别处：备份/迁移时两者一定一起走）
        self.evicted_path = os.path.join(os.path.dirname(os.path.abspath(path)),
                                         EVICTED_NAME)
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

    # ---------- 淘汰台账 ----------
    def record_evicted(self, items, reason: str = 'overflow', kept: int = 0) -> int:
        """把即将被删掉的条目**先**记进台账。返回成功记下的条数。

        ⚠ 纪律：调用方必须**先调本函数、再删**。顺序反了就没有「删之前一定记过」。
        ⚠ 写失败不影响淘汰（库里无限增长会让 prompt 注入爆掉，比不可追溯更糟），
          但必须落痕 —— 静默失败是最坏的一种。
        ⚠ 字段一律 .get()：老数据有 3 种字段集（评审-172 发现 D），不许假设字段齐全。
        """
        if not items:
            return 0
        stamp = time.strftime('%Y-%m-%d %H:%M')
        rows = []
        for m in items:
            try:
                # content_hash：库删了 id 之后，靠它还能认出「当时删的是哪条内容的版本」
                #   （评审-174 §六 第 3 条）。title + detail 拼起来取前 16 位。
                _raw = ((m.get('title') or '') + '\x00' + (m.get('detail') or '')).encode('utf-8')
                _hash = hashlib.sha256(_raw).hexdigest()[:16]
                rows.append(json.dumps({
                    't': stamp,
                    'reason': reason,
                    'id': m.get('id'),
                    # ⚠ 加 version=2：老台账没有这两个字段，靠它区分
                    'v': 2,
                    'content_hash': _hash,
                    'title': m.get('title') or '',
                    'time': m.get('time') or '',
                    'weight': m.get('weight'),
                    'access_count': m.get('access_count'),
                    'origin': m.get('origin') or 'user',
                    'repeat_count': m.get('repeat_count'),
                    'kept': kept,
                    # committed=False 表示「已记账、尚未确认删除成功」
                    #   淘汰写台账成功、删记忆失败（进程被 kill 在中间）时，
                    #   重启后台账里有一条「已淘汰」但记忆还在 ⇒ 对账会以为它没了。
                    #   删成功后再 update_evicted_committed() 改成 True。
                    'committed': False,
                }, ensure_ascii=False))
            except Exception as exc:
                _log.debug('台账序列化失败（跳过该条）：%r', exc)
        if not rows:
            return 0
        try:
            # 轮转：先看现有行数，超上限就把旧文件改名（只留一代）
            if os.path.exists(self.evicted_path):
                try:
                    with open(self.evicted_path, encoding='utf-8') as fh:
                        n = sum(1 for _ in fh)
                except Exception as exc:
                    # 落痕：数不了行数 ≠ 台账是空的。静默按 0 处理会让轮转永不触发，
                    # 台账悄悄涨到无限长（那正是轮转要防的事）。
                    _log.warning('台账行数读不出来（按 0 处理，轮转本轮跳过）：%r', exc)
                    n = 0
                if n >= EVICTED_MAX_LINES:
                    bak = self.evicted_path + '.1'
                    try:
                        if os.path.exists(bak):
                            os.remove(bak)
                        os.replace(self.evicted_path, bak)
                    except Exception as exc:
                        _log.warning('台账轮转失败（继续追加）：%r', exc)
            with open(self.evicted_path, 'a', encoding='utf-8', newline='\n') as fh:
                fh.write('\n'.join(rows) + '\n')
            return len(rows)
        except Exception as exc:
            _log.warning('淘汰台账写入失败（淘汰仍会继续，但这条不可追溯）：%r', exc)
            return 0

    def update_evicted_committed(self, ids, committed: bool = True) -> int:
        """把台账里这些 id 的 committed 标记改掉。返回改了条数。

        ⚠ 为什么要它（评审-174 §六 第 3 条）：淘汰是「先记账 → 再删」两步，
          中间被 kill 就会留下「台账说已淘汰、库里还在」的假记录。
          本方法在删除**确认成功后**才把 committed 置 True，
          对账时「committed=false 且库里没有」才是真异常。

        ⚠ 重写整个文件（台账 5000 行上限，可接受）；失败落痕不吞。
        """
        ids = {str(i) for i in (ids or []) if i is not None}
        if not ids or not os.path.exists(self.evicted_path):
            return 0
        rows = []
        changed = 0
        try:
            with open(self.evicted_path, encoding='utf-8') as fh:
                for line in fh:
                    t = line.strip()
                    if not t:
                        continue
                    try:
                        d = json.loads(t)
                    except Exception as exc:
                        # 落痕：一行坏了就原样保留、不阻断整次更新。
                        # 但「有一行解析不了」是台账正在腐坏的信号，必须看得见。
                        _log.warning('台账有一行解析不了（原样保留，该行 committed 无法更新）：'
                                     '%r：%r', t[:80], exc)
                        rows.append(t)
                        continue
                    if str(d.get('id')) in ids and d.get('committed') is not committed:
                        d['committed'] = committed
                        changed += 1
                    rows.append(json.dumps(d, ensure_ascii=False))
            if changed:
                tmp = self.evicted_path + '.tmp'
                with open(tmp, 'w', encoding='utf-8', newline='\n') as fh:
                    fh.write('\n'.join(rows) + '\n')
                os.replace(tmp, self.evicted_path)
            return changed
        except Exception as exc:
            _log.warning('台账 committed 更新失败（对账时需人工确认）：%r', exc)
            return 0

    def evicted_recent(self, n: int = 20) -> list:
        """最近 n 条淘汰记录（时间倒序）。台账不存在返回空表 —— 不是错误。"""
        if not os.path.exists(self.evicted_path):
            return []
        out = []
        try:
            with open(self.evicted_path, encoding='utf-8') as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        _log.debug('台账有一行解析不了（跳过）：%r', line[:80])
        except Exception as exc:
            _log.warning('读淘汰台账失败：%r', exc)
            return []
        return list(reversed(out[-n:]))

    # ---------- 写入 ----------
    def add(self, role: str, type_: str, title: str, detail: str = '',
            emotion: str = '', affection_at=None, origin: str = 'user') -> dict:
        """新增一条回忆。超上限滚动淘汰最旧。

        v3.1：可重算的机械播报（余额 / 花费）**不入库**，直接返回 {}。
          —— 这类信息随时能查（api_stats.day_breakdown / balance_text），
             留在库里只会把真回忆挤出去，并被注入 prompt 当成旧账说出口。
          调用方若要展示（气泡 / 日志），请自行处理，不要依赖本函数落盘。

        origin（v3.4，2026-10-31，评审-158 指出）：
            'user' 主人说的 / 从对话里提取的 —— **默认**
            'pet'  桌宠自己推送的（定时关心、提醒）

            ⚠ 为什么必须区分：合并时给权重加分，本意是「主人反复提到越重要」。
              但定时关心是一句固定模板，一天触发几十次，照样能把权重推到满格。
              那不是「被反复提及」，是「定时器跑了很多次」。
              实测（2026-10-31）：库里那条「记得站起来活动一下」合并 32 次、
              weight=1.00 满格，而它恰恰是压梗概时「该先压」的那类。
              ⇒ 'pet' 来源的合并只累加 repeat_count，**不动 weight**。
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
            # v3.4：来源与重复推送次数（区分「主人反复提及」和「定时器反复触发」）
            'origin': 'pet' if str(origin or '').strip().lower() == 'pet' else 'user',
            'repeat_count': 0,
        }
        with self._lock:
            # v3.3（2026-10-31，存量清理暴露）：同一句话反复触达不该攒条目。
            #   实测删完噪音后剩 26 条，其中 24 条是同一句「记得站起来活动一下」。
            #   查重：同 role/type/title/detail ⇒ 合并到已有那条，累加计数 + 加权。
            #   这也正是 Owner 说的「被反复提及的记忆权重上升」的正确落点。
            _t = (title or '').strip()
            _d = (detail or '').strip()
            for _ex in self._memories:
                if (_ex.get('role') == role and _ex.get('type') == type_
                        and (_ex.get('title') or '').strip() == _t
                        and (_ex.get('detail') or '').strip() == _d):
                    try:
                        _ex['access_count'] = int(_ex.get('access_count') or 0) + 1
                    except (TypeError, ValueError):
                        _ex['access_count'] = 1
                    _ex['last_access'] = entry['time']
                    # v3.4：重复推送次数恒增（这条信息本身有用：能看出是不是机械重复）
                    try:
                        _ex['repeat_count'] = int(_ex.get('repeat_count') or 0) + 1
                    except (TypeError, ValueError):
                        _ex['repeat_count'] = 1
                    # 只有「人说的」才涨权重。桌宠自己推的模板不动权重 ——
                    # 否则定时器跑几十次就能把一条废话推到满格（评审-158 实测症状）。
                    _this_origin = 'pet' if str(origin or '').strip().lower() == 'pet' else 'user'
                    _ex_origin = _ex.get('origin') or 'user'     # 老数据无此字段 ⇒ 按 user
                    if _this_origin == 'user':
                        try:
                            _b = float(_ex.get('weight', WEIGHT_NEW))
                        except (TypeError, ValueError):
                            _b = WEIGHT_NEW
                        _ex['weight'] = min(WEIGHT_MAX, _b + WEIGHT_BUMP)
                        # 老条目本来没 origin，被主人提了一次就说明它确实是「人说的」
                        if _ex_origin == 'pet':
                            _ex['origin'] = 'user'
                    if emotion and not _ex.get('emotion'):
                        _ex['emotion'] = emotion
                    if affection_at is not None:
                        _ex['affection_at'] = affection_at
                    self._save()
                    return _ex
            entry['id'] = _next_id({m.get('id') for m in self._memories})
            self._memories.append(entry)
            if len(self._memories) > MAX_MEMORIES:
                # v3.2：钉住的条目不参与淘汰 —— 核心事实不能因条数满被挤掉。
                #   先占掉 pinned 的位子，剩余名额给其余条目按「旧→新」淘汰。
                pinned = [m for m in self._memories if m.get('pinned')]
                others = [m for m in self._memories if not m.get('pinned')]
                # 2026-11-07 补（评审-186 §一 指出的真缺陷）：**critical 条目也豁免**。
                #   写入边界会把「用户正在服药」这类判进 events，而本层原本只认 pinned
                #   ⇒ 服药/用药类会按插入顺序被滚动淘汰。
                #   ⚠ 用 is_critical_text(title+detail) 而不是在写入侧返 fact：
                #     实测在 classify 里按 critical 返 fact 会新增 6 条误杀
                #     （「助手建议我服用维生素」「用户怕打针」等被钉死）。
                crit = [m for m in others if _is_critical_event(m)]
                normal = [m for m in others if not _is_critical_event(m)]
                keep = max(0, MAX_MEMORIES - len(pinned) - len(crit))
                kept = normal[-keep:] if keep else []
                merged = [m for m in self._memories
                          if m in pinned or m in crit or m in kept]
                new_list = merged[-MAX_MEMORIES:] if len(merged) > MAX_MEMORIES else merged
                # 2026-11-02（Owner「淘汰可以」）：**先记账、再删**。
                #   算出「原来有、现在没有」的那些 = 真正被淘汰的，先写台账。
                #   ⛔ 顺序不许反：反了就没有「删之前一定记过」。
                _rec_ids = []
                try:
                    gone = [m for m in self._memories if m not in new_list]
                    if gone:
                        self.record_evicted(gone, reason='overflow', kept=len(new_list))
                        _rec_ids = [m.get('id') for m in gone]
                except Exception as exc:
                    _log.warning('淘汰台账环节异常（淘汰照常进行）：%r', exc)
                self._memories = new_list
                # 删除已生效 ⇒ 把台账里的 committed 置 True。
                # 若这里被 kill，台账会留 committed=false，对账时能分辨。
                if _rec_ids:
                    self.update_evicted_committed(_rec_ids, True)
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
        """命中加权：在锁内改原条目（pool 里的 dict 就是 self._memories 的元素）

        ⚠ 2026-11-03 补 origin 保护（评审-174 §四-b 报出，我核实成立）：

          `add()` 的合并路径**特意**做了「pet 不动 weight」——
            原注释：「定时关心是一句固定模板，一天触发几十次，照样能把权重推到满格。
            那不是『被反复提及』，是『定时器跑了很多次』。⇒ 'pet' 来源只累加
            repeat_count，不动 weight。」
          但 `_bump()`（检索命中路径）**无条件** `weight = min(MAX, base + 0.06)`
          ⇒ **同一个风险，一条路堵了、一条路漏着。**

          后果：一条 origin='pet' 的模板话被检索命中 8 次：
            0.55 + 8 × 0.06 = 1.03 → min() 截到 1.0 = WEIGHT_MAX 满格
          正是 评审-158 要防的那个症状，从另一条路径绕回来了。

          ⚠ 自限说明：当前 6 条 weight 全是 0.55（= WEIGHT_NEW），
            说明 `_bump` 在这个库上几乎没真正生效过 ⇒ **这是代码层不一致，不是已发生事故。**
            但一旦接上语义检索、命中率上去，它就会变成事故。
        """
        m = pool[idx]
        try:
            m['access_count'] = int(m.get('access_count') or 0) + 1
        except (TypeError, ValueError):
            m['access_count'] = 1
        m['last_access'] = time.strftime('%Y-%m-%d %H:%M')
        # 只有「人说的」才因命中而加权 —— 与 add() 合并路径同一个判据
        if (m.get('origin') or 'user') == 'pet':
            return m
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
