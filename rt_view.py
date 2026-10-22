# -*- coding: utf-8 -*-
"""rt_view —— 圆桌**只读导出面**（接线批次 C1 ✓）

定位（Owner 2026-09-26 15:32 批「接」✓ · 微信侧委托 C1 ✓）：
  给**界面侧**提供**数据/接口** ✓ —— 本方**不做视觉** ✗（双视图界面实现归界面侧 ✓）

四条出口（全部**只读** ✗ 不产新行 ✓ 不出网 ✗ 不写盘 ✗）：
  ① ``hall_cards()``    大厅视图数据：L1 摘要流 ✓ 每轮一条卡 ✓（含 `round_id`/`turn_no`/`ptr` ✓）
  ② ``channel_view()``  通道视图数据：L2 工作集 ✓ 五优先级构成 ✓ + **trace** ✓
  ③ ``read_original()`` 原文按需读取 ✓ ⭐ **归属隔离在数据层强制** ✓（跨角色默认拒 ✗ 显式索取才给 ✓ 记审计 ✓）
  ④ ``budget_display()``预算展示口径 ✓：上限 6000 / 提示线 4000 ✓ 恒标**估算** ✓ + ⭐ `near_limit` ✓

硬约束自查：零新依赖 ✓（仅 stdlib + 既有模块）｜ 只读 ✓｜ 不改既有产品行为 ✗
"""
from __future__ import annotations

from rt_store import MissingOriginal, make_ptr, parse_ptr

import rt_assembler as _asm

# 展示口径（⭐ 单一来源 = `rt_assembler` 常量 ✓ 不另立数字 ✗）
BUDGET_LIMIT = _asm.BUDGET_DEFAULT      # 上限 6000 ✓
NEAR_LIMIT_LINE = _asm.NEAR_LIMIT       # 提示线 4000 ✓
ESTIMATE_NOTE = '估算（字符 ÷2 保守估，非真实 token 计数）'
CROSS_NEED_EXPLICIT = '跨角色读取需显式索取'


def _audit(audit, rec):
    """审计出口：调用方可注入**可调用**或带 `write`/`record` 的对象 ✓；不注入则静默 ✓（不落盘 ✗）"""
    if audit is None:
        return
    if callable(audit):
        audit(dict(rec))
        return
    for name in ('write', 'record', 'log'):
        fn = getattr(audit, name, None)
        if callable(fn):
            fn(dict(rec))
            return
    raise TypeError('audit 需为可调用或含 write/record/log 的对象 ✗')


# ── ① 大厅视图数据（只读 ✓）─────────────────────────────────────────
def hall_cards(*, store, role=None, day=None, limit=None):
    """L1 摘要流 → **每轮一条卡** ✓（含 `round_id`/`turn_no`/指针 ✓）· ⭐ **只读** ✗ 不产新行 ✓

    归属：`role` 不传 = 全部角色可见项（大厅语义 ✓ 仅含 L1 **摘要** ✓ 原文走 ③ ✓）
    """
    rows = store.summaries(role=role, day=day, limit=limit)
    cards = []
    for r in rows:
        ptr = r.get('ptr')
        if not ptr:
            continue
        info = parse_ptr(ptr)
        cards.append({
            'ptr': ptr,
            'role': info['role'],
            'day': info['day'],
            'seq': info['seq'],
            'round_id': str(r.get('round_id') or ''),
            'turn_no': int(r.get('turn_no') or 0),
            'kind': str(r.get('kind') or ''),
            'summary': str(r.get('summary') or ''),
            'ts': str(r.get('ts') or ''),
            'expired': bool(r.get('expired')),
        })
    return cards


# ── ② 通道视图数据（只读 ✓）─────────────────────────────────────────
def channel_view(*, role, my_recent=(), hall_summaries=(), mentions=(), related=(),
                 cross_requested=(), k=None, budget=None):
    """L2 工作集 → 通道视图数据 ✓（五优先级 ✓ + trace ✓ + 预算口径 ✓）

    ⭐ **归属隔离**：`my_recent` 内他人条目由 `rt_assembler` 判 ✗（默认不装 ✓）；跨角色私文需
    `cross_requested` **显式索取** ✓（否则 trace 记 `需显式索取` ✓）
    """
    kw = {}
    if k is not None:
        kw['k'] = int(k)
    if budget is not None:
        kw['budget'] = int(budget)
    out = _asm.build(role=role, my_recent=tuple(my_recent), hall_summaries=tuple(hall_summaries),
                     mentions=tuple(mentions), related=tuple(related),
                     cross_requested=tuple(cross_requested), **kw)
    out = dict(out)
    out['view'] = 'channel'
    out['role'] = role
    out['isolation'] = {
        'rule': '通道视图只显示该角色可见项；他人私文需显式索取',
        'cross_requested': [str(p) for p in cross_requested],
    }
    out['budget_display'] = budget_display(out.get('budget') or {})
    return out


# ── ③ 原文按需读取（只读 ✓ + 隔离强制 ✓ + 审计 ✓）────────────────────
def read_original(*, requester, store, ptr=None, role=None, day=None, seq=None,
                  explicit=False, audit=None):
    """按需取 L0 原文 ✓ **只读** ✗

    - 同角色 → 直接给 ✓
    - ⭐ 跨角色 → **默认拒** ✗（`ok=False, denied=True`）+ 审计 `cross_read_denied` ✓
    - `explicit=True`（显式索取 ✓）→ 给 ✓ + 审计 `cross_read_allowed` ✓
    - 已滚/缺失 → `ok=False` + **原因** ✓（不抛 ✗ 不静默 ✓）+ 审计 `original_missing` ✓
    """
    if ptr:
        info = parse_ptr(ptr)
        role, day, seq = info['role'], info['day'], info['seq']
    target = make_ptr(role, day, seq)
    cross = str(role) != str(requester)
    if cross and not explicit:
        _audit(audit, {'kind': 'cross_read_denied', 'requester': requester, 'target': target,
                       'reason': CROSS_NEED_EXPLICIT})
        return {'ok': False, 'ptr': target, 'denied': True, 'cross': True,
                'reason': CROSS_NEED_EXPLICIT}
    try:
        rec = store.read(role, day, seq)
    except MissingOriginal as e:
        _audit(audit, {'kind': 'original_missing', 'requester': requester, 'target': target,
                       'reason': str(e)})
        return {'ok': False, 'ptr': target, 'denied': False, 'cross': cross,
                'reason': str(e), 'expired': _safe_expired(store, target)}
    if cross:
        _audit(audit, {'kind': 'cross_read_allowed', 'requester': requester, 'target': target,
                       'explicit': True})
    return {'ok': True, 'ptr': target, 'denied': False, 'cross': cross, 'rec': rec}


def _safe_expired(store, ptr):
    try:
        return bool(store.is_expired(ptr))
    except Exception:
        return False


# ── ④ 预算展示口径（⭐ `near_limit` 随本批落地 ✓）────────────────────
def budget_display(budget=None):
    """把 `rt_assembler` 的预算结构翻译成**展示口径** ✓

    - 上限 **6000** ✓ / 提示线 **4000** ✓（取自常量 ✓ 不另立 ✗）
    - ⭐ `near_limit` 恒按 `4000 ≤ used < 6000` ✓（`≥6000` 走拦截路径 ✗ 与提示线**不混用** ✗）
    - ⭐ `estimated=True` + `note` 恒含"估算" ✓（界面必须标 ✓）
    """
    b = dict(budget or {})
    limit = int(b.get('limit') or BUDGET_LIMIT)
    used = int(b.get('used') or 0)
    near = b.get('near_limit')
    if near is None:
        near = bool(NEAR_LIMIT_LINE <= used < limit)
    return {
        'limit': limit,
        'near_limit_line': NEAR_LIMIT_LINE,
        'used': used,
        'unit': b.get('unit') or 'token(估)',
        'estimated': True,
        'note': ESTIMATE_NOTE,
        'near_limit': bool(near),
    }
