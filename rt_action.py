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

import io
import json
import os

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


# ── ④ 人工确认闸门·完整动作链（C2b ✓）─────────────────────────────
def _flat_receipt(rec):
    if not isinstance(rec, dict) or not rec:
        return None
    state = str(rec.get('state') or '')
    return {'ok': state in OK_STATES, 'state': state, 'reason': str(rec.get('reason') or ''),
            'idem_key': str(rec.get('idem_key') or ''), 'round_id': str(rec.get('round_id') or ''),
            'role': str(rec.get('role') or '')}


def draft_for_human(*, gate, round_id, role, content, turn_no=0):
    """生成**待人工确认**草稿 ✓ ⭐ **不进 L0** ✗（`rt_gate.draft()` 只写草稿 ✓）"""
    did = gate.draft(round_id, role, content, turn_no=turn_no)
    return {'ok': True, 'draft_id': did, 'state': 'pending', 'in_l0': False,
            'note': '未确认 → 不进 L0 ✗（数据层保证 ✓）'}


def confirm_draft(*, gate, draft_id, round_id=None, turn_no=0):
    """人工确认 ✓ → **写 L0** ✓ + 返回 `ptr` ✓ + **投递回执** ✓

    ⚠️ 额度不足 → 闸门**已写审计** `budget_deny` ✓ 并置 `rejected` ✓ → 此时 `ok=False` + **不进 L0** ✗
    """
    res = gate.confirm(draft_id, round_id=round_id, turn_no=turn_no) or {}
    return {'ok': bool(res.get('ok')), 'reason': str(res.get('reason') or ''),
            'ptr': str(res.get('ptr') or ''), 'in_l0': bool(res.get('ptr')),
            'receipt': _flat_receipt(res.get('receipt'))}


def reject_draft(*, gate, draft_id, reason=''):
    """否决 ✓ → `state=rejected` ✓ ⭐ **不留 L0** ✗"""
    res = gate.reject(draft_id, reason=reason) or {}
    return {'ok': bool(res.get('ok')), 'reason': str(res.get('reason') or reason),
            'in_l0': False, 'note': '否决 → 不留 L0 ✗'}


def draft_detail_for_ui(*, gate, draft_id):
    """界面点开某草稿：内容 + 状态 ✓（⭐ 状态**直读** `state` ✓ 不靠推断 ✗）"""
    r = gate.latest_draft(draft_id)
    if not r:
        return {'ok': False, 'reason': '草稿不存在（%s）' % draft_id}
    return {'ok': True, 'draft_id': str(r.get('draft_id') or ''),
            'round_id': str(r.get('round_id') or ''), 'role': str(r.get('role') or ''),
            'turn_no': int(r.get('turn_no') or 0), 'state': str(r.get('state') or ''),
            'content': str(r.get('content') or ''), 'ts': str(r.get('ts') or ''),
            'in_l0': str(r.get('state') or '') == 'confirmed'}


# ── ⑤ 装配与审计落盘（⭐ 额度拒绝必留痕 ✓ 不静默 ✗）─────────────────
def make_audit(path):
    """文件审计出口（**append-only** ✓）→ 注入闸门即"拒绝必留痕" ✓ 不静默 ✗"""
    def _sink(action, role='', where='', detail=''):
        p = str(path)
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)
        with io.open(p, 'a', encoding='utf-8', newline='') as f:
            f.write(json.dumps({'action': str(action), 'role': str(role),
                                'where': str(where), 'detail': str(detail)}, ensure_ascii=False) + '\n')
    return _sink


def make_gate(*, store, base_dir, relay=None, check_budget=None, audit_path=None):
    """装配人工确认闸门 ✓ ⭐ `audit_path` 默认 `<base_dir>/audit.jsonl` ✓

    ⭐ 接线的界面侧**应当用本函数建闸门** ✓ → 额度拒绝会自动留痕 ✓（否则 `rt_gate` 默认审计为**空操作** ✗）
    """
    import rt_gate
    p = audit_path if audit_path is not None else os.path.join(str(base_dir), 'audit.jsonl')
    return rt_gate.Gate(store, base_dir, audit=make_audit(p), check_budget=check_budget, relay=relay)
