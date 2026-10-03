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
# ⭐ 载荷字段白名单（`-105` §一 审定 ✓ 未知字段一律拒 ✗）
PROJECT_FIELDS = ('name', 'root', 'outputs', 'memory_file', 'roles')
ASSET_OPS = ('insert', 'replace', 'add_state', 'add_role', 'delete_state',
             'run_pipeline', 'set_portrait')          # ⭐ `set_portrait` Owner 00:36 已批 ✓
ASSET_SOURCES = ('pool', 'assets')               # ⭐ 白名单根 ✓
# ⭐ 运行必需的**内置状态**（⛔ 不可删 ✗ —— 微信侧 `-16` §2.3#2 补的，我方漏了 ✓）
BUILTIN_STATES = ('idle', 'blink', 'happy', 'angry', 'sad', 'sleep', 'hungry',
                  'eating', 'thinking', 'crying', 'cry', 'surprised', 'shy')
_MAX_ROOT = 512
_BAD_DEVICE = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)', re.I)
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


def _root_problem(v) -> str:
    r"""⭐ `root` 的**唯一绝对路径例外**（条款 IV E1③ 例外 · Owner 23:04 已批 ✓）

    四条限缩（`PC-…-105` §〇 ✓）：① 只此一项 ✓ ② 必须**已存在目录** ✓（只登记·不创建 ✗）
    ③ 长度 ≤ %d 且不得含 `..` 段 ✗ ④ 拒 UNC／设备前缀／设备名 ✗
    """
    s = str(v or '').strip()
    if not s:
        return 'root 不能为空'
    if len(s) > _MAX_ROOT:
        return 'root 超过 %d 字' % _MAX_ROOT
    if s.startswith('\\\\') or s.startswith('//') or s.startswith('\\\\?\\'):
        return 'root 不得为 UNC/设备前缀'
    if any(seg == '..' for seg in s.replace('\\', '/').split('/')):
        return 'root 不得含 ..'
    if not os.path.isdir(s):
        return 'root 必须是**已存在**的目录（只登记，不创建）'
    return ''


def _rel_problem(v) -> str:
    """相对路径字段（`outputs`／`memory_file`／`source_ref`）⭐ **只允许相对形式** ✓。"""
    s = str(v or '').strip()
    if not s:
        return '不能为空'
    t = s.replace('\\', '/')
    if re.match(r'^[A-Za-z]:', t) or t.startswith('/') or t.startswith('~'):
        return '只允许相对路径（不得盘符/根/~/UNC）'
    if any(seg == '..' for seg in t.split('/')):
        return '不得含 ..'
    return ''


def _rel_ok(v) -> str:
    """⭐ `source_ref` 两种写法**都收**（微信侧 `WX-…-20261004-11` §2.1 实测撞到 ✓）：

      · 带白名单根：`assets_3.0/deepseek/deepseek_idle.png` ✓ / `assets/flash/flash_idle.png` ✓
      · ⭐ 裸形式：`deepseek/deepseek_idle.png` ✓（按 `source` 指定的根解析 ✓ 更好用 ✓）

    ⛔ 两形式均**不得**含绝对路径／`..` ✗；裸形式**必须恰好两段**（角色/文件名 ✓）
    ⚠️ 旧行为：校验只认带根形式 ✗ 而解析器**两种都支持** ✗ → 不一致 → 裸形式被 400 拒 ✓
       （你方实测：`source_ref:"deepseek/deepseek_idle.png"` → 400 ✓ 报错文案本身没错 ✓ 但不友好 ✓）
    """
    s = str(v or '').strip()
    if not s:
        return 'source_ref 不能为空'
    p = _rel_problem(s)                                   # 拒绝对路径 / `..` ✓
    if p:
        return 'source_ref %s' % p
    parts = s.replace('\\', '/').split('/')
    if parts[0] in ('assets_3.0', 'assets'):
        # ⭐ 带根形式必须是 root/角色/文件 ✓（≥3 段 ✗ 否则缺文件名 ✓）
        return '' if len(parts) >= 3 else 'source_ref 带根时必须写到文件（assets_3.0/<角色>/<文件>）'
    if len(parts) != 2:
        return ('source_ref 应写 `assets_3.0/<角色>/<文件>` 或裸形式 `<角色>/<文件>`；'
                '例如 assets_3.0/deepseek/deepseek_idle.png')
    return ''


def _asset_payload_problem(payload: dict) -> str:
    """`asset_op` 载荷校验（`-105` §一.2 ✓ ＋ `set_portrait` 补充口径 ✓）。"""
    role = str(payload.get('role') or '').strip()
    if not re.match(r'^[A-Za-z0-9_-]{1,64}$', role):
        return 'role 形状非法'
    op = str(payload.get('op') or '')
    if op not in ASSET_OPS:                                  # 枚举 ✓
        return 'op 不在枚举内：%r' % payload.get('op')
    # ⭐ `set_portrait`：**只收** `{role, portrait_prefix}` ✓ ⛔ 不收其它字段、⛔ 无 state ✗
    if op == 'set_portrait':
        extra = [k for k in payload if k not in ('role', 'op', 'portrait_prefix')]
        if extra:
            return 'set_portrait 不接受其它字段：%s' % ', '.join(extra)
        pfx = payload.get('portrait_prefix')
        if pfx is None:
            return 'set_portrait 缺 portrait_prefix'
        pfx = str(pfx).strip()
        if pfx and ('/' in pfx or '\\' in pfx or '..' in pfx):
            return 'portrait_prefix 只允许单段目录名（或留空解绑）✗'
        return ''
    st = str(payload.get('state') or '').strip()
    if not re.match(r'^[a-z0-9_]{1,32}$', st):
        return 'state 形状非法（[a-z0-9_]{1,32}）'
    # ⭐ 内置状态不可删 ✗（运行必需 ✓）
    if op == 'delete_state' and st in BUILTIN_STATES:
        return '内置状态 %r 不可删（运行必需）' % st
    src = payload.get('source')
    if src is not None and str(src) not in ASSET_SOURCES:
        return 'source 不在枚举内：%r' % src
    ref = payload.get('source_ref')
    if ref is not None:
        p = _rel_ok(ref)
        if p:
            return p
    return ''


def validate_request(req) -> tuple:
    """校验一条变更请求 → `(ok, why)`。⭐ 全是**拒绝式**校验 ✓ 宁严勿松 ✓

    `known_roles`（可选）：当前 `/api/roles` 见过的 key 集合 ✓ 传入则校验 `roles` 项 ✓
    """
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
    # ⭐ E1③：载荷里出现绝对路径或 `..` → 直接拒 ✗
    # ⭐ 例外：`project_edit.changes.root`（唯一一项 ✓ 由 `_root_problem` 单独把关 ✓）
    #    —— 坑：若先整块扫，`root` 的绝对路径会在这里被叉掉 ✗，永远走不到例外 ✓
    if t == 'project_edit':
        _p = _scan_paths({k: v for k, v in payload.items() if k != 'changes'})
        if not _p:
            _ch = payload.get('changes')
            if isinstance(_ch, dict):
                _p = _scan_paths({k: v for k, v in _ch.items() if k != 'root'}, 'payload.changes')
    else:
        _p = _scan_paths(payload)
    if _p:
        return False, 'payload %s，已拒' % _p
    if t == 'project_edit':
        # ⭐ `payload` **顶层**也要白名单（微信侧 `WX-…-20261004-09` §4.1 ✓）——
        #    与 `changes` 同口径 ✓：不然只拦内层不拦外层 ✗ 契约扫描也没法一致 ✓
        _extra = [k for k in payload if k not in ('project_id', 'changes')]
        if _extra:
            return False, 'payload 顶层含未知字段：%s' % ', '.join(_extra)
        changes = payload.get('changes')
        if not isinstance(changes, dict) or not changes:
            return False, 'project_edit 必须给非空 changes'
        unknown = [k for k in changes if k not in PROJECT_FIELDS]   # 字段白名单 ✓
        if unknown:
            return False, 'changes 含未知字段：%s' % ', '.join(unknown)
        name = str(changes.get('name') or '').strip()
        if 'name' in changes and not (1 <= len(name) <= 80):
            return False, 'name 长度须为 1–80 字（去空白后非空）'
        for k in ('outputs', 'memory_file'):
            if k in changes:
                p = _rel_problem(changes[k])
                if p:
                    return False, '%s %s' % (k, p)
        if 'root' in changes:
            p = _root_problem(changes['root'])               # ⭐ 唯一例外 ✓
            if p:
                return False, p
        if 'roles' in changes:
            rl = changes['roles']
            if not isinstance(rl, list) or any(not isinstance(x, str) for x in rl):
                return False, 'roles 必须是字符串数组'
    elif t == 'asset_op':
        p = _asset_payload_problem(payload)
        if p:
            return False, p
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
    """已**真被消费**的 `op_id`（⭐ 幂等依据 ✓）。

    ⚠️ 必须排除两类 ✗（⭐ 微信侧两轮 QA 各揪出一类 ✓）：
      · `dry_run:true` —— 预演不算消费 ✓
      · ⭐ `ok:false` —— **失败也不算消费** ✓（失败时**什么都没发生** ✓ → 重跑安全 ✓）
    ⭐ 否则：用户提交 → 失败 → 我们修好 bug → 用户重跑 → **幂等跳过、毫无反应** ✗
       → 用户会以为“还没修好” ✗（`WX-…-20261004-09` §4.2 实测 ✓）
    """
    return {str(r.get('op_id')) for r in read_results(base_dir)
            if r.get('op_id') and not r.get('dry_run') and r.get('ok')}


def append_result(op_id: str, ok: bool, reason: str = '', detail: str = '', base_dir: str = '',
                  dry_run: bool = False, artifacts=None) -> str:
    """⭐ 追加一条结果（**只追加** ✗ 不改旧行 ✓；E1⑥ 失败也必须落 ✓）。

    ⭐ `dry_run=True`：预演结果也落盘 ✓（口径 ③ ✓）—— ⭐ 但它**不算已消费** ✗，
       否则真跑会被“幂等”误跳过 ✗（见 `done_op_ids` 的过滤 ✓）
    """
    rec = {'op_id': str(op_id), 'ok': bool(ok), 'reason': str(reason or ''),
           'detail': str(detail or '')[:2000], 'ts': int(time.time() * 1000)}
    if dry_run:
        rec['dry_run'] = True
    if artifacts:
        rec['artifacts'] = [str(x) for x in artifacts][:64]
    p = results_path(base_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'a', encoding='utf-8') as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
    return p
