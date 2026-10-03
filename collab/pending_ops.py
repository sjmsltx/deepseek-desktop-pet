# -*- coding: utf-8 -*-
"""collab/pending_ops.py —— **待办／结果文件协议**（契约条款 IV **E2** ✓）

用途（只有这一个 ✓）：界面侧把"变更请求"落成**待办文件** ✓；电脑侧**人触发**的运行器消费它 ✓。

⛔ 本模块**不执行任何东西** ✗（执行只在 `run_pending.py` ✓）
⛔ 本模块**不碰领域文件** ✗（`config.json` / `assets/` 一律由运行器按类型改 ✓）
⛔ 不引入任何凭证 ✗（`requested_by` 只存 peer id 引用 ✓ E2 ✓）
"""
from __future__ import annotations

import json
import os
import random
import re
import time

PENDING_DIRNAME = 'pending'                      # ⭐ E1② 只写这一个目录 ✓
RESULTS_NAME = 'results.jsonl'                   # ⭐ E2 只追加 ✓
OP_TYPES = ('project_edit', 'asset_op')          # ⭐ E1① 类型枚举 ✓（不收命令/脚本 ✗）
_NAME_RE = re.compile(r'^(\d{8}-\d{6})-([a-z_]+)-([A-Za-z0-9_-]{4,64})\.json$')
_PATHISH = re.compile(r'^(?:[A-Za-z]:[\\/]|/|\\\\|~[\\/])')          # 绝对路径类 ✓
_LEVEL_WORDS = ('\\.\\.', '..')                                       # ⭐ E1③ 拒 `..` ✓


def _path_problem(v) -> str:
    """逐值判断：返回问题描述或 '' ✓。⭐ 比查 JSON 文本串可靠得多 ✗

    （教训：早先版本拿 `json.dumps` 后的整串去 search ✓ —— 而正则锚在**串首** ✗
       → JSON 以 `{` 开头，永远匹配不上 ✗ → 绝对路径能溜过去 ✗）
    """
    if not isinstance(v, str):
        return ''
    s = v.strip().replace('\\', '/')
    if not s:
        return ''
    if re.match(r'^[A-Za-z]:/', s) or s.startswith('/') or s.startswith('~'):
        return '绝对路径'
    if any(seg == '..' for seg in s.split('/')):
        return '..'
    return ''


def _scan_paths(obj, path='payload') -> str:
    """递归扫 payload 里所有字符串值 ✓（dict/list 都进 ✓）。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            r = _scan_paths(v, '%s.%s' % (path, k))
            if r:
                return '%s 含%s' % (path, r)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            r = _scan_paths(v, '%s[%d]' % (path, i))
            if r:
                return r
    else:
        return _path_problem(obj)
    return ''


def base_dir_of(base_dir: str = '') -> str:
    """待办根目录（默认 = 本文件同级的 `pending/` ✓）。"""
    if base_dir:
        return str(base_dir)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), PENDING_DIRNAME)


def op_id_new() -> str:
    """新幂等键（★ 撞号沿用既有约定：时间戳 ＋ 随机 ✓）。"""
    return '%s-%04d' % (time.strftime('%Y%m%d%H%M%S'), random.randint(0, 9999))


def validate_request(req) -> tuple:
    """校验一条变更请求 → `(ok, why)`。⭐ 全是**拒绝式**校验 ✓ 宁严勿松 ✓"""
    if not isinstance(req, dict):
        return False, '请求必须是对象'
    t = str(req.get('type') or '')
    if t not in OP_TYPES:                                     # E1① 枚举 ✓
        return False, '类型不在枚举内：%r（仅 %s）' % (req.get('type'), ' / '.join(OP_TYPES))
    oid = str(req.get('op_id') or '')
    if not re.match(r'^[A-Za-z0-9_-]{4,64}$', oid):           # 幂等键形状 ✓
        return False, 'op_id 形状非法（应 [A-Za-z0-9_-]{4,64}）'
    payload = req.get('payload')
    if not isinstance(payload, dict):
        return False, 'payload 必须是对象'
    # ⭐ E1③：载荷里出现绝对路径或 `..` → 直接拒 ✗（防越界写 ✓）
    _p = _scan_paths(payload)
    if _p:
        return False, 'payload %s，已拒' % _p
    rb = str(req.get('requested_by') or '')
    if rb and ('sk-' in rb.lower() or 'token' in rb.lower() or 'secret' in rb.lower()):
        return False, 'requested_by 只允许 peer id 引用，不含凭证'   # E2 ✓
    return True, ''


def write_pending(req: dict, base_dir: str = '') -> str:
    """⭐ 把一个**已校验**的请求写成待办文件（**只写待办目录** ✓ 不带任意落点 ✗）。"""
    ok, why = validate_request(req)
    if not ok:
        raise ValueError(why)
    d = base_dir_of(base_dir)
    os.makedirs(d, exist_ok=True)
    fn = '%s-%s-%s.json' % (time.strftime('%Y%m%d-%H%M%S'), req['type'], req['op_id'])
    path = os.path.join(d, fn)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(req, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)                                     # 原子落盘 ✓
    return path


def parse_pending_name(fn: str):
    """`<YYYYMMDD-HHMMSS>-<type>-<op_id>.json` → `(ts, type, op_id)` 或 None ✓。"""
    m = _NAME_RE.match(os.path.basename(fn))
    return (m.group(1), m.group(2), m.group(3)) if m else None


def list_pending(base_dir: str = '') -> list:
    """列出待办（**按文件名排序** ✓ 跳过 `.tmp` 与非法名 ✓）。"""
    d = base_dir_of(base_dir)
    out = []
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        if not fn.endswith('.json'):
            continue
        meta = parse_pending_name(fn)
        if not meta:
            continue
        try:
            with open(os.path.join(d, fn), encoding='utf-8') as fh:
                req = json.load(fh)
        except Exception:
            continue
        out.append({'file': fn, 'ts': meta[0], 'type': meta[1], 'op_id': meta[2], 'request': req})
    return out


def results_path(base_dir: str = '') -> str:
    return os.path.join(base_dir_of(base_dir), RESULTS_NAME)


def read_results(base_dir: str = '') -> list:
    """读结果（⭐ **只读不写** ✓；坏行跳过不影响其余 ✓）。"""
    p = results_path(base_dir)
    out = []
    if not os.path.isfile(p):
        return out
    with open(p, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def done_op_ids(base_dir: str = '') -> set:
    """已出现过结果的 op_id（⭐ 幂等依据 ✓）。"""
    return {str(r.get('op_id')) for r in read_results(base_dir) if r.get('op_id')}


def append_result(op_id: str, ok: bool, reason: str = '', detail: str = '', base_dir: str = '') -> str:
    """⭐ 追加一条结果（**只追加** ✗ 不改旧行 ✓；E1⑥ 失败也必须落 ✓）。"""
    rec = {'op_id': str(op_id), 'ok': bool(ok), 'reason': str(reason or ''),
           'detail': str(detail or '')[:2000], 'ts': int(time.time() * 1000)}
    p = results_path(base_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'a', encoding='utf-8') as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
    return p
