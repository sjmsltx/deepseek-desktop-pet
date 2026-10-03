# -*- coding: utf-8 -*-
"""rt_remote.py — 遥控 · **B-乙 v1**（消费器 + 命令解析 / 白名单 / 派发）

依据：冻结稿《B乙-v1-用例设计-冻结版v1-20260926.md》（微信侧 ✓ Owner 18:44 批「就做 B-乙」✓）

形态（三个纯函数 + 一个轮询件）：
  ``parse_command(text)``   文本 → 结构化命令        ⭐ **纯函数** ✗ 无 IO / 无网
  ``is_allowed(cmd)``       白名单判定              ⭐ **纯函数** ✓ **白名单枚举** ✓ 不用黑名单 ✗
  ``dispatch(cmd, ...)``    执行只读 / 投递          ⭐ **只许调 `rt_view` / `rt_action`** ✗ ；**必写审计** ✓
  ``RemoteConsumer``        轮询消费 + 记 `last_seq`  ⭐ **幂等** ✓ `last_seq` **只前进** ✓ 失败**不静默** ✗

硬约束（红线 ✗ 违反即不合格）：
  ⛔ 不出网 ✗（本模块只用标准库 ✓ 无 `urllib/requests/socket/http` ✓）
  ⛔ 遥控路径**禁** `store.append` ✗（只能产草稿 / 只读 / 投递 ✓）
  ⛔ `确认`/`否决`/`投喂` **永禁** ✗；`step` 默认关 ✗
  ⛔ 不改既有产品行为 ✗（本模块**只新增** ✓ 由调用方选择是否起用 ✓）
  ⛔ 静默失败 ✗（一律 `pet_log` + 回话 ✓）

⚠️ 诚实项（**不得对外宣称"零中转"** ✗）：指令**经过微信** ✗ + 自动档**会过一次模型** ✗（已告知 Owner ✓）
"""
from __future__ import annotations

import json
import os
import re

import rt_action
import rt_view

# ── 白名单（**枚举** ✓ 不用黑名单 ✗）──────────────────────────────
KINDS = ('状态', '大厅', '通道', '原文', '投递')
ALIASES = {'status': '状态', 'state': '状态', 'hall': '大厅', 'channel': '通道',
           'read': '原文', 'original': '原文', 'deliver': '投递', 'send': '投递'}
# ⛔ 永禁 / v1 不进白名单（即使命令里写死也必须拒 ✗）
FORBIDDEN_WORDS = ('确认', 'confirm', 'approve', '否决', 'reject', 'deny',
                   '投喂', 'feed', 'step', '步进', '推一回合')

HALL_DEFAULT = 5
HALL_MAX = 20
MAX_TEXT = 1000
DEFAULT_INTERVAL_MS = 2000
AUDIT_KIND = 'remote'


class CommandError(Exception):
    """命令层错误（含明报文案 ✓）"""


def _clean(text):
    """去首尾空白 + 去控制字符（**保留 emoji** ✓ 不崩 ✓）"""
    s = '' if text is None else str(text)
    s = ''.join(ch for ch in s if ch >= ' ' or ch in '\t')
    return s.strip()


def _err(why, *, kind=None, forbidden=False):
    return {'ok': False, 'kind': kind, 'error': str(why), 'forbidden': bool(forbidden),
            'args': {}, 'text': ''}


# ── ① 纯函数：解析 ────────────────────────────────────────────────
def parse_command(text):
    """文本 → `{'ok','kind','args','error','forbidden','text'}` ✓ ⭐ **纯函数** ✗ 无 IO / 无网

    §2 语法（冻结 ✓）：`状态`/`status` · `大厅 [N]`/`hall [N]`（默认 5 ✓ **上限 20 钳制** ✓）·
    `通道 <角色>`/`channel <role>` · `原文 <角色> <日期> <序号>` · `投递 <轮次id|角色> <内容>`/`deliver ...`
    ⭐ 大小写不敏感 ✓ 中英别名等价 ✓ **一次只执行一条** ✗（不拆分 ✓）
    """
    s = _clean(text)
    if not s:
        return _err('空命令（请发「状态」查看可用命令）')
    if len(s) > MAX_TEXT:
        return _err('命令过长（>%d 字）' % MAX_TEXT)
    parts = s.split()
    head = parts[0]
    kind = ALIASES.get(head.lower()) or (head if head in KINDS else None)
    if kind is None:
        low = s.lower()
        if any(w in s or w in low for w in FORBIDDEN_WORDS):
            return _err('该动作**被禁止** ✗（确认/否决/投喂/step 均不在白名单内）', kind=None, forbidden=True)
        return _err('未知命令 ✗（可用：状态｜大厅 [N]｜通道 <角色>｜原文 <角色> <日期> <序号>｜投递 <轮次id|角色> <内容>）')
    rest = parts[1:]
    if kind == '状态':
        return {'ok': True, 'kind': kind, 'args': {}, 'error': '', 'forbidden': False, 'text': s}
    if kind == '大厅':
        n = HALL_DEFAULT
        if rest:
            if not rest[0].isdigit():
                return _err('「大厅」参数须为正整数（收到：%s）' % rest[0], kind=kind)
            n = int(rest[0])
        n = max(1, min(int(n), HALL_MAX))          # ⭐ 钳到上限 20 ✓（不报错也不无限 ✓）
        return {'ok': True, 'kind': kind, 'args': {'limit': n}, 'error': '', 'forbidden': False, 'text': s}
    if kind == '通道':
        if not rest:
            return _err('「通道」缺角色（用法：通道 <角色>）', kind=kind)
        return {'ok': True, 'kind': kind, 'args': {'role': rest[0]}, 'error': '',
                'forbidden': False, 'text': s}
    if kind == '原文':
        if len(rest) < 3:
            return _err('「原文」缺参数（用法：原文 <角色> <日期> <序号>）', kind=kind)
        role, day, seq = rest[0], rest[1], rest[2]
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
            return _err('「原文」日期须为 YYYY-MM-DD（收到：%s）' % day, kind=kind)
        if not seq.isdigit():
            return _err('「原文」序号须为数字（收到：%s）' % seq, kind=kind)
        return {'ok': True, 'kind': kind, 'args': {'role': role, 'day': day, 'seq': int(seq)},
                'error': '', 'forbidden': False, 'text': s}
    # 投递 <轮次id|角色> <内容>
    if len(rest) < 2:
        return _err('「投递」缺参数（用法：投递 <轮次id|角色> <内容>）', kind=kind)
    target, content = rest[0], ' '.join(rest[1:])
    bits = target.split('|')
    if len(bits) != 2 or not bits[0].strip() or not bits[1].strip():
        return _err('「投递」目标须为「轮次id|角色」（收到：%s）' % target, kind=kind)
    return {'ok': True, 'kind': kind,
            'args': {'round_id': bits[0].strip(), 'role': bits[1].strip(), 'content': content},
            'error': '', 'forbidden': False, 'text': s}


# ── ② 纯函数：白名单 ──────────────────────────────────────────────
def is_allowed(cmd):
    """⭐ **纯函数** ✓：命令是否在**白名单**内 ✓（枚举 ✓ 非黑名单 ✗）→ `(bool, reason)` ✓"""
    if not isinstance(cmd, dict) or not cmd.get('ok'):
        return False, (cmd or {}).get('error') or '非法命令'
    kind = cmd.get('kind')
    if kind not in KINDS:
        return False, '不在白名单：%s' % kind
    return True, ''


# ── ③ 派发（只调 rt_view / rt_action ✓ + 必写审计 ✓）────────────────
def _audit_write(audit, *, action, role='', detail='', allowed=True, extra=None):
    """审计出口 ✓（默认 `governance.log_event` ✓ 可注入替身 ✓ 便于单测**不污染真审计** ✗）"""
    if audit is None:
        import governance
        fn = governance.log_event
    elif callable(audit):
        fn = audit
    else:
        raise TypeError('audit 需为可调用对象 ✗')
    try:
        fn(AUDIT_KIND, str(role or ''), str(action), str(detail or ''), bool(allowed), extra or {})
    except TypeError:
        fn(AUDIT_KIND, str(role or ''), str(action), str(detail or ''))


def dispatch(cmd, *, store=None, relay=None, gate=None, audit=None, requester='owner',
             view=None, action=None, budget=None):
    """执行一条命令 ✓ 返回**回话文本 + 结构化结果** ✓

    ⭐ **只许调 `rt_view` / `rt_action`** ✗（不得直连产品动作 ✗ 禁 `store.append` ✗）；**必写审计** ✓
    """
    ok, why = is_allowed(cmd)
    if not ok:
        _audit_write(audit, action='reject', role=requester, detail=why, allowed=False)
        return {'ok': False, 'reply': '⛔ %s' % why, 'data': None}
    kind = cmd['kind']
    a = cmd['args']
    v = view or rt_view
    act = action or rt_action
    try:
        if kind == '状态':
            cards = v.hall_cards(store=store, limit=HALL_DEFAULT) if store is not None else []
            bd = v.budget_display(budget or {})
            pend = act.pending_for_ui(gate=gate) if gate is not None else []
            data = {'hall_count': len(cards), 'budget': bd, 'pending': len(pend)}
            reply = ('📋 状态：大厅 %d 条 ｜ 预算 used %s/%s %s ｜ 待确认 %d 条'
                     % (data['hall_count'], bd['used'], bd['limit'],
                        '（已达提示线 ⚠️）' if bd['near_limit'] else '', data['pending']))
        elif kind == '大厅':
            if store is None:
                raise CommandError('未接入存储（store 缺失）')
            cards = v.hall_cards(store=store, limit=a['limit'])
            data = cards
            lines = ['🗂 大厅最近 %d 条：' % len(cards)]
            for c in cards:
                lines.append('· [%s] %s（%s）' % (c.get('ptr', ''), (c.get('summary') or '')[:80],
                                                 c.get('round_id') or '—'))
            reply = '\n'.join(lines) if cards else '🗂 大厅暂无摘要'
        elif kind == '通道':
            out = v.channel_view(role=a['role'])
            kept = [t for t in (out.get('trace') or []) if t.get('kept')]
            data = {'messages': out.get('messages'), 'trace_kept': kept,
                    'budget_display': out.get('budget_display')}
            reply = ('🧵 通道（%s）：装入 %d 条 ｜ 预算 used %s/%s'
                     % (a['role'], len(out.get('messages') or []),
                        (out.get('budget_display') or {}).get('used'),
                        (out.get('budget_display') or {}).get('limit')))
        elif kind == '原文':
            if store is None:
                raise CommandError('未接入存储（store 缺失）')
            got = v.read_original(requester=requester, store=store, role=a['role'],
                                  day=a['day'], seq=a['seq'], explicit=False, audit=audit)
            data = got
            if got.get('ok'):
                reply = '📄 原文（%s）已返回 ✓' % got.get('ptr')
            else:
                reply = '⛔ 拒绝或失败：%s' % got.get('reason')
        else:                                    # 投递
            if relay is None:
                raise CommandError('未接入通道（relay 缺失）')
            bg = act.budget_gate(estimate=0.0, audit=audit, role=a['role'],
                                 round_id=a['round_id'], check=budget)
            if not bg.get('ok'):
                data = bg
                reply = '⛔ 额度拒绝 ✗（已写审计）：%s' % bg.get('reason')
            else:
                out = act.deliver(relay=relay, round_id=a['round_id'], role=a['role'],
                                  content=a['content'])
                data = out
                reply = ('📮 投递 %s ｜ state=%s%s'
                         % (out.get('idem_key'), out.get('state'),
                            (' ｜ 原因：%s' % out['reason']) if out.get('reason') else ''))
    except Exception as exc:                      # ⭐ 不静默 ✗
        _audit_write(audit, action=kind, role=requester, detail='异常：%r' % (exc,), allowed=False)
        _log_warn('dispatch 失败（%s）：%r' % (kind, exc))
        return {'ok': False, 'reply': '⛔ 执行失败 ✗：%s' % exc, 'data': None}
    _audit_write(audit, action=kind, role=requester, detail=str(a)[:300])
    return {'ok': True, 'reply': reply, 'data': data}


def _log_warn(msg):
    """⚠️ 不静默 ✗：走 `pet_log` ✓（S2 已给注入入口 ✓；失败也不拖垮主程序 ✓）"""
    try:
        import pet_log
        pet_log.get_logger('remote').warning(msg)
    except Exception:
        pass


def build_consumer_from_config(cfg, *, base_dir, emit=None, agent='owner', requester='owner',
                               interval_ms=None):
    """⭐ **按配置装配消费器** ✓ —— ⛔ **开关关着时返回 `None` 且不构造任何东西** ✗

    配置键：``remote_control``（**默认 `False`** ✓ 与既有 `active_chat` 同一惯用法 ✓）
    → ⭐ **关着时行为与接线前完全一致** ✗（由用例钉住 ✓）
    开着时：在 `base_dir` 下建 L0/L1 存储 + 投递通道 + 人工确认闸门（带审计落盘 ✓）→ 返回 `RemoteConsumer` ✓
    ⚠️ 审计一律走 `governance.log_event` ✓；⛔ 本函数**既不写 L0 也不投递** ✗（只装配 ✓）
    """
    if not isinstance(cfg, dict) or not bool(cfg.get('remote_control', False)):
        return None                              # ⭐ 默认关：什么都不做 ✓
    import os as _os

    import relay_log
    import rt_relay
    import rt_store

    base = str(base_dir)
    store = rt_store.Store(_os.path.join(base, 'rt'))
    relay = rt_relay.Relay(_os.path.join(base, 'remote'))
    gate = rt_action.make_gate(store=store, base_dir=_os.path.join(base, 'remote'), relay=relay)
    # ⭐ 通道注入（2026-09-26 端到端小批补 ✓）：消费器必须能真读到通道 ✓
    ch = str(cfg.get('remote_channel') or _os.path.join(base, 'logs', 'remote_channel.jsonl'))
    d = _os.path.dirname(ch)
    if d:
        _os.makedirs(d, exist_ok=True)
    # ⭐ 门槛第 1 件（Owner 2026-10-02 批）：自定义圆桌额度（未配置 = 不覆盖默认 = 不限 ✓）
    relay_log_obj = relay_log.RelayLog(ch, limits=relay_log.load_limits())
    return RemoteConsumer(
        relay_log_obj,
        interval_ms=int(interval_ms or cfg.get('remote_interval_ms') or DEFAULT_INTERVAL_MS),
        store=store, relay=relay, gate=gate, audit=None,
        requester=str(cfg.get('remote_requester') or requester),
        state_path=_os.path.join(base, 'logs', 'remote_state.json'),
        agent=str(cfg.get('remote_agent') or agent), emit=emit)


# ── ④ 消费器（轮询 ✓ last_seq 只前进 ✓ 幂等 ✓ 失败不静默 ✓）────────
class RemoteConsumer:
    """桌宠侧**消费器** ✓：轮询 `relay_log` 收件箱 → 解析 → 白名单 → 派发 → 写回执 ✓

    ⭐ 硬性：`last_seq` **只前进** ✓（不倒退 ✗）｜ **同 id 只执行一次** ✓｜**重启不重复消费** ✓（状态落盘 ✓）
    ｜ **失败不静默** ✗｜`interval_ms` **可配** ✓（默认 **2000** ✓）
    ⭐ **回 UI 走注入的 `emit`** ✓（应用侧传 `ui_call_signal.emit` ✓ → 本模块**不引 Qt** ✗）
    ⚠️ 本类**不改既有产品行为** ✗ —— 是否起用由应用侧决定 ✓
    """

    def __init__(self, relay_log=None, *, interval_ms=DEFAULT_INTERVAL_MS, dispatch_fn=None,
                 store=None, relay=None, gate=None, audit=None, requester='owner',
                 state_path='', agent='owner', emit=None):
        self.log = relay_log
        self.interval_ms = max(200, int(interval_ms or DEFAULT_INTERVAL_MS))
        self.dispatch_fn = dispatch_fn or dispatch
        self.store = store
        self.relay = relay
        self.gate = gate
        self.audit = audit
        self.requester = requester
        self.state_path = str(state_path or '')
        self.agent = str(agent or 'owner')
        self.emit = emit
        self.last_seq = 0
        self._seen = []                      # 已消费命令 id（有界 ✓）
        self._load_state()

    # ---- 状态落盘（重启不重复消费 ✓）----
    def _load_state(self):
        if not self.state_path or not os.path.isfile(self.state_path):
            return
        try:
            with open(self.state_path, encoding='utf-8') as f:
                d = json.load(f)
            self.last_seq = int(d.get('last_seq') or 0)
            self._seen = [str(x) for x in (d.get('seen') or [])][-500:]
        except Exception as exc:
            _log_warn('消费器状态读失败（%r）→ 以 0 起步 ✓' % (exc,))

    def _save_state(self):
        if not self.state_path:
            return
        try:
            d = os.path.dirname(self.state_path)
            if d:
                os.makedirs(d, exist_ok=True)
            tmp = self.state_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump({'last_seq': int(self.last_seq), 'seen': self._seen[-500:]}, f)
            os.replace(tmp, self.state_path)
        except Exception as exc:
            _log_warn('消费器状态写失败（%r）' % (exc,))

    # ---- 轮询一次 ----
    def poll_once(self):
        """消费一次 → 回执列表 ✓（**幂等** ✓ **只前进** ✓ **失败不静默** ✓）"""
        out = []
        if self.log is None:
            return out
        try:
            msgs = list(self.log.inbox(self.agent, layer='L1'))
        except Exception as exc:             # ⭐ 通道损坏/被删 → 不崩 ✓ 记警 ✓
            _log_warn('读收件箱失败（%r）→ 本轮跳过 ✓' % (exc,))
            return out
        for m in msgs:
            mid = str(getattr(m, 'id', '') or '')
            seq = int(getattr(m, 'seq', 0) or 0)
            if seq <= self.last_seq or (mid and mid in self._seen):
                continue                     # ⭐ 幂等：同 id / 旧 seq 一律跳过 ✓
            text = getattr(m, 'body', '')
            cmd = parse_command(text)
            try:
                res = self.dispatch_fn(cmd, store=self.store, relay=self.relay, gate=self.gate,
                                       audit=self.audit, requester=self.requester)
            except Exception as exc:          # ⭐ 派发异常**不静默** ✗ 也不中断消费 ✓
                _log_warn('派发异常（seq=%s）：%r' % (seq, exc))
                res = {'ok': False, 'reply': '⛔ 执行失败 ✗：%s' % exc, 'data': None}
            res = dict(res or {})
            res['msg_id'] = mid
            res['seq'] = seq
            res['state'] = 'done' if res.get('ok') else 'failed'
            if not res.get('ok'):
                _log_warn('遥控命令未成功（seq=%s）：%s' % (seq, res.get('reply')))
            self.last_seq = max(self.last_seq, seq)      # ⭐ 只前进 ✓
            if mid:
                self._seen.append(mid)
                self._seen = self._seen[-500:]
            out.append(res)
            if callable(self.emit):
                try:
                    self.emit(res)                   # ⭐ 回 UI 走注入 emit ✓
                except Exception as exc:
                    _log_warn('emit 失败（%r）' % (exc,))
        if out:
            self._save_state()
        return out
