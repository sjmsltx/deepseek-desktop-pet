# -*- coding: utf-8 -*-
"""collab/pending_ops.py —— **待办／结果文件协议**（契约条款 IV **E2** ✓）

用途（只有这一个 ✓）：界面侧把"变更请求"落成**待办文件** ✓；电脑侧**人触发**的运行器消费它 ✓。

⛔ 本模块**不执行任何东西** ✗（执行只在 `run_pending.py` ✓）
⛔ 本模块**不碰领域文件** ✗（`config.json` / `assets/` 一律由运行器按类型改 ✓）
⛔ 不引入任何凭证 ✗（`requested_by` 只存 peer id 引用 ✓ E2 ✓）
"""
from __future__ import annotations

import io
import json
import os
import random
import re
import time

PENDING_DIRNAME = 'pending'                      # ⭐ E1② 只写这一个目录 ✓
RESULTS_NAME = 'results.jsonl'                   # ⭐ E2 只追加 ✓
CLAIMS_NAME = 'claims.jsonl'                     # ⭐ B1/D3-1：claim（执行中）痕迹**只追加** ✓
CLAIM_STALE_S = 300                              # ⭐ claim 超时（秒）⇒ 可回收 ✓
CLAIM_GRACE_S = 30                               # ⭐ ⭐ **宽限期**：⭐ 即便 pid 看起来已死，
                                                 #    ⭐ 也要过这么多秒才允许回收 ✗
                                                 #    （⭐ 起因：⭐ **刚 spawn 的进程 tasklist 还没列到** ✗
                                                 #      ⇒ ⭐ `_pid_alive` 误判为死 ⇒ 误回收他人 claim ✓
                                                 #      ⭐ 实测：8 进程并发时错误地有 3 个拿到 ✗）
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
        except Exception as exc:
            # ⭐ ⭐ 落痕（⭐ 采纳微信侧口径 ✓）：⭐ 此处原本是 `except: continue` **完全静默** ✗
            #   ⇒ ⭐ 现象正好是"⭐ **文件在、`run()` 却看不见**"✗ ⇒ ⭐ 极难查 ✓
            #   ⇒ ⭐ 与"⭐ 关键路径不得静默"同族 ⇒ 至少留痕 ✓（⛔ 不静默 ✓）
            print('  \u26a0\ufe0f 待办 %s **内容不可解析 ⇒ 跳过**（⭐ 文件在但用不了 ✓）：%r'
                  % (fn, exc))
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


# ── ⭐ E14.1 后半：产品**自动**给产出补线名（⛔ 不靠人记 ✗）──────────────────
DEFAULT_LINE = 'PC'          # ⭐ 本侧默认线名（runner 跑在电脑侧 ✓）


def product_line(base_dir: str = '') -> str:
    """线名：优先环境变量 `AC_COLLAB_LINE` ✓ → 再 `<base>/collab/config.json` 的 `collab_line` ✓
    → 兜底 `DEFAULT_LINE` ✓（⛔ 不静默失败 ✗：读不到就用默认 ✓ 且有默认值可判 ✓）。"""
    try:
        v = os.environ.get('AC_COLLAB_LINE', '').strip()
        if v:
            return v
    except Exception as exc:
        print('  ℹ️ 读环境变量 AC_COLLAB_LINE 失败：%r' % (exc,))     # ⭐ 落痕 ✓
    try:
        import json as _json
        p = os.path.join(str(base_dir or os.path.dirname(os.path.abspath(__file__))),
                         'config.json')
        if os.path.isfile(p):
            with open(p, encoding='utf-8') as fh:
                d = _json.load(fh) or {}
            v = str(d.get('collab_line') or '').strip()
            if v:
                return v
    except Exception as exc:
        print('  ℹ️ 读 collab/config.json 失败：%r' % (exc,))          # ⭐ 落痕 ✓
    return DEFAULT_LINE



# ═══════════════════════════════════════════════════════════════════
# ⭐ B1 / D3-1：**「claim（执行中）」态** —— 幂等 ＋ 可回收 ✓
#
# ⭐ 要解决（D3-2 的前置 ✓）：⭐ 现在 `run()` 是"执行 → 落结果" ✗
#    ⇒ ⭐ **两步之间中断** ⇒ 无结果 ⇒ ⭐ 重启会**重做一遍** ✗（**重复执行** ✗）
# ⭐ 做法（⭐ 采纳微信侧 `WX-…-49` §1.2 判据 ✓）：
#    · ⭐ 取待办前**先落 claim** ✓（⭐ `claims.jsonl` **只追加** ✓ 带 `pid` ＋ `ts` ✓）
#    · ⭐ 已被 claim 且**持有者还活着** ⇒ ⭐ **明确跳过并留痕** ✗（⛔ 不静默 ✗）
#    · ⭐ claim **持有者已死** 或**超 `CLAIM_STALE_S`** ⇒ ⭐ **可回收重取** ✓（⭐ 记痕 ✓）
#    · ⭐ 执行完 ⇒ ⭐ 落结果 ＋ **释放 claim** ✓
# ⭐ 判据（真跑 ✓）：⭐ ① 两个运行器并发取同一条 ⇒ **只有一个执行** ✓ 另一个**明确跳过** ✓
#                   ⭐ ② claim 超时回收 ✓ ③ 两进程并发 ⇒ ⭐ **结果条数 = 1** ✓
# ═══════════════════════════════════════════════════════════════════

def claims_path(base_dir: str = '') -> str:
    """⭐ claim 痕迹文件（⭐ 与结果同目录 ✓ 只追加 ✓）。"""
    return os.path.join(_pending_dir(base_dir), CLAIMS_NAME)


def _pending_dir(base_dir: str = '') -> str:
    """⭐ `base_dir_of()` **本身就指向 `pending/`** ✓ ⇒ ⛔ 不要再拼一次 ✗
    （⭐ 我方曾写成 `join(base_dir_of(...), 'pending')` ⇒ **`pending/pending/`** ✗ ⇒
      ⭐ 写 claim 全 FileNotFoundError ✓ —— ⭐ 是"写失败 ⇒ 保守不执行"的兜底**先兜住了** ✓）。"""
    return base_dir_of(base_dir)


def _pid_alive(pid) -> bool:
    """⭐ 进程是否还活着 ✓（⭐ 判不了 ⇒ **当活着** ✗ 保守 ✓：宁可跳过也不重复执行 ✓）。"""
    try:
        pid = int(pid or 0)
    except Exception:
        return True
    if pid <= 0:
        return False
    try:
        if os.name == 'nt':
            import subprocess
            out = subprocess.run(['tasklist', '/FI', 'PID eq %d' % pid],
                                 capture_output=True, text=True, timeout=8)
            return str(pid) in (out.stdout or '')
        os.kill(pid, 0)
        return True
    except Exception:
        return True


def read_claims(base_dir: str = '') -> list:
    """⭐ 读全部 claim 行（⭐ 只读 ✓ 坏行跳过并告警 ✓）。"""
    p = claims_path(base_dir)
    out = []
    if not os.path.isfile(p):
        return out
    try:
        with io.open(p, encoding='utf-8', errors='replace') as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    print('  \u26a0\ufe0f claims 坏行跳过：第 %d 行' % lineno)
    except Exception as exc:
        print('  \u26a0\ufe0f 读 claims 失败：%r' % (exc,))
    return out


def _claims_dir(base_dir: str = '') -> str:
    """⭐ 互斥目录（⭐ 每 op 一个 `<op_id>.claim` 文件 ✓ —— ⭐ 靠 `O_EXCL` **创建即拿锁** ✗）。"""
    return os.path.join(_pending_dir(base_dir), 'claims')


def _claim_file(op_id: str, base_dir: str = '') -> str:
    safe = ''.join(ch if (ch.isalnum() or ch in '-_.') else '_' for ch in str(op_id or ''))
    return os.path.join(_claims_dir(base_dir), '%s.claim' % safe)


def _read_claim(op_id: str, base_dir: str = '') -> dict:
    """⭐ 读 claim ✓ —— ⚠️ ⭐ **`ts` 缺失时必须用文件 `mtime` 兜底** ✗（⭐ 见下 ✓）。

    ⭐ ⭐ 为什么（⭐ 这是**真 race 的根因** ✗・微信侧 `WX-…-58` §二 报的抖动 ✓）：
      ⭐ `claim_op` 是"⭐ `O_EXCL` **创建即拿**"✗ ⇒ ⭐ ⭐ **"创建成功"与"写完内容"之间有窗口** ✗；
      ⭐ 窗口里别人 `O_EXCL` 撞 `FileExistsError` ⇒ ⭐ 读到**空文件** ⇒ ⭐ 旧写法给 `ts=0`
      ⇒ ⭐ `_claim_reclaimable` 算 `age = 1e9` ⇒ ⭐ ⭐ **判成陈旧 ⇒ 立刻回收** ✗
      ⇒ ⭐ 别人删掉持有者的 claim 后**重试** ⇒ ⭐ ⭐ **两个运行器都执行** ✗（实测结果条数 = 2 ✓）。
    ⭐ 对策：⭐ **无 `ts` ⇒ 以文件 `mtime` 当 `ts`** ✗ ⇒ ⭐ 空 claim 落在**宽限期内不可回收** ✓，
      ⭐ 又不会让"真损坏且持有者早死"的 claim **永久卡死** ✓（⭐ mtime 会变老 ✓）。
    """
    p = _claim_file(op_id, base_dir)
    try:
        with io.open(p, encoding='utf-8') as fh:
            rec = json.load(fh) or {}
    except Exception as exc:
        # ⚠️ ⭐ 关键：⭐ 空文件（⭐ "刚建还没写完" ✗）会让 `json.load` **抛错** ✗
        #   ⇒ ⭐ 首版兜底只写在"读成功"那条路上 ⇒ ⭐ **永不执行** ✗（⭐ 编译绿、运行红 ✓）
        #   ⇒ ⭐ 这里必须一并处理 ✓：⭐ 落成空 `rec` ＋ ⭐ 走**同一个** `ts` 兜底 ✓
        print('  \u2139\ufe0f claim %s 内容不可读（⭐ 多为"刚建未写完" ✓）：%r' % (op_id, exc))
        rec = {}
    if not rec.get('ts'):
        try:
            rec['ts'] = os.path.getmtime(p)          # ⭐ mtime 兜底 ✗
        except OSError as exc:
            print('  \u26a0\ufe0f claim %s 取 mtime 失败（⭐ 当作"刚建"✓ 不回收）：%r' % (op_id, exc))
            rec['ts'] = time.time()
    return rec



def _claim_reclaimable(pid, ts, now, stale: int = None, grace: int = None) -> bool:
    """⭐ 该 claim 是否**可回收** ✓ —— ⭐ ⭐ **两条独立路径，都不许过快** ✗。

    ⭐ ① **超 `stale`**（默认 300s）⇒ 可回收 ✓（⭐ 不管 pid 死活 ✓ —— ⭐ "活着但卡死" ✓）
    ⭐ ② ⭐ pid **确实已死** ✗ 且 ⭐ **已过 `grace`**（默认 30s ✓）⇒ 可回收 ✓
    ⭐ ⭐ 为什么 ② 要加宽限期（⭐ 实测教训 ✓）：⭐ **刚 spawn 的进程**，⭐ `tasklist` **还没列到** ✗
       ⇒ ⭐ `_pid_alive` 会**误报"死"** ✗ ⇒ ⭐ 若据此立刻回收 ⇒ ⭐ **误抢他人的 claim** ✓
       （⭐ 实测：⭐ 8 进程并发时错误地有 **3 个**拿到 ✗）
    """
    st = CLAIM_STALE_S if stale is None else stale
    gr = CLAIM_GRACE_S if grace is None else grace
    age = (now - ts) if ts else 1e9
    if age > st:
        return True
    # ⭐ ⭐ 保守化（2026-10-05，⭐ 采纳微信侧口径 ✓）：⭐ ⭐ **"pid 死"只能当参考条件** ✗
    #   ⭐ 可回收 ⇔ ⭐ **年龄 > 宽限** ✗ 且 ⭐ ( pid 死 **或** 读不到 pid ) ✗
    #   ⛔ **不许**「pid 死 ⇒ 立刻可回收」✗（⭐ 就缺了"年龄"这道门 ✓）
    #   ⛔ **不许**「读不到 pid ⇒ 立刻可回收」✗
    #   ⭐ 理由：⭐ `tasklist` 是**快照式**查询 ✗ ⇒ ⭐ **刚 spawn 的进程可能还没被列进去** ✗
    #     ⇒ ⭐ `_pid_alive` 误报"死" ✗ ⇒ ⭐ **活人的 claim 被回收** ✗ ★
    #     （⭐ 本文件上方 docstring 自记：⭐ "⭐ 8 进程并发时错误地有 **3 个**拿到"✗ ✓）
    #   ⭐ 保守化后：⭐ tasklist 误报 ／ 空文件 ／ 刚起的子进程 ⭐ **三者都落进宽限期** ✓，
    #     ⭐ 而真死的持有者**过了宽限照样能回收** ✓（⛔ 不会永久卡死 ✓）。
    if age > gr:
        if not _pid_alive(pid):
            return True
        return False
    return False


def active_claims(base_dir: str = '', stale: int = CLAIM_STALE_S) -> dict:
    """⭐ 当前**有效**的 claim（⭐ `op_id` → 信息 ✓）。

    ⭐ 有效判据：⭐ 持有者 `pid` **还活着** ✗ 且 ⭐ 未超 `stale` ✓
    （⭐ 判不了的 ⇒ **当有效** ✗ 保守 ✓：宁可跳过也不重复执行 ✓）。
    """
    d = _claims_dir(base_dir)
    out = {}
    if not os.path.isdir(d):
        return out
    now = time.time()
    for fn in sorted(os.listdir(d)):
        if not fn.endswith('.claim'):
            continue
        oid = fn[:-len('.claim')]
        info = _read_claim(oid, base_dir)
        pid = info.get('pid')
        ts = float(info.get('ts') or 0)
        if _claim_reclaimable(pid, ts, now):
            continue          # ⭐ 可回收 ⇒ 不算有效 ✓
        out[oid] = info
    return out


def claim_op(op_id: str, line: str = '', base_dir: str = '') -> bool:
    """⭐ 尝试 claim 一条待办 ✓ —— ⭐ ⭐ **原子**（⭐ `O_EXCL` 创建即拿 ✗ 不成即退 ✓）。

    ⭐ 为什么不用"先查后写"✗：⭐ 我方首版就是这么写的 ✓ ⇒ ⭐ **实测两个进程都拿到了** ✗
      （⭐ 并发下 check 与 write 之间有空隙 ✓）⇒ ⭐ 改成 ⭐ **一个 op 一个文件 ＋ `O_EXCL`** ✓
      （⭐ 由**操作系统**保证原子 ✓）。

    返回 `True` = ⭐ 拿到（可执行 ✓）；`False` = ⭐ 别人正持有（⭐ **明确跳过并留痕** ✗）。
    """
    oid = str(op_id or '')
    if not oid:
        return False
    p = _claim_file(oid, base_dir)
    os.makedirs(_claims_dir(base_dir), exist_ok=True)
    rec = {'op_id': oid, 'pid': os.getpid(), 'ts': time.time(),
           'line': line or product_line(base_dir)}
    for _attempt in (1, 2):
        try:
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            info = _read_claim(oid, base_dir)
            pid, ts = info.get('pid'), float(info.get('ts') or 0)
            if _claim_reclaimable(pid, ts, time.time()):
                why = ('超过 %ds 未释放' % CLAIM_STALE_S
                       if (time.time() - ts) > CLAIM_STALE_S else '持有者已退出且已过宽限期')
                print('  \u2139\ufe0f 回收 claim %s（%s ✓；原持有者 pid=%s）' % (oid, why, pid))
                # ⭐ 回收＝删旧 claim ✓：⭐ 撞 `FileNotFoundError` ⇒ ⭐ **别人已先回收** ✓（⭐ 不是失败 ✓）
                #   ⚠️ 但**不能静默** ✗ —— ⭐ 我方第一版写了 `except FileNotFoundError: pass` ✗
                #   ⇒ ⭐ 被对方 `test_no_new_silent_spots` 当场判红 ✓（⭐ 本会话第 7 次同类 ✗）⇒ 加落痕 ✓
                try:
                    os.remove(p)
                except FileNotFoundError as exc:
                    print('  \u2139\ufe0f 旧 claim 已被他人回收（忽略 ✓）：%r' % (exc,))
                except OSError as exc:
                    print('  \u26a0\ufe0f 删旧 claim 失败：%r' % (exc,))
                continue          # ⭐ 重试一次 ✓
            print('  \u2139\ufe0f 待办 %s **已被其他运行器 claim**（pid=%s）⇒ 跳过本次（⛔ 不重复执行 ✗）'
                  % (oid, pid))
            return False
        except OSError as exc:
            print('  \u26a0\ufe0f 创建 claim 失败 ⇒ 本次**不执行**（保守 ✓）：%r' % (exc,))
            return False
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(rec, fh, ensure_ascii=False)
        # ⭐ 复核归属：⭐ 读回来必须还是**我** ✗（⭐ 防"我写完后别人回收并重写"的极窄窗口 ✓）
        if int(_read_claim(oid, base_dir).get('pid') or 0) == os.getpid():
            _audit(base_dir, oid, 'claim', rec)
            return True
        print('  \u2139\ufe0f claim %s 归属已变（被他人接管）⇒ 本次不执行 ✓' % oid)
        return False
    return False


def _audit(base_dir: str, op_id: str, kind: str, extra=None):
    """⭐ 审计痕迹（⭐ `claims.jsonl` **只追加** ✓ 便于回放 ✓ ⛔ 不参与互斥 ✗）。"""
    try:
        rec = {'op_id': str(op_id), 'kind': kind, 'pid': os.getpid(), 'ts': time.time()}
        if extra:
            rec.update({k: v for k, v in extra.items() if k not in rec})
        with io.open(claims_path(base_dir), 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
            fh.flush()
    except Exception as exc:
        print('  \u26a0\ufe0f 写审计痕迹失败（接口本身不受影响 ✓）：%r' % (exc,))


def release_claim(op_id: str, base_dir: str = '') -> bool:
    """⭐ 释放 claim ✓ —— ⭐ ⭐ **只放自己的** ✗（⭐ 核 `pid` ✓ 不误删他人的 ✓ 幂等 ✓）。"""
    oid = str(op_id or '')
    if not oid:
        return False
    p = _claim_file(oid, base_dir)
    info = _read_claim(oid, base_dir)
    if info and int(info.get('pid') or 0) != os.getpid():
        print('  \u26a0\ufe0f claim %s 不是本进程持有（不删 ✓）' % oid)
        return False
    try:
        os.remove(p)
    except FileNotFoundError as exc:
        # ⭐ 已不在＝等价于已释放 ✓ —— ⭐ 但**不静默** ✗（⭐ 留痕 ✓；⭐ 本会话第 8 次同类 ✗）
        print('  \u2139\ufe0f claim 已不在（视为已释放 ✓）：%r' % (exc,))
    except OSError as exc:
        print('  \u26a0\ufe0f 释放 claim 失败：%r' % (exc,))
        return False
    _audit(base_dir, oid, 'release')
    return True


# ═══════════════════════════════════════════════════════════════════
# ⭐ B11 / `D2-4`：⭐ **失败终态 ＋ 死信（DLQ）**（⭐ 采纳微信侧 `WX-…-56` 草稿 6 ✓）
#
# ⭐ 三终态（⛔ 不许"无终态" ✗）：
#     · `ok`     —— ⭐ 成功 ✓（⭐ 承 `E17.3`：⭐ **不重复只对成功项成立** ✗）
#     · `failed` —— ⭐ 已判失败 ✗（⭐ **可重跑** ✓ —— 承"⭐ 失败不算消费" ✓；
#       ⚠️ ⭐ **不自动升级** ✗ —— ⭐ 方案 B：⭐ `failed` **恒为 `failed`** ✓，⭐ 只有**人**能把它
#       ⭐ 标成 `dead` ✗（⭐ 走 `mark_dead()` ✓）✓ —— ⭐ 撞项目内核"⛔ 运行器不得自我驱动" ✓）
#     · `dead`   —— ⭐ ⭐ **重放次数用尽** ✗（⭐ 终止态 ⇒ ⭐ **不再自动重试** ✗）
# ⭐ 死信落点：⭐ 追加进 ⭐ **同一个 `results.jsonl`** ✗（⭐ `kind='dead'` ✓ ⛔ 不另开目录 ✗
#    —— ⭐ 免得"又多一处状态源" ✓ 承 `P5`：⭐ 真相源＝产品自带记录 ✓）。
# ⭐ 计数：⭐ **从结果行数推** ✓（⭐ 不另存 ✓ 单一真相源 ✓）。
# ⭐ 兼容：⭐ 旧字段 `ok` **保留不动** ✗ ＋ ⭐ **只追加 `kind`** ✓。
# ═══════════════════════════════════════════════════════════════════

MAX_REPLAY = 2          # ⚠️ ⭐ **仅供人参考** ✗（⭐ 方案 B 下**不再影响终态** ✓ ——
#                         ⭐ 实现早就回退了自动重放 ✗；⭐ 此常量保留只为"⭐ 建议人何时考虑标死信"✓）


def _kind_of(rec: dict) -> str:
    """⭐ 一条结果行的终态 ✓ —— ⭐ 旧行**没有 `kind`** ✗ ⇒ ⭐ 由 `ok` 推 ✓（⭐ 兼容 ✓）。"""
    k = str((rec or {}).get('kind') or '').strip()
    if k in ('ok', 'failed', 'dead'):
        return k
    return 'ok' if (rec or {}).get('ok') else 'failed'


def op_kind(op_id: str, base_dir: str = '') -> str:
    """⭐ 该 `op_id` 的**最新终态** ✓（⭐ 无记录 ⇒ 空串 ✓）。"""
    latest = ''
    for r in read_results(base_dir):
        if str(r.get('op_id') or '') == str(op_id or ''):
            latest = _kind_of(r)
    return latest


def fail_count(op_id: str, base_dir: str = '') -> int:
    """⭐ 该 `op_id` 已 `failed` 几次 ✓（⭐ 从结果行数推 ✓ 不另存 ✓）。"""
    return sum(1 for r in read_results(base_dir)
               if str(r.get('op_id') or '') == str(op_id or '')
               and _kind_of(r) == 'failed')


def dead_ids(base_dir: str = '') -> set:
    """⭐ 已进死信的 `op_id` ✓（⭐ 终止态 ⇒ ⭐ **不再自动重试** ✗）。

    ⚠️ ⭐ ⭐ **必须"先归一到最新行、再筛"** ✗ —— 这是**追加式历史 ＋ 视图**的经典坑：
      ⭐ 首版直接筛 `kind=='dead'` 的**行** ✗ ⇒ ⭐ 只要历史上出现过 `dead` ⇒ ⭐ 永久算死信 ✗
      ⇒ ⭐ ⭐ **人工重放（`unmark_dead`）形同虚设** ✗（⭐ 放行后 `run` 仍跳过 ✓ —— 实测抓到 ✓）。
    ⭐ 同族判例：⭐ 2026-09-26 我方入库的 `rt_gate.pending()` ✗（⭐ "⭐ 必须先按 `draft_id` 取最新行 ✓"）✓
      ⇒ ⭐ ⭐ **同一坑第二次出现** ✗ ⇒ ⭐ 本处按同一条修 ✓。
    """
    latest = {}
    for r in read_results(base_dir):
        oid = str(r.get('op_id') or '')
        if oid:
            latest[oid] = _kind_of(r)          # ⭐ 后写覆盖先写 ⇒ 最后一次即最新 ✓
    return {oid for oid, k in latest.items() if k == 'dead'}


def replay_allowed(op_id: str, base_dir: str = '') -> tuple:
    """⭐ 人工重放**准入** ✓ —— ⭐ ⭐ **只对 `dead`** ✗；⭐ `ok` **绝不重放** ✗（⭐ 幂等 ✓）。

    ⭐ 返回 `(是否允许, 原因)` ✓ —— ⭐ 不允许时**原因非空** ✗（⛔ 不静默 ✗）。
    """
    k = op_kind(op_id, base_dir)
    if k == 'ok':
        return False, '该待办**已成功**（ok）⇒ ⭐ 绝不重放 ✗（幂等 ✓）'
    if k == 'dead':
        return True, ''
    if k == 'failed':
        return True, ''          # ⭐ 失败项本就允许重试 ✓（承 E17.3 ✓）
    return False, '该待办**没有结果记录** ⇒ 无需重放（⭐ 直接跑运行器即可 ✓）'


def next_kind(ok: bool, fails: int, base_dir: str = '', op_id: str = '',
              max_replay: int = None) -> str:
    """⭐ 由"这次成没成"推**终态** ✓（⭐ 终态口径唯一入口 ✗ 免得到处写 ✓）。

    ⭐ ⭐ 方案 **B**（2026-10-05 双方裁定 ✓）：⭐ **失败恒 `failed`** ✗ ——
      ⛔ ⭐ **不自动推 `dead`** ✗（⭐ `dead` 只由**人显式标** ✓ 见 `mark_dead` ✓）。
    ⚠️ ⭐ 为什么改（⭐ 实测抓到 ✓）：⭐ 原实现是"⭐ 失败次数累到 `MAX_REPLAY` ⇒ 自动 `dead`✗"✗ ⇒
      ⭐ 那是**方案 A 的残留** ✗（⭐ 我方 `8d8104c` 只回退了"同一次 run 内的自动重放"✗，
      ⭐ ⭐ **这条判据漏了** ✓）⇒ ⭐ 实测两行结果是 `failed` ＋ **`dead`** ✗ ⇒ ⭐ 与方案 B **冲突** ✓。
      ⭐ 另：⭐ "⭐ 自动升级状态"✗ 本身撞项目内核（⭐ `test_runner_is_human_triggered_only` ✓
      ＋ ⭐ 微信侧判例 `J34`「⭐ 自动类提案先过"人类触发"这道门」✗ ✓）。
    ⭐ `fails` 参数**保留** ✓（⭐ 调用方仍在传 ✓ 且人工标记时可参考 ✓），⭐ 但**不再影响终态** ✗。
    """
    return 'ok' if ok else 'failed'

def mark_dead(op_id: str, reason: str = '', base_dir: str = '', by: str = '') -> bool:
    """⭐ 人工把一条待办标为**死信** ✗ —— ⭐ ⭐ **方案 B 下 `dead` 的**唯一入口** ✗**。

    ⭐ 依据（⭐ 双方 2026-10-05 裁定 ✓）：
      ⭐ `dead` 是**终止态** ✗ ⇒ ⭐ 只有"⭐ **人显式标**"✗ 才能进 ✓（⛔ 不许自动升级 ✗ ——
      ⭐ 自动类行为撞项目内核 ⭐ `test_runner_is_human_triggered_only` ✓ 与微信侧判例 `J34` ✓）。
    ⭐ 语义：
      · ⭐ 已 `ok` ✗ ⇒ ⭐ **拒绝** ✓（⭐ 成功项不可标死信 ✓ 且**给原因** ✗ ⛔ 不静默 ✓）
      · ⭐ 已在 `dead` ✗ ⇒ ⭐ **幂等** ✓（⭐ 不重复写行 ✓）
      · ⭐ `failed` ／ 无记录 ✗ ⇒ ⭐ 追加一行 `kind='dead'` ✓（⭐ **只追加** ✗ ⛔ 不改旧行 ✓）
    ⭐ 返回 `True` = ⭐ 本次真的标了 ✓；`False` = ⭐ 没标（⭐ 原因已打印 ✓）。
    """
    oid = str(op_id or '')
    if not oid:
        print('  \u26a0\ufe0f `mark_dead` 需要 `op_id` ✗')
        return False
    k = op_kind(oid, base_dir)
    if k == 'ok':
        print('  \u26a0\ufe0f 拒绝标记 %s：⭐ 该待办**已成功（ok）**✗ ⇒ ⛔ 不可标死信 ✓' % oid)
        return False
    if k == 'dead':
        print('  \u2139\ufe0f %s **已在死信**（幂等 ✓ ⇒ 不重复写行 ✓）' % oid)
        return False
    append_result(oid, False, reason=reason or '人工标记死信',
                  detail='mark_dead', base_dir=base_dir,
                  extra={'kind': 'dead', 'by': by or product_line(base_dir)})
    print('  \u2139\ufe0f 已标死信 ✓：%s（%s）' % (oid, reason or '人工标记死信'))
    return True


def unmark_dead(op_id: str, base_dir: str = '') -> bool:
    """⭐ 人工**重放**一条死信 ✓ —— ⭐ 只落痕、不改旧行 ✗（⭐ 承 `replay_allowed` ✓）。

    ⭐ 做法：⭐ 追加一行 `kind='failed'` ✗（⭐ 让"⭐ 最新终态"回到可重跑 ✓）——
      ⚠️ ⭐ 旧 `dead` 行 ⭐ **保留** ✗（⭐ 只追加 ✓ 可回溯 ✓）。
    ⭐ ⛔ **`ok` 项一律拒绝** ✗（⭐ 承 `replay_allowed` ✓ 幂等 ✓）。
    """
    oid = str(op_id or '')
    if not oid:
        print('  \u26a0\ufe0f `unmark_dead` 需要 `op_id` ✗')
        return False
    allow, why = replay_allowed(oid, base_dir)
    if not allow:
        print('  \u26a0\ufe0f 拒绝重放 %s：%s ✓' % (oid, why))
        return False
    append_result(oid, False, reason='人工重放死信', detail='unmark_dead', base_dir=base_dir,
                  extra={'kind': 'failed', 'replayed': True})
    print('  \u2139\ufe0f 已放行重放 ✓：%s（⭐ 下次 `run` 会重新执行 ✓）' % oid)
    return True



def append_result(op_id: str, ok: bool, reason: str = '', detail: str = '', base_dir: str = '',
                  dry_run: bool = False, artifacts=None, line: str = '', extra: dict = None) -> str:
    """⭐ 追加一条结果（**只追加** ✗ 不改旧行 ✓；E1⑥ 失败也必须落 ✓）。

    ⭐ `dry_run=True`：预演结果也落盘 ✓（口径 ③ ✓）—— ⭐ 但它**不算已消费** ✗，
       否则真跑会被“幂等”误跳过 ✗（见 `done_op_ids` 的过滤 ✓）
    """
    rec = {'op_id': str(op_id), 'ok': bool(ok), 'reason': str(reason or ''),
           'detail': str(detail or '')[:2000], 'ts': int(time.time() * 1000)}
    # ⭐ E14.1 后半（产品自动补线名 ✓）：⛔ 不靠人记 ✗ —— 结果行自带"哪条线跑的" ✓
    _ln = str(line or product_line()).strip()
    if _ln:
        rec['line'] = _ln
    if dry_run:
        rec['dry_run'] = True
    if artifacts:
        rec['artifacts'] = [str(x) for x in artifacts][:64]
    if extra:                                   # ⭐ B11：⭐ 只**补** ✗（⛔ 不覆盖既有键 ✗）
        for _k, _v in dict(extra).items():
            rec.setdefault(_k, _v)
    p = results_path(base_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'a', encoding='utf-8') as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
    return p
