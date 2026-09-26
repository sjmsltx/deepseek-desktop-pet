# -*- coding: utf-8 -*-
"""rt_action —— 圆桌**动作面**（接线批次 C2a ✓ 投递 + 回执 + 额度）

定位（Owner 2026-09-26 15:32 批「接」✓ · 微信侧委托 C2 ✓ 建议先做低风险半批 ✓）：
  给**界面侧**提供**动作/回执数据** ✓ —— 本方**不做视觉** ✗

三条出口：
  ① ``deliver()``         投递一条 ✓（幂等 ✓ `sent`/`duplicate`/`failed` ✓ 失败带原因 ✓ 不静默 ✗）
  ② ``receipts_for_ui()`` **回执视图** ✓ ⭐ 按 `idem_key` **归一到最新一行再筛** ✓（供界面渲染 ✓）
  ③ ``budget_gate()``     **额度** ✓（走 `governance.check_cost` ✓ 超额**即停并说明** ✓ 拒绝**写审计** ✓）

硬约束自查：零新依赖 ✓ ｜ ⛔ 不出网 ✗（只写**文件通道** ✓ 由 `rt_relay` 负责 ✓）｜ 只读 config ✗ 不写 config ✗
"""
from __future__ import annotations

import governance

AUDIT_BUDGET_DENY = 'budget_deny'
OK_STATES = ('sent', 'duplicate')       # `duplicate` = 幂等命中 ✓ 视为**成功** ✓（不重发 ✗）


def _audit(audit, rec):
    """审计出口：可调用 / 含 `write`·`record`·`log` 的对象 ✓；不注入则静默 ✓（不落盘 ✗）"""
    if audit is None:
        return
    if callable(audit):
        audit(dict(rec))
        return
    for name in ('write', 'record', 'log', 'audit'):
        fn = getattr(audit, name, None)
        if callable(fn):
            fn(dict(rec))
            return
    raise TypeError('audit 需为可调用或含 write/record/log/audit 的对象 ✗')


# ── ① 投递（幂等 ✓ 失败不静默 ✓）──────────────────────────────────
def deliver(*, relay, round_id, role, content):
    """投递一条 → **扁平结构化回执** ✓

    ⭐ `ok` 仅当 `state ∈ (sent, duplicate)` ✓（`duplicate` = 已投递过 ✓ **不重发** ✗）
    失败 → `ok=False` + **原因** ✓（回执由 `rt_relay` 落 `receipts.jsonl` ✓ 不静默 ✗）
    """
    rec = relay.deliver(round_id, role, content) or {}
    state = str(rec.get('state') or '')
    return {
        'ok': state in OK_STATES,
        'state': state,
        'reason': str(rec.get('reason') or ''),
        'idem_key': str(rec.get('idem_key') or ''),
        'round_id': str(rec.get('round_id') or round_id),
        'role': str(rec.get('role') or role),
    }


# ── ② 回执视图（⭐ append-only 行 → 必须先归一再加筛 ✓）─────────────
def receipts_for_ui(*, relay, round_id=None, limit=None, only=None):
    """回执**视图** ✓ 供界面渲染 ✓

    ⭐ 规则（2026-09-26 入库教训 ✓）：**回执行是 append-only** ✗ → 同一 `idem_key` 可能有多行 ✓
    （如先 `sent` 后 `failed` ✗）→ **必须先按 `idem_key` 归一到最新一行，再按条件筛选** ✓
    → 否则旧行会把已变更的状态**拉回列表** ✗（与 `rt_gate.pending()` 同一坑 ✓）

    - `round_id` 过滤 ✓ · `only` = 只看某状态（如 `'failed'` ✓）· `limit` 取**归一并筛后**的尾部 ✓
    """
    latest, order = {}, []
    for r in relay.receipts():
        if not isinstance(r, dict):
            continue
        key = str(r.get('idem_key') or '')
        if not key:
            continue
        if key not in latest:
            order.append(key)
        latest[key] = r                     # 后写覆盖先写 ✓ = 最新状态 ✓
    rows = [latest[k] for k in order]
    out = []
    for r in rows:
        if round_id is not None and str(r.get('round_id') or '') != str(round_id):
            continue
        if only is not None and str(r.get('state') or '') != str(only):
            continue
        out.append({'idem_key': str(r.get('idem_key') or ''),
                    'round_id': str(r.get('round_id') or ''),
                    'role': str(r.get('role') or ''),
                    'state': str(r.get('state') or ''),
                    'reason': str(r.get('reason') or ''),
                    'ok': str(r.get('state') or '') in OK_STATES})
    return out[-int(limit):] if limit else out


# ── ③ 额度（超额即停并说明 ✓ 拒绝写审计 ✓）──────────────────────────
def budget_gate(*, estimate=0.0, check=None, audit=None, role='', round_id=''):
    """额度闸：走 `governance.check_cost` ✓ **超额即停并说明** ✓

    - `check` 可注入 ✓（默认 `governance.check_cost` ✓ 单测可替身 ✓）
    - ⭐ 拒绝时**写审计** ✓（`action='budget_deny'` ✓ 与 `rt_gate` 同名 ✓ 口径一致 ✓）
    - ⚠️ 只**读**成本 ✓ 不写 config ✗ 不改日上限 ✗（拦截口径 = `today_cost()` ✓ 余额不参与 ✓）
    """
    fn = check or governance.check_cost
    ok, why, used = fn(estimate)
    if not ok:
        _audit(audit, {'action': AUDIT_BUDGET_DENY, 'actor': '额度闸', 'role': str(role),
                       'round_id': str(round_id), 'reason': str(why), 'used': float(used or 0.0),
                       'estimate': float(estimate or 0.0)})
    return {'ok': bool(ok), 'reason': str(why or ''), 'used': float(used or 0.0),
            'estimate': float(estimate or 0.0),
            'note': '超额即停（本批**只判断**不调参 ✓ 调整在设置页 ✓）' if not ok else ''}


def pending_for_ui(*, gate, role=None):
    """未确认草稿**视图** ✓（供界面渲染「待我确认」列 ✓）

    ⭐ 状态**直读** `state` ✓ 不靠推断 ✗；归一由 `rt_gate.pending()` 负责 ✓（已修 ✓）
    ⭐ 数据层保证：**未确认 → 不进 L0** ✓（`rt_gate.draft()` 只写草稿 ✓ 本函数**只读** ✓）
    """
    out = []
    for r in gate.pending(role):
        out.append({'draft_id': str(r.get('draft_id') or ''),
                    'round_id': str(r.get('round_id') or ''),
                    'role': str(r.get('role') or ''),
                    'turn_no': int(r.get('turn_no') or 0),
                    'state': str(r.get('state') or ''),
                    'content': str(r.get('content') or ''),
                    'ts': str(r.get('ts') or '')})
    return out
