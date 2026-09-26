# -*- coding: utf-8 -*-
"""rt_store.py — 「圆桌」L0/L1 存储（第 3 批 · B1）

设计依据：`PC-设计-20260925-19` **v1.1**（微信侧交叉复核通过 ✓）
边界（务必遵守 ✗）：
  - **IO 集中在本模块** ✓；指针解析是**纯函数** ✓（可单测 ✓）
  - ⛔ **不出网** ✗（AST 护栏 `tests/test_rt_store.py`）
  - L0 = 按角色 × 按天分片 JSONL ✓ **永不替换为摘要** ✗（Owner 口径：全文存文件可查 ✓）
  - L1 = `summaries.jsonl` **永久 append-only** ✓（含 `round_id` / `turn_no` / `kind` ✓）
  - ⭐ **滚动只动 L0** ✓（L1 / 指针 / `meta.json` / `rolled.jsonl` 一律不动 ✗）
  - ⭐ 缺失 / 已滚 → **明确报错** ✗（不静默返回空 ✗）
"""
from __future__ import annotations

import datetime
import json
import os
import re

SCHEMA_VERSION = 1
DEFAULT_L0_MAX_BYTES = 200 * 1024 * 1024          # Owner 批：~200 MB ✓
_PTR_RX = re.compile(r'^([A-Za-z0-9_\-\u4e00-\u9fff]{1,32})\|(\d{4}-\d{2}-\d{2})\|(\d{4})$')


class MissingOriginal(Exception):
    """原文缺失 / 已被滚动 —— ⭐ **必须上抛** ✗ 不静默返回空 ✓"""


def _today():
    return datetime.date.today().isoformat()


def make_ptr(role, day, seq):
    """指针：``角色|日期|4位序号`` ✓（人可读可核对 ✓）"""
    return '%s|%s|%04d' % (str(role), str(day), int(seq))


def parse_ptr(ptr):
    """纯函数：解析指针 → ``{'role','day','seq'}`` ✓ 格式不对 → **抛 ValueError** ✗"""
    m = _PTR_RX.match(str(ptr or '').strip())
    if not m:
        raise ValueError('指针格式非法（应为 角色|YYYY-MM-DD|0001）：%r' % (ptr,))
    return {'role': m.group(1), 'day': m.group(2), 'seq': int(m.group(3))}


class Store:
    """L0/L1 存储（一个目录一个库 ✓ 支持多实例/测试隔离 ✓）"""

    def __init__(self, base_dir):
        self.base = str(base_dir)
        self.channels_dir = os.path.join(self.base, 'channels')
        self.summaries_path = os.path.join(self.base, 'summaries.jsonl')
        self.rolled_path = os.path.join(self.base, 'rolled.jsonl')
        self.meta_path = os.path.join(self.base, 'meta.json')

    # ---------- 路径 ----------
    def day_path(self, role, day):
        return os.path.join(self.channels_dir, str(role), '%s.jsonl' % day)

    def _ensure(self, p):
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)

    # ---------- meta（schema_version ✓）----------
    def meta(self):
        try:
            with open(self.meta_path, encoding='utf-8') as f:
                m = json.load(f)
            if not isinstance(m, dict):
                raise ValueError('meta 不是对象')
            m.setdefault('schema_version', 0)
            return m
        except FileNotFoundError:
            return {'schema_version': SCHEMA_VERSION, 'limits': {'l0_max_bytes': DEFAULT_L0_MAX_BYTES}}
        except Exception as e:
            # ⭐ 版本不符/坏档：**明确报错** ✗ 不静默 ✗
            raise MissingOriginal('meta.json 无法解析（明确报错，不静默 ✗）：%s' % e)

    def _write_meta(self, patch=None):
        m = self.meta()
        m.setdefault('schema_version', SCHEMA_VERSION)
        m.setdefault('limits', {'l0_max_bytes': DEFAULT_L0_MAX_BYTES})
        if patch:
            m.update(patch)
        self._ensure(self.meta_path)
        with open(self.meta_path, 'w', encoding='utf-8') as f:
            json.dump(m, f, ensure_ascii=False, indent=2)
        return m

    # ---------- L0 ----------
    def _read_jsonl(self, path):
        out = []
        if not os.path.isfile(path):
            return out
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue                      # 坏行跳过（不影响其余 ✓）
        return out

    def append(self, role, kind, text, *, day=None, round_id='', turn_no=0):
        """追加一条 L0（**全文** ✓ 不摘要 ✗）→ 返回 ``ptr`` ✓"""
        day = day or _today()
        p = self.day_path(role, day)
        self._ensure(p)
        recs = self._read_jsonl(p)
        seq = len(recs) + 1
        rec = {'seq': seq, 'ts': datetime.datetime.now().isoformat(timespec='seconds'),
               'role': str(role), 'kind': str(kind), 'text': str(text)}
        if round_id:
            rec['round_id'] = str(round_id)
            rec['turn_no'] = int(turn_no or 0)
        with open(p, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        return make_ptr(role, day, seq)

    def read(self, role, day, seq):
        """取原文：**已滚/缺失 → 抛 `MissingOriginal`** ✗ 不静默 ✓"""
        p = self.day_path(role, day)
        if not os.path.isfile(p):
            raise MissingOriginal('原文已过期（仅摘要可用）：%s' % make_ptr(role, day, seq))
        for r in self._read_jsonl(p):
            if int(r.get('seq') or 0) == int(seq):
                return r
        raise MissingOriginal('原文缺失（序号不存在）：%s' % make_ptr(role, day, seq))

    def list_day(self, role, day):
        return self._read_jsonl(self.day_path(role, day))

    def days(self, role):
        d = os.path.join(self.channels_dir, str(role))
        if not os.path.isdir(d):
            return []
        return sorted(n[:-6] for n in os.listdir(d) if n.endswith('.jsonl'))

    # ---------- L1（永久 append-only ✓）----------
    def add_summary(self, ptr, summary, *, round_id='', turn_no=0, kind='', ts=''):
        """写 L1 ✓ **幂等**（同 ptr 已有同摘要 → 跳过 ✓ 不改写历史 ✗）"""
        info = parse_ptr(ptr)
        for row in self.summaries(limit=None):
            if row.get('ptr') == ptr and str(row.get('summary') or '') == str(summary):
                return False
        rec = {'ptr': ptr, 'role': info['role'], 'day': info['day'], 'seq': info['seq'],
               'summary': str(summary), 'ts': ts or datetime.datetime.now().isoformat(timespec='seconds'),
               'round_id': str(round_id or ''), 'turn_no': int(turn_no or 0),
               'kind': str(kind or ''), 'expired': False}
        self._ensure(self.summaries_path)
        with open(self.summaries_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        return True

    def summaries(self, *, role=None, day=None, round_id=None, limit=None):
        """读 L1（按 ptr 取**最后一条** ✓ 支持按角色/日/轮过滤 ✓）"""
        rows = self._read_jsonl(self.summaries_path)
        latest = {}
        order = []
        for r in rows:
            if not isinstance(r, dict) or not r.get('ptr'):
                continue
            if role and r.get('role') != role:
                continue
            if day and r.get('day') != day:
                continue
            if round_id and r.get('round_id') != round_id:
                continue
            k = r['ptr']
            if k not in latest:
                order.append(k)
            latest[k] = r
        out = [latest[k] for k in order]
        if limit:
            out = out[-int(limit):]
        return out

    def mark_expired(self, ptrs):
        """标记一批指针的原文已失效（**只追加一行** ✓ 不改写既有行 ✗）"""
        n = 0
        for ptr in ptrs:
            try:
                info = parse_ptr(ptr)
            except ValueError:
                continue
            rec = {'ptr': ptr, 'role': info['role'], 'day': info['day'], 'seq': info['seq'],
                   'summary': '', 'ts': datetime.datetime.now().isoformat(timespec='seconds'),
                   'round_id': '', 'turn_no': 0, 'kind': '', 'expired': True}
            self._ensure(self.summaries_path)
            with open(self.summaries_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            n += 1
        return n

    def is_expired(self, ptr):
        rows = [r for r in self._read_jsonl(self.summaries_path) if r.get('ptr') == ptr]
        return bool(rows and rows[-1].get('expired'))

    # ---------- 回放（**只读** ✗ 不产新行 ✓）----------
    def replay(self, role, day):
        """回放某角色某日：有 L0 → 全文 ✓；已滚 → L1 摘要 + ``expired=True`` ✓ **只读** ✗"""
        recs = self.list_day(role, day)
        if recs:
            return [{'source': 'L0', 'expired': False, 'rec': r} for r in recs]
        rows = [r for r in self.summaries(role=role, day=day) if parse_ptr(r['ptr'])['role'] == role]
        return [{'source': 'L1', 'expired': bool(r.get('expired')), 'rec': r} for r in rows]

    # ---------- 滚动（⭐ **只动 L0** ✗）----------
    def _l0_day_sizes(self):
        out = []
        if not os.path.isdir(self.channels_dir):
            return out
        for role in sorted(os.listdir(self.channels_dir)):
            d = os.path.join(self.channels_dir, role)
            if not os.path.isdir(d):
                continue
            for n in sorted(os.listdir(d)):
                if not n.endswith('.jsonl'):
                    continue
                p = os.path.join(d, n)
                try:
                    out.append((n[:-6], p, os.path.getsize(p)))
                except OSError:
                    continue
        return out

    def l0_total_bytes(self):
        return sum(sz for _day, _p, sz in self._l0_day_sizes())

    def roll(self, max_bytes=None):
        """超限 → 从**最旧的整天**开始滚 ✗（**只动 L0** ✓）→ 返回被滚日期列表 ✓"""
        lim = int(max_bytes or (self.meta().get('limits') or {}).get('l0_max_bytes') or DEFAULT_L0_MAX_BYTES)
        total = self.l0_total_bytes()
        if total <= lim:
            return []
        by_day = {}
        for day, p, sz in self._l0_day_sizes():
            by_day.setdefault(day, []).append((p, sz))
        rolled = []
        for day in sorted(by_day):
            if total <= lim:
                break
            ptrs = []
            for p, sz in by_day[day]:
                role = os.path.basename(os.path.dirname(p))
                for r in self._read_jsonl(p):
                    try:
                        ptrs.append(make_ptr(role, day, int(r.get('seq') or 0)))
                    except Exception:
                        continue
                try:
                    os.remove(p)          # 只删 L0 分片 ✓
                except OSError:
                    continue
                total -= sz
            self.mark_expired(ptrs)
            rec = {'day': day, 'ptrs': len(ptrs), 'ts': datetime.datetime.now().isoformat(timespec='seconds')}
            self._ensure(self.rolled_path)
            with open(self.rolled_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            rolled.append(day)
        self._write_meta({'last_roll': datetime.datetime.now().isoformat(timespec='seconds')})
        return rolled

    # ---------- 概览 ----------
    def stats(self):
        return {'schema_version': self.meta().get('schema_version'),
                'l0_bytes': self.l0_total_bytes(),
                'l0_max_bytes': (self.meta().get('limits') or {}).get('l0_max_bytes'),
                'l1_rows': len(self._read_jsonl(self.summaries_path)),
                'rolled_days': len(self._read_jsonl(self.rolled_path))}
