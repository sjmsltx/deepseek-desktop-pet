# -*- coding: utf-8 -*-
"""rt_relay.py — 圆桌投递适配（第 3 批 · B4）

设计依据：《设计 v1.1》§4（复用 3.0 M1 文件通道 + 回执；本批只做**适配层**）

边界（务必遵守 ✗）：
  - ⛔ **不出网** ✗：默认传输 = **文件通道写盘** ✓（可注入替身 ✓ 便于单测）
  - ⭐ **幂等键 = `轮次id|角色`** ✓：重复投递 → 回 **`duplicate`** ✓ **不重发** ✗
  - 投递失败 → 回执含**失败 + 原因** ✓ **不静默** ✗（并写 `receipts.jsonl` ✓）
"""
from __future__ import annotations

import json
import os


class Relay:
    """文件通道投递适配（一个 outbox 目录一个实例 ✓ 支持测试隔离 ✓）"""

    def __init__(self, base_dir, transport=None):
        self.base = str(base_dir)
        self.outbox = os.path.join(self.base, 'outbox')
        self.receipts_path = os.path.join(self.base, 'receipts.jsonl')
        self._transport = transport          # 可注入 ✓（入参 (round_id, role, content) → 失败时抛异常 ✓）

    # ---------- 幂等键 ----------
    @staticmethod
    def idem_key(round_id, role):
        return '%s|%s' % (round_id, role)

    def _sent_keys(self):
        keys = set()
        if not os.path.isfile(self.receipts_path):
            return keys
        with open(self.receipts_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get('state') == 'sent':
                    keys.add(str(r.get('idem_key') or ''))
        return keys

    def _write_receipt(self, rec):
        d = os.path.dirname(self.receipts_path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(self.receipts_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        return rec

    # ---------- 默认传输：写文件通道 ----------
    def _file_transport(self, round_id, role, content):
        p = os.path.join(self.outbox, str(round_id))
        os.makedirs(p, exist_ok=True)
        with open(os.path.join(p, '%s.md' % role), 'w', encoding='utf-8') as f:
            f.write(str(content or ''))
        return True

    def deliver(self, round_id, role, content):
        """投递一条 → 返回**回执** ✓（`state`: `sent` / `duplicate` / `failed` ✓）"""
        key = self.idem_key(round_id, role)
        if key in self._sent_keys():
            return self._write_receipt({'idem_key': key, 'round_id': str(round_id), 'role': str(role),
                                        'state': 'duplicate', 'reason': '幂等：已投递过 ✓ 不重发 ✗'})
        fn = self._transport or self._file_transport
        try:
            fn(round_id, role, content)
        except Exception as e:
            return self._write_receipt({'idem_key': key, 'round_id': str(round_id), 'role': str(role),
                                        'state': 'failed', 'reason': '%s: %s' % (type(e).__name__, e)})
        return self._write_receipt({'idem_key': key, 'round_id': str(round_id), 'role': str(role),
                                    'state': 'sent', 'reason': ''})

    def receipts(self, limit=None):
        out = []
        if os.path.isfile(self.receipts_path):
            with open(self.receipts_path, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        continue
        return out[-int(limit):] if limit else out
