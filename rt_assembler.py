# -*- coding: utf-8 -*-
"""rt_assembler.py — L2 工作集装配（第 3 批 · B3）

设计依据：《设计 v1.1》§3（五优先级 / 预算 / trace / 归属隔离）+ §F（上限 6000 + 提示线 4000）

边界（务必遵守 ✗）：
  - **纯函数** ✓：数据由调用方传入 ✗ 不读文件 ✗ 不出网 ✗（AST 护栏）
  - ①@点名/被引用、②本角色近段 → ⭐ **永不砍** ✗
  - 裁剪顺序：**先砍 ④相关性 → 再砍 ③时效窗口（最旧优先）** ✗
  - **归属隔离**：他人私聊全文**默认不装** ✗（需显式索取 ✓ 并标 `deny 需显式索取` ✓）
  - 预算：字符 **÷2** 保守估 ✓ 输出标 `estimated: true` ✓；**上限 6000 / 提示线 4000** ✓
"""
from __future__ import annotations

DIVISOR = 2                       # 中文保守估：字符 ÷2 ✓（宁可高估 ✗）
BUDGET_DEFAULT = 6000             # 上限（估）✓
NEAR_LIMIT = 4000                 # 提示线 ✓
K_DEFAULT = 8                     # 本角色近段条数 ✓
K_TIGHT = 4                       # 预算吃紧时的降级值 ✓
PRIORITY_LABELS = {1: '@点名/被引用（优先级①）', 2: '本角色近段（优先级②）',
                   3: '时效窗口摘要（优先级③）', 4: '相关性摘要（优先级④）'}


def est_tokens(text):
    """token 估算（**保守**）：字符数 ÷ 2 ✓ 向上取整 ✓（宁可高估 ✗）"""
    n = len(str(text or ''))
    return int((n + DIVISOR - 1) // DIVISOR)


def _item(item, prio, why):
    it = dict(item or {})
    it['priority'] = int(prio)
    it['why'] = why
    it['est_tokens'] = est_tokens(it.get('text', ''))
    it.setdefault('kind', 'l1')
    return it


def build(*, role, my_recent=(), hall_summaries=(), mentions=(), related=(),
          k=K_DEFAULT, budget=BUDGET_DEFAULT, cross_requested=()):
    """装配 L2 工作集（**纯函数** ✓）

    参数：
      ``my_recent``      本角色近段（含 `role` 字段 ✓ 用于归属校验）
      ``hall_summaries`` 大厅 L1 摘要（时效窗口 ✓）
      ``mentions``       @点名/被引用（含被引用原文片段 ✓）
      ``related``        相关性命中的摘要 ✓（**最先被砍** ✗）
      ``cross_requested`` **显式索取**的他人私文 ✓（不传则一律不装 ✗）

    返回：``{'messages', 'budget', 'trace'}`` ✓
    """
    k = int(k or K_DEFAULT)
    budget = int(budget or BUDGET_DEFAULT)
    trace, kept = [], []

    # ① @点名 / 被引用 —— 永不砍 ✓
    for m in (mentions or []):
        it = _item(m, 1, PRIORITY_LABELS[1])
        kept.append(it)
        trace.append({'ptr': it.get('ptr', ''), 'why': it['why'], 'kept': True})

    # ② 本角色近段 —— 永不砍 ✓（归属校验：只收自己的 ✓）
    mine = [x for x in (my_recent or []) if str((x or {}).get('role') or role) == str(role)]
    kept_prio2 = []
    for m in mine[-k:]:
        it = _item(m, 2, PRIORITY_LABELS[2])
        kept.append(it)
        kept_prio2.append(it)
        trace.append({'ptr': it.get('ptr', ''), 'why': it['why'], 'kept': True})

    # ④ 相关性 + ③ 时效窗口（收入候选 ✓ 按 ④→③ 顺序可砍 ✗）
    cand4 = [_item(x, 4, PRIORITY_LABELS[4]) for x in (related or [])]
    cand3 = [_item(x, 3, PRIORITY_LABELS[3]) for x in (hall_summaries or [])]
    cand3.sort(key=lambda x: str(x.get('ts') or ''))          # 最旧在前 ✓ 先砍最旧 ✓
    candidates = cand4 + cand3

    # 归属隔离：他人私聊 → 默认 **deny** ✗ 需显式索取 ✓
    allowed_cross = set(str(x) for x in (cross_requested or []))
    safe = []
    for it in candidates:
        owner = str(it.get('role') or '')
        if owner and owner != str(role) and it.get('private') and it.get('ptr') not in allowed_cross:
            trace.append({'ptr': it.get('ptr', ''), 'why': '他人私聊全文', 'kept': False,
                          'drop_reason': 'deny 需显式索取'})
            continue
        safe.append(it)

    # ⑤ 预算装箱
    def total(items):
        return sum(int(i['est_tokens']) for i in items)

    # k 联动（**先判**）：①② 已超预算 → ② 从 k 降到 K_TIGHT（**必写 drop_reason** ✗ 不静默）
    if total(kept) + total(safe) > budget and len(kept_prio2) > K_TIGHT:
        extra = kept_prio2[:-K_TIGHT]              # 最旧的几条 ✓
        for it in extra:
            kept.remove(it)
            trace.append({'ptr': it.get('ptr', ''), 'why': it['why'], 'kept': False,
                          'drop_reason': 'k 降级 %d→%d（预算吃紧）' % (k, K_TIGHT)})
        kept_prio2 = kept_prio2[-K_TIGHT:]

    # 裁剪顺序：**先扔 ④ 相关性 → 再扔 ③ 时效窗口（最旧优先）** ✗；①② 永不扔 ✗
    while total(kept) + total(safe) > budget and safe:
        victim = next((i for i in reversed(safe) if i['priority'] == 4), None)
        if victim is None:
            victim = next((i for i in safe if i['priority'] == 3), None)   # 已按最旧在前 ✓
        if victim is None:
            break
        safe.remove(victim)
        trace.append({'ptr': victim.get('ptr', ''), 'why': victim['why'], 'kept': False,
                      'drop_reason': '预算裁剪'})

    messages = kept + safe
    used = total(messages)
    return {
        'messages': messages,
        'budget': {'limit': budget, 'used': used, 'estimated': True, 'unit': 'token(估)',
                   'divisor': DIVISOR, 'near_limit': bool(NEAR_LIMIT <= used < budget)},
        'trace': trace,
    }
