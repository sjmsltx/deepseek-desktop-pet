# -*- coding: utf-8 -*-
"""3.0 · M1 消息内核(RelayLog)-- 依《用例设计_冻结版v2》逐条对齐实现。

核心承诺:**绝不静默烧钱** -- 触顶必须「停 + 出结论 + @人类」,此后不再发请求。
关键约定(与冻结契约/用例一致):
  · provider **外部注入**(内核绝不自己发请求)→ 调用次数可断言
  · `clock` 可注入;**时长从 open_issue 起算**,判据 `>=`
  · 金额 **微元整数**,字段 `cost_micro`;**记账唯一入口 = append()**(step 不重复累加)
  · `seq` 严格单调(写层自增);`ts` 仅展示、可回拨
  · 读接口(replay/inbox/view/...) 会**按文件变化自动重载** → 支持"外部导入/直写日志"
  · 人类插队:**立即进入暂停**(不再有新回合),**绝不自动恢复**;"继续"必须显式
  · 收束结论 kind = `system`(meta 里另标 arbitrate=True),且**幂等**
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Callable, Iterable, Optional

SCHEMA_V = 1

# ---------------------------------------------------------------- 异常面(冻结)
class RelayError(Exception):
    """内核异常基类。"""

class RelayWriteError(RelayError):
    """盘写入失败 -- 硬失败:上层须停 + @人类。"""

class RelayDuplicateId(RelayError):
    """写层:同 id 重复写入(拒绝并告警,不覆盖、不重号)。"""

class RelayTooLarge(RelayError):
    """写层:单条正文超限(拒绝,不静默截断)。"""

# ---------------------------------------------------------------- 数据类型(冻结)
@dataclass(frozen=True)
class Issue:
    title: str
    goal: str
    done_when: str

    def missing(self) -> str:
        miss = []
        if not (self.title or '').strip():
            miss.append('title')
        if not (self.goal or '').strip():
            miss.append('goal')
        if not (self.done_when or '').strip():
            miss.append('done_when')
        return ('缺 ' + '/'.join(miss)) if miss else ''

@dataclass(frozen=True)
class Msg:
    id: str
    seq: int
    ts: int
    channel: str
    sender: str
    recipients: list = field(default_factory=list)
    kind: str = 'speak'
    visibility: str = 'human'
    body: str = ''
    meta: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @staticmethod
    def from_dict(d: dict) -> 'Msg':
        return Msg(
            id=str(d.get('id', '')),
            seq=int(d.get('seq', 0) or 0),
            ts=int(d.get('ts', 0) or 0),
            channel=str(d.get('channel', '')),
            sender=str(d.get('sender', '')),
            recipients=list(d.get('recipients') or []),
            kind=str(d.get('kind', 'speak')),
            visibility=str(d.get('visibility', 'human')),
            body=str(d.get('body', '')),
            meta=dict(d.get('meta') or {}),
        )

@dataclass(frozen=True)
class ProviderReply:
    body: str
    tokens: int = 0
    cost_micro: int = 0
    meta: dict = field(default_factory=dict)

@dataclass(frozen=True)
class StepResult:
    ok: bool = True
    stopped: bool = False
    reason: str = ''
    turn_no: int = 0
    notice_human: bool = False
    cost_micro: int = 0
    provider_calls: int = 0

DEFAULT_LIMITS = {
    'max_turns': 8,
    'time_limit_ms': 300_000,
    'max_tokens': 0,
    'max_cost_micro': 0,
    'retry_max': 2,
    'converge_no_new': 2,
    'msg_max_bytes': 65_536,
    'interrupt_timeout_ms': 60_000,   # 仅用于"提醒一次";严禁自动恢复
}

# 显式"继续"白名单(N2)
RESUME_WORDS = {'继续', '继续吧', '继续。', 'continue', 'go on', 'resume'}

# ---------------------------------------------------------------- 圆桌额度配置（门槛第 1 件）
# ⭐ Owner 2026-10-02 21:53 批：「成本上限默认值 → 自定义」
#   · DEFAULT_LIMITS 里的 0 = 不限 **保持不动** ✗（不预先塞死数 ✓）
#   · 用户可配：config.json 的 `roundtable_limits` 键 ✓（GUI 入口见 settings_ui 的「用量与计费」页 ✓）
#   · 未设置 = 不覆盖默认（仍是不限 ✓）；非法值**不静默** ✗
LIMITS_CONFIG_KEY = 'roundtable_limits'
_FLAT_KEY_PREFIX = 'roundtable_'          # ⭐ GUI 保存的扁平键前缀（roundtable_max_tokens 等 ✓）
_CUSTOM_LIMIT_KEYS = ('max_tokens', 'max_cost_micro', 'interrupt_timeout_ms')
DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')


def load_limits(config_path=None, *, warn=None) -> dict:
    """从配置文件读**自定义**圆桌额度；返回的 dict 供 `RelayLog(limits=...)` 用。

    兼容两种写法：① `"roundtable_limits": {...}` 对象 ✓  ② 存成 JSON 字符串 ✓（GUI 保存路径）
    未配置/文件不存在 → 返回 `{}`（= 不覆盖默认 = 不限 ✓）
    非法值 → 跳过该键 ＋ `warn(msg)`（无 warn 则写 stderr ✓ **不静默** ✗）
    """
    path = config_path or DEFAULT_CONFIG_PATH
    out: dict = {}
    problems: list = []
    try:
        with open(path, encoding='utf-8') as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        return out
    except Exception as exc:
        problems.append('配置读取失败（%s）：%s' % (path, exc))
        cfg = {}
    raw = cfg.get(LIMITS_CONFIG_KEY) if isinstance(cfg, dict) else None
    if isinstance(raw, str):                      # 若存成 JSON 字符串 ✓
        try:
            raw = json.loads(raw)
        except Exception:
            problems.append('圆桌额度不是合法 JSON，已忽略')
            raw = None
    if isinstance(raw, dict):
        _pairs = [(k, raw[k]) for k in _CUSTOM_LIMIT_KEYS if k in raw]
    else:
        if raw is not None:
            problems.append('圆桌额度 %s 应为对象，已忽略（实得 %s）'
                            % (LIMITS_CONFIG_KEY, type(raw).__name__))
        # ⭐ 后门：也认**扁平键**（GUI 保存路径 ✓ 不需嵌套 JSON ✓）
        _pairs = [(_k, cfg.get(_FLAT_KEY_PREFIX + _k))
                  for _k in _CUSTOM_LIMIT_KEYS if _FLAT_KEY_PREFIX + _k in cfg]
    for k, v in _pairs:
        if isinstance(v, bool) or not isinstance(v, int):
            problems.append('圆桌额度 %s 必须是整数，已忽略（实得 %r）' % (k, v))
            continue
        if v < 0 or (k == 'interrupt_timeout_ms' and v == 0):
            problems.append('圆桌额度 %s 取值非法，已忽略（实得 %r）' % (k, v))
            continue
        out[k] = v
    for msg in problems:
        if warn:
            warn(msg)
        else:
            sys.stderr.write('[relay_log] %s\n' % msg)
    return out


def limits_configured(config_path=None) -> bool:
    """是否已显式配置圆桌额度（供"首次进圆桌提示一次"用 ✓）。"""
    return bool(load_limits(config_path, warn=lambda _m: None))

_STOP = set('的 了 是 我 你 他 她 它 们 和 与 及 或 在 有 就 都 也 还 把 被 让 给 对 从 到 这 那 一个 一种 可以 需要 应该 我们 你们 他们 而且 但是 所以 因为 如果 那么 什么 怎么 这个 那个 一点 一下 吧 呢 啊 呀 嗯 好 行 要 会 能'.split())
_SIG_TOKEN = re.compile(r'[A-Za-z0-9_./\\:-]+|[\u4e00-\u9fff]{2,}')

def _signature(text: str) -> set:
    out = set()
    for tok in _SIG_TOKEN.findall(text or ''):
        t = tok.strip().lower()
        if t and t not in _STOP:
            out.add(t)
    return out


class RelayLog:
    def __init__(self, path, *, clock: Optional[Callable[[], int]] = None,
                 limits: Optional[dict] = None,
                 provider: Optional[Callable[[Msg, Issue], ProviderReply]] = None):
        self.path = str(path)
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.limits = dict(DEFAULT_LIMITS)
        if limits:
            self.limits.update(limits)
        self.provider = provider
        self._lock = threading.RLock()

        self._msgs: list = []
        self._by_id: dict = {}
        self._seq = 0
        self._stat = None
        self.warnings: list = []
        self.issue: Optional[Issue] = None
        self.turn_no = 0
        self.tokens = 0
        self.cost_micro = 0
        self.interrupted = False
        self.concluded = False
        self.stopped = False
        self.stop_reason = ''
        self._notice_sent = False
        self._no_new_streak = 0
        self._prev_sig: set = set()
        self._started_ts: Optional[int] = None
        self._use_current_issue_channel = 'group:main'

        d = os.path.dirname(os.path.abspath(self.path))
        if d:
            os.makedirs(d, exist_ok=True)
        self._saw_interrupt = False
        self._reload()
        self.interrupted = bool(self._saw_interrupt)

    # ------------------------------------------------------------ 内部:读 / 重载
    def _file_stat(self):
        try:
            st = os.stat(self.path)
            return (st.st_mtime_ns, st.st_size)
        except Exception:
            return None

    def _reload(self):
        """从文件重读(append-only,只读不改写)。坏行跳过并告警。"""
        self._msgs = []
        self._by_id = {}
        self._seq = 0
        self.turn_no = 0
        self.tokens = 0
        self.cost_micro = 0
        self._stat = self._file_stat()
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, 'r', encoding='utf-8', errors='replace') as fh:
                for lineno, line in enumerate(fh, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        self.warnings.append('坏行跳过:第 %d 行(半条/非法 JSON)' % lineno)
                        continue
                    msg = Msg.from_dict(d)
                    if not msg.id:
                        self.warnings.append('坏行跳过:第 %d 行(缺 id)' % lineno)
                        continue
                    self._msgs.append(msg)
                    self._by_id[msg.id] = msg
                    self._seq = max(self._seq, msg.seq)
                    meta = msg.meta or {}
                    if 'v' not in meta:
                        self.warnings.append('旧格式行(无 v):%s' % msg.id)
                    if meta.get('billable', True) and 'tokens' in meta:
                        self.tokens += int(meta.get('tokens') or 0)
                    if 'cost_micro' in meta and meta.get('billable', True):
                        self.cost_micro += int(meta.get('cost_micro') or 0)
                    elif msg.kind != 'system' and meta.get('billable', True):
                        self.warnings.append('条目 %s 缺 cost_micro，按 0 计并留痕' % msg.id)
                    tno = int(meta.get('turn_no') or 0)
                    if tno > self.turn_no:
                        self.turn_no = tno
                    # ★ 状态必须能从日志重建("可回放"验收要求)
                    if msg.kind == 'system' and meta.get('arbitrate'):
                        self.concluded = True
                        self.stopped = True
                        self.stop_reason = str(meta.get('reason') or 'converged')
                        self._notice_sent = True
                    if meta.get('interrupt'):
                        self._saw_interrupt = True
                    if meta.get('resumed'):
                        self._saw_interrupt = False
        except Exception as exc:
            raise RelayWriteError('读取日志失败:%r' % exc)

    def _maybe_reload(self):
        """文件被外部改动(导入/直写/截断)时自动重载 -- 读接口的真相源始终是文件。"""
        if self._file_stat() != self._stat:
            self._reload()

    # ------------------------------------------------------------ 议题
    def open_issue(self, issue: Issue):
        bad = issue.missing()
        if bad:
            return False, bad
        bad_limits = []
        if self.limits.get('max_turns', 0) <= 0:
            bad_limits.append('max_turns')
        for k in ('time_limit_ms', 'max_tokens', 'max_cost_micro', 'retry_max',
                  'converge_no_new', 'msg_max_bytes'):
            if self.limits.get(k, 0) < 0:
                bad_limits.append(k)
        if bad_limits:
            return False, '上限非法:%s' % '/'.join(bad_limits)
        self.issue = issue
        self.turn_no = 0
        self.concluded = False
        self.stopped = False
        self.stop_reason = ''
        self.interrupted = False
        self._notice_sent = False
        self._no_new_streak = 0
        self._prev_sig = set()
        self._started_ts = self.clock()          # ★ 时长基准 = 议题开始时刻
        return True, '议题已建立'

    # ------------------------------------------------------------ 写层(记账唯一入口)
    def append(self, msg):
        with self._lock:                      # 单写者 + 队列语义:进程内写入串行化
            return self._append_locked(msg)

    def _append_locked(self, msg):
        d = asdict(msg) if isinstance(msg, Msg) else dict(msg or {})
        mid = str(d.get('id') or '')
        if not mid:
            raise RelayError('id 不能为空')
        if mid in self._by_id:
            self.warnings.append('写层拒绝重复 id:%s(未覆盖、未重号)' % mid)
            raise RelayDuplicateId(mid)
        body = str(d.get('body') or '')
        limit = int(self.limits.get('msg_max_bytes', 65536))
        if len(body.encode('utf-8')) > limit:
            self.warnings.append('写层拒绝超长正文:%s(%d 字节 > %d)'
                                 % (mid, len(body.encode('utf-8')), limit))
            raise RelayTooLarge(mid)
        self._seq += 1
        meta = dict(d.get('meta') or {})
        meta['v'] = SCHEMA_V
        out = Msg(
            id=mid, seq=self._seq, ts=int(d.get('ts') or self.clock()),
            channel=str(d.get('channel') or ''), sender=str(d.get('sender') or ''),
            recipients=list(d.get('recipients') or []),
            kind=str(d.get('kind') or 'speak'),
            visibility=str(d.get('visibility') or 'human'),
            body=body, meta=meta,
        )
        try:
            with open(self.path, 'a', encoding='utf-8') as fh:
                fh.write(out.to_json() + '\n')
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except Exception:
                    pass
        except Exception as exc:
            raise RelayWriteError('写入日志失败:%r' % exc)
        self._msgs.append(out)
        self._by_id[out.id] = out
        self._stat = self._file_stat()
        # ★ 记账唯一入口(只算可计费行;L2 投影行标 billable=False)
        if meta.get('billable', True) and 'tokens' in meta:
            self.tokens += int(meta.get('tokens') or 0)
        if 'cost_micro' in meta and meta.get('billable', True):
            self.cost_micro += int(meta.get('cost_micro') or 0)
        elif out.kind != 'system' and meta.get('billable', True):
            self.warnings.append('条目 %s 缺 cost_micro，按 0 计并留痕' % out.id)
        tno = int(meta.get('turn_no') or 0)
        if tno > self.turn_no:
            self.turn_no = tno
        return out

    def deliver(self, msg):
        """投递层:幂等(同 id 二次投递 → False,不抛)。"""
        try:
            self.append(msg)
            return True
        except RelayDuplicateId:
            return False

    # ------------------------------------------------------------ 投影(读接口,自动重载)
    def _layer_want(self, layer: str) -> str:
        return {'L1': 'human', 'L2': 'meta', 'L3': 'debug'}.get(layer, 'human')

    def inbox(self, agent: str, *, layer: str = 'L1'):
        """可见于该 agent 的消息:广播 + 定向包含它(**含它自己发的** -- 镜像即真实对话流)。"""
        self._maybe_reload()
        want = self._layer_want(layer)
        return [m for m in self._msgs
                if m.visibility == want and (not m.recipients or agent in m.recipients)]

    def view(self, channel: str, *, layer: str = 'L1'):
        self._maybe_reload()
        want = self._layer_want(layer)
        return [m for m in self._msgs if m.channel == channel and m.visibility == want]

    def replay(self, *, to_seq: Optional[int] = None):
        self._maybe_reload()
        seqs = [m for m in self._msgs if to_seq is None or m.seq <= to_seq]
        return sorted(seqs, key=lambda m: m.seq)

    def cost_total(self) -> int:
        self._maybe_reload()
        return int(self.cost_micro)

    def token_total(self) -> int:
        self._maybe_reload()
        return int(self.tokens)

    # 告警分级（供界面用）：**严重告警**才应该打扰人；“缺 cost_micro”属于告知级 ✓
    _INFO_MARK = '缺 cost_micro'

    def alerts(self):
        """只返回**严重**告警（拒绝/失败/截断/重复等）；告知级不进这里。"""
        return [w for w in self.warnings if RelayLog._INFO_MARK not in w]

    def snapshot(self) -> dict:
        return {
            'turn_no': self.turn_no, 'cost_micro': self.cost_micro, 'tokens': self.tokens,
            'interrupted': self.interrupted, 'concluded': self.concluded,
            'stopped': self.stopped, 'stop_reason': self.stop_reason,
            'warnings': list(self.warnings), 'alerts': self.alerts(), 'seq': self._seq,
            'issue': asdict(self.issue) if self.issue else None,
        }

    # ------------------------------------------------------------ 人类交互
    def _next_id(self, prefix: str) -> str:
        return '%s-%d' % (prefix, self._seq + 1)

    def interrupt(self, body: str):
        """人类插队:**立即进入暂停**(不再有新回合);绝不自动恢复。"""
        msg = self.append({
            'id': self._next_id('human'), 'channel': self._use_current_issue_channel,
            'sender': 'human:owner', 'recipients': [], 'kind': 'speak',
            'visibility': 'human', 'body': body,
            'meta': {'priority': 'highest', 'interrupt': True},
        })
        self.interrupted = True
        return msg

    def resume(self, text: str) -> bool:
        """仅显式"继续"才恢复;其余话语不得视为继续(N2)。(恢复也写日志 → 状态可回放)"""
        if (text or '').strip().lower() not in {w.lower() for w in RESUME_WORDS}:
            return False
        if not self.interrupted:
            return False
        self.append({
            'id': self._next_id('resume'), 'channel': self._use_current_issue_channel,
            'sender': 'human:owner', 'recipients': [], 'kind': 'system', 'visibility': 'human',
            'body': '[已恢复]人类显式"继续",轮转恢复(回合计数不重置)。',
            'meta': {'resumed': True, 'billable': False},
        })
        self.interrupted = False
        return True

    def conclude(self, reason: str = 'converged'):
        """收束结论(kind=system,幂等)。返回新写入的 Msg;已收束则返回 None。"""
        if self.concluded:
            return None
        self.concluded = True
        self.stopped = True
        self.stop_reason = reason or 'converged'
        body = ('[收敛]停止条件:%s。结论:本议题在此收束。\n'
                '@人类 请决定是否继续或更换议题。' % self.stop_reason)
        msg = self.append({
            'id': self._next_id('concl'), 'channel': self._use_current_issue_channel,
            'sender': 'system', 'recipients': [], 'kind': 'system', 'visibility': 'human',
            'body': body, 'meta': {'reason': self.stop_reason, 'notice_human': True,
                                   'arbitrate': True},
        })
        self._notice_sent = True
        return msg

    # ------------------------------------------------------------ 回合推进
    def _elapsed_ms(self) -> int:
        if self._started_ts is None:
            return 0
        return max(0, self.clock() - self._started_ts)

    def _check_limits(self):
        """四道上限(`>=` 语义,只在回合边界调用)。"""
        if self.limits['max_turns'] and self.turn_no >= int(self.limits['max_turns']):
            return 'turn_limit'
        if self.limits['time_limit_ms'] and self._elapsed_ms() >= int(self.limits['time_limit_ms']):
            return 'time_limit'
        if self.limits['max_tokens'] and self.tokens >= int(self.limits['max_tokens']):
            return 'token_limit'
        if self.limits['max_cost_micro'] and self.cost_micro >= int(self.limits['max_cost_micro']):
            return 'cost_limit'
        return ''

    def _notice_pause_if_needed(self):
        """暂停提醒:最多一次(绝不自动恢复)。"""
        if not self._notice_sent:
            self._notice_sent = True
            self.append({
                'id': self._next_id('notice'), 'channel': self._use_current_issue_channel,
                'sender': 'system', 'recipients': [], 'kind': 'system', 'visibility': 'human',
                'body': '[已暂停]检测到人类消息:暂停自动轮转,等待人类明确说"继续"'
                        '(不会自动恢复)。\n@人类',
                'meta': {'notice_human': True, 'interrupt': True},
            })

    def step(self) -> StepResult:
        # 0) 已停/已收束:不再推进、不再发请求
        if self.stopped:
            return StepResult(ok=False, stopped=True, reason=self.stop_reason,
                              turn_no=self.turn_no, notice_human=self._notice_sent,
                              cost_micro=self.cost_micro, provider_calls=0)

        # 1) 已被人类插队 → 暂停(不推进、零请求、不自动恢复)
        if self.interrupted:
            self._notice_pause_if_needed()
            return StepResult(ok=False, stopped=True, reason='interrupted',
                              turn_no=self.turn_no, notice_human=True,
                              cost_micro=self.cost_micro, provider_calls=0)

        # 2) 回合边界:四道上限
        hit = self._check_limits()
        if hit:
            self.conclude(hit)
            return StepResult(ok=True, stopped=True, reason=hit, turn_no=self.turn_no,
                              notice_human=True, cost_micro=0, provider_calls=0)

        if self.issue is None:
            return StepResult(ok=False, stopped=False, reason='no_issue', turn_no=self.turn_no)
        if self.provider is None:
            return StepResult(ok=False, stopped=False, reason='no_provider', turn_no=self.turn_no)

        # 3) 调 provider(外部注入;失败计重试、不计回合)
        provider_calls = 0
        retry_max = int(self.limits['retry_max'])
        last = self._msgs[-1] if self._msgs else Msg(
            id='seed', seq=0, ts=self.clock(), channel=self._use_current_issue_channel,
            sender='human:owner', recipients=[], kind='system', visibility='human',
            body=getattr(self.issue, 'title', '') or '', meta={})
        reply = None
        for attempt in range(retry_max + 1):
            provider_calls += 1
            try:
                reply = self.provider(last, self.issue)
                break
            except Exception as exc:
                if attempt >= retry_max:
                    self.warnings.append('provider 连续失败 %d 次:%r' % (provider_calls, exc))
                    self.conclude('provider_failed')
                    return StepResult(ok=True, stopped=True, reason='provider_failed',
                                      turn_no=self.turn_no, notice_human=True,
                                      cost_micro=0, provider_calls=provider_calls)

        # 4) 记消息(记账在 append 里自动完成)
        tokens = int(getattr(reply, 'tokens', 0) or 0)
        cost = int(getattr(reply, 'cost_micro', 0) or 0)
        body = getattr(reply, 'body', '') or ''
        rmeta = dict(getattr(reply, 'meta', {}) or {})
        _tno = self.turn_no + 1               # ★ 回合号只算一次(两个 append 共用)
        self.append({
            'id': self._next_id('turn'), 'channel': self._use_current_issue_channel,
            'sender': 'agent:worker', 'recipients': [], 'kind': 'speak',
            'visibility': 'human', 'body': body,
            'meta': {'turn_no': _tno, 'tokens': tokens, 'cost_micro': cost,
                     'model': rmeta.get('model', ''), 'latency_ms': rmeta.get('latency_ms', 0)},
        })
        self.append({
            'id': self._next_id('meta'), 'channel': self._use_current_issue_channel,
            'sender': 'system', 'recipients': ['agent:worker'], 'kind': 'reply',
            'visibility': 'meta',
            'body': '投递:system → agent:worker(回合 %d)' % _tno,
            'meta': {'turn_no': _tno, 'tokens': tokens, 'cost_micro': cost,
                     'billable': False},   # 投影行:供 L2 展示,不参与累计
        })

        # 5) 结构化"主张签名"收敛检测(新数字/新实体一律算有新信息)
        sig = _signature(body)
        if not (sig - self._prev_sig):
            self._no_new_streak += 1
        else:
            self._no_new_streak = 0
        self._prev_sig |= sig
        if self._no_new_streak >= int(self.limits['converge_no_new']):
            self.conclude('converged')
            return StepResult(ok=True, stopped=True, reason='converged', turn_no=self.turn_no,
                              notice_human=True, cost_micro=cost, provider_calls=provider_calls)

        # 6) 本回合结束后再查一次上限(到顶即停,绝不进入下一回合)
        hit = self._check_limits()
        if hit:
            self.conclude(hit)
            return StepResult(ok=True, stopped=True, reason=hit, turn_no=self.turn_no,
                              notice_human=True, cost_micro=cost, provider_calls=provider_calls)

        return StepResult(ok=True, stopped=False, reason='', turn_no=self.turn_no,
                          notice_human=False, cost_micro=cost, provider_calls=provider_calls)
