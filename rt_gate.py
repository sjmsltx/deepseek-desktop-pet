# -*- coding: utf-8 -*-
"""rt_gate.py — 圆桌闸门（人工确认 / 额度 / 审计）（第 3 批 · B4）

设计依据：《设计 v1.1》§5 + 加固 B（`drafts/` 带 `state` + `draft_id`）

边界（务必遵守 ✗）：
  - ⭐ **未确认不进 L0** ✗：`draft()` 只写 `drafts/`（`state=pending` ✓）
  - `confirm()` 才写 L0（经 `Store.append` ✓）并投递 ✓；`reject()` **不留 L0** ✗
  - **额度**与**审计**均**可注入** ✓（默认：额度放行 ✓ 审计 no-op ✓）→ 上层接 `governance` ✓
  - ⛔ 不出网 ✗（AST 护栏）
"""
from __future__ import annotations

import datetime
import json
import os


def _today_compact():
    return datetime.date.today().strftime('%Y%m%d')


class Gate:
    """人工确认闸门 + 额度 + 审计（一个目录一个实例 ✓）"""

    def __init__(self, store, base_dir, *, audit=None, check_budget=None, relay=None):
        self.store = store
        self.base = str(base_dir)
        self.drafts_dir = os.path.join(self.base, 'drafts')
        self._audit = audit or (lambda *a, **k: None)
        self._check_budget = check_budget or (lambda role='': (True, ''))
        self._relay = relay
        self._seq = 0

    # ---------- 草稿（pending ✓ 不进 L0 ✗）----------
    def _draft_path(self, role):
        d = self.drafts_dir
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, '%s.jsonl' % role)

    def _append_draft(self, rec):
        with open(self._draft_path(rec['role']), 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        return rec

    def _read_drafts(self, role=None):
        out = []
        if not os.path.isdir(self.drafts_dir):
            return out
        for n in sorted(os.listdir(self.drafts_dir)):
            if not n.endswith('.jsonl'):
                continue
            if role and n[:-6] != role:
                continue
            with open(os.path.join(self.drafts_dir, n), encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        continue
        return out

    def latest_draft(self, draft_id):
        rows = [r for r in self._read_drafts() if r.get('draft_id') == draft_id]
        return rows[-1] if rows else None

    def _set_state(self, draft_id, state):
        cur = self.latest_draft(draft_id)
        if not cur:
            raise KeyError('草稿不存在：%s' % draft_id)
        rec = dict(cur)
        rec['state'] = state
        rec['ts_state'] = datetime.datetime.now().isoformat(timespec='seconds')
        return self._append_draft(rec)

    def draft(self, round_id, role, content, *, turn_no=0):
        """生成草稿（**pending** ✓ **不写 L0** ✗）→ 返回 `draft_id` ✓

        ⭐ 序号**从已有草稿续号** ✓（防重启后 `d-YYYYMMDD-0001` 撞号 ✗ 撞号会导致状态读错 ✗）
        """
        tag = 'd-%s-' % _today_compact()
        try:
            seen = [r for r in self._read_drafts() if str(r.get('draft_id') or '').startswith(tag)]
            self._seq = max(self._seq, len(seen))
        except Exception:
            pass
        self._seq += 1
        did = '%s%04d' % (tag, self._seq)
        rec = {'draft_id': did, 'round_id': str(round_id), 'role': str(role),
               'content': str(content or ''), 'turn_no': int(turn_no or 0),
               'state': 'pending', 'ts': datetime.datetime.now().isoformat(timespec='seconds')}
        self._append_draft(rec)
        self._audit('draft', role, '人工确认闸门', did)
        return did

    # ---------- 确认 / 否决 ----------
    def confirm(self, draft_id, *, round_id=None, turn_no=0):
        """确认 → **写 L0** ✓ 并投递 ✓ → 返回 `ptr` ✓（额度不足 → **拒绝并写审计** ✗）"""
        cur = self.latest_draft(draft_id)
        if not cur:
            raise KeyError('草稿不存在：%s' % draft_id)
        if cur.get('state') != 'pending':
            raise ValueError('草稿状态不是 pending（%s）——不重复确认 ✗' % cur.get('state'))
        ok, why = self._check_budget(cur.get('role'))
        if not ok:
            self._audit('budget_deny', cur.get('role'), '人工确认闸门', str(why))
            self._set_state(draft_id, 'rejected')
            return {'ok': False, 'reason': str(why), 'ptr': ''}
        rid = round_id or cur.get('round_id') or ''
        ptr = self.store.append(cur.get('role'), 'role', cur.get('content'),
                               round_id=rid, turn_no=turn_no or cur.get('turn_no') or 0)
        self._set_state(draft_id, 'confirmed')
        self._audit('confirm', cur.get('role'), '人工确认闸门', ptr)
        receipt = None
        if self._relay is not None:
            receipt = self._relay.deliver(rid, cur.get('role'), cur.get('content'))
        return {'ok': True, 'reason': '', 'ptr': ptr, 'receipt': receipt}

    def reject(self, draft_id, *, reason=''):
        """否决 → `state=rejected` ✓ **不留 L0** ✗"""
        self._set_state(draft_id, 'rejected')
        cur = self.latest_draft(draft_id) or {}
        self._audit('reject', cur.get('role'), '人工确认闸门', str(reason))
        return {'ok': True, 'reason': str(reason)}

    def pending(self, role=None):
        """未确认草稿（界面直读 `state` ✓ 不靠推断 ✗）

        ⭐ 必须**先归一到最新状态**（后写覆盖先写 ✓）—— 否则已否决草稿的旧 `pending` 行
        会把它又拉回列表 ✗（本批实测到该 bug ✓ 已修 ✓）
        """
        latest = {}
        for r in self._read_drafts(role):
            did = r.get('draft_id')
            if did:
                latest[did] = r            # 后写覆盖先写 ✓ = 最新状态 ✓
        return [r for r in latest.values() if r.get('state') == 'pending']
