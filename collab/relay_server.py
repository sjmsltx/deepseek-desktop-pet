# -*- coding: utf-8 -*-
"""3.0 · M2 协作台后端（只读导出面）—— 依《3.0-M2-UI导出契约-冻结v1.md》。

职责：把内核（relay_log.RelayLog）的投影**原样**暴露成 JSON，供前端渲染 + 供复核脚本做
"渲染 ↔ 后端投影 ↔ 日志真相"三方比对。

硬约束（契约冻结，不得违反）：
  · **只读**：绝不写日志、绝不改内核状态（不调 step/interrupt/resume）
  · **不做二次过滤/重排**：接口返回必须直接来自 RelayLog 的投影（否则"同源"无从验证）
  · **只监听 127.0.0.1**（绝不 0.0.0.0）—— 本机工具，不对外暴露
  · 只用标准库（http.server），不引入新依赖

接口：
  GET /api/view?channel=<c>&layer=L1|L2|L3   → Msg[]        （同 RelayLog.view）
  GET /api/inbox?agent=<a>&layer=L1|L2|L3    → Msg[]        （同 RelayLog.inbox）
  GET /api/snapshot                          → dict         （同 RelayLog.snapshot）
  GET /api/log.jsonl                         → text/plain   （原始日志，真相源）
  GET /api/health                            → {ok, path, seq, msgs}
  GET /api/assets                            → {role:{state:{white,chroma,alpha}}}（条款 IV E3 ✓）
  POST /api/pending                          → 窄写端点：只落 collab/pending/（条款 IV E1 ✓）
  GET /           或 /index.html             → 静态前端（collab/index.html，若存在）

用法：
  python collab/relay_server.py --log <日志路径> [--port 0] [--open]
  （--port 0 = 让系统分配端口，打印实际端口）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import relay_log as relay  # noqa: E402

LAYERS = ('L1', 'L2', 'L3')

# 动作端点默认关闭：默认只暴露**只读**导出面（契约 v1）；
# 需 --enable-actions 才打开（契约补遗 v2：/api/step /api/interrupt /api/resume）
ACTIONS_ALLOWED = False


def demo_provider(msg, issue):
    """演示用 provider：**不发任何真实请求**，返回固定回复（用于 UI/复核自动化）。

    特点：内容里带新数字与实体 → 不会误触“无新信息”收敛；可被 --max-turns 停下。
    """
    n = getattr(demo_provider, 'n', 0) + 1
    demo_provider.n = n
    return relay.ProviderReply(
        body='（演示回复 %d）基于议题「%s」，我建议先做方案 %d：把动作端点独立开关，'
             '默认只读、需要时才开；验证指标：接口 200 率 100%%，回合 %d/8。'
             % (n, getattr(issue, 'title', ''), (n % 3) + 1, n),
        tokens=40 + n, cost_micro=120 + n * 5,
        meta={'model': 'demo-provider', 'latency_ms': 300 + n * 10},
    )


def _msg(m) -> dict:
    """Msg → 契约规定的字段集（与内核一一对应，不增不减核心字段）。"""
    return {
        'id': m.id, 'seq': m.seq, 'ts': m.ts, 'channel': m.channel,
        'sender': m.sender, 'recipients': list(m.recipients), 'kind': m.kind,
        'visibility': m.visibility, 'body': m.body, 'meta': dict(m.meta),
    }


# ── ⭐ 条款 IV（写回协议 · Owner 2026-10-03 23:01/23:04 已批 ✓）─────────────
#   E1：唯一**窄写**端点 `POST /api/pending` —— ⭐ 必须放在 do_POST 的 403 闸门**之前** ✓
#       （它是契约特批的“只落待办、不执行”通道 ✓ 不该受 --enable-actions 管 ✗）
#   E3：只读端点 `GET /api/assets` —— ⭐ 最严形态：仅 `{role→state→{white,chroma,alpha}}` ✓
#       ⛔ 不含图片内容 ✗ ⛔ 不含路径 ✗ ⛔ 不含大小/时间 ✗
MAX_PENDING_BYTES = 64 * 1024          # 待办载荷上限 ✓（远超真实需要 ✓）
_ASSET_ROOTS = ('assets', 'assets_3.0')   # ⭐ assets 生效目录优先 ✓ 素材池次之 ✓


def assets_payload(base_dir: str = '') -> dict:
    """⭐ `{角色: {状态: {white, chroma, alpha}}} `—— **只有布尔** ✓（条款 IV E3 ✓）。

    · `white`  = `<名>_<状态>.png` ✓ ｜ `chroma` = `_chroma.png` ✓ ｜ `alpha` = `_alpha.png` ✓
    · ⛔ 不返回路径/大小/时间/图片内容 ✗（最严形态 ✓）
    · 同角色同名时 **`assets/` 优先** ✓（与渲染侧 `_asset_dir_for()` 同口径 ✓）
    """
    base = str(base_dir or _BASE_DIR)
    out = {}
    for root in _ASSET_ROOTS:
        rp = os.path.join(base, root)
        if not os.path.isdir(rp):
            continue
        for role in sorted(os.listdir(rp)):
            rd = os.path.join(rp, role)
            if not os.path.isdir(rd):
                continue
            # ⭐ 先到的根（`assets/`）**整角色占位** ✓ 后到的池子**不再合并** ✗
            #    —— 与渲染侧 `_asset_dir_for()` 同口径：找到第一个存在的目录就全用它 ✓
            if role in out:
                continue
            states = out.setdefault(role, {})
            try:
                names = os.listdir(rd)
            except OSError:
                continue
            for fn in names:
                if not fn.lower().endswith('.png') or not fn.startswith(role + '_'):
                    continue
                stem = fn[len(role) + 1:-4]                 # 去掉 `<role>_` 与 `.png`
                kind = 'white'
                for suf, k in (('_chroma', 'chroma'), ('_alpha', 'alpha')):
                    if stem.endswith(suf):
                        stem, kind = stem[:-len(suf)], k
                        break
                st = states.setdefault(stem, {'white': False, 'chroma': False, 'alpha': False})
                st[kind] = True                              # ⭐ 只置布尔 ✓
    return out


def _pending_base() -> str:
    """⭐ 待办目录（＝ `<仓库根>/collab/pending` ✓）。

    ⚠️ 坑（本批测试逮住的真 bug ✗）：`pending_ops.write_pending(base_dir=…)` 的语义是
    **“待办目录本身”** ✓ 而不是仓库根 ✗ —— 早先传仓库根会把待办甩到仓库根下 ✗
    （虽不越权 ✓，但落点偏了 ✗ 界面侧也找不到 ✓）
    """
    return os.path.join(_BASE_DIR, 'collab', 'pending')


# ── ⭐ 批 4 前置三端点（Owner 2026-10-03 ｜ WX-桌宠-20261003-06 §五 · 我方选路 A）
#   全部在契约 ④-1 已预留的白名单内 ✓ **只读** ✓ 不新增写端点 ✗（守 C1 ✓）
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def roles_payload(base_dir: str = '') -> list:
    """角色列表（⭐ 取自档案 ✓ 只输出 key／显示名／立绘前缀／颜色 ✓ **绝不含密钥** ✗）。

    · 立绘前缀 v1 = **`key` 派生** ✓（= 资产目录名 ✓）→ 不必等新字段 `portrait_prefix` ✓
    · 档案来源：`model_registry.BUILTIN_PROFILES` ＋ `models.json.profiles` 覆盖 ✓
    · ⭐ 受保护导入：服务侧须能在**无 GUI 环境**独立跑 ✓（导入失败 → 空表，不崩 ✗）
    · ⛔ 不输出 `endpoint` / `api_key_field` / `params` / `price`（契约 ④-2 只列四项 ✓）
    """
    import json as _json_mod                      # 局部导入 ✓ 不依赖模块头部 ✗
    import sys as _sys_mod
    base = str(base_dir or _BASE_DIR)
    profs = {}
    try:
        import model_registry as _mr              # ⭐ 该模块明确不依赖 PySide6 ✓
        raw = getattr(_mr, 'BUILTIN_PROFILES', None)
        # ⚠️ 实测：出厂档案是 **list[dict]**（含 key ✓）而非 dict ✗ → 两种形状都认 ✓
        if isinstance(raw, dict):
            profs = {str(k): (v if isinstance(v, dict) else {}) for k, v in raw.items()}
        elif isinstance(raw, (list, tuple)):
            profs = {str(p.get('key')): p for p in raw
                     if isinstance(p, dict) and p.get('key')}
    except Exception as _exc:
        # ⭐ 风险 1 第二批：**失败不得静默** ✗ —— 否则界面显示“无角色”却无线索 ✓
        _sys_mod.stderr.write('[relay_server] 角色档案导入失败（%s）：%r → 本次返回空表\n'
                              % (type(_exc).__name__, _exc))
        profs = {}
    try:
        with open(os.path.join(base, 'models.json'), encoding='utf-8') as fh:
            over = (_json_mod.load(fh) or {}).get('profiles') or {}
        if isinstance(over, dict):
            for k, v in over.items():
                if isinstance(v, dict):
                    profs.setdefault(str(k), {}).update(v)
        elif isinstance(over, (list, tuple)):      # ⭐ 同样两种形状都认 ✓
            for v in over:
                if isinstance(v, dict) and v.get('key'):
                    profs.setdefault(str(v['key']), {}).update(v)
    except FileNotFoundError:
        pass                                       # 用户档案可不存在 ✓（出厂档案已兜底 ✓）
    except Exception as _exc:
        _sys_mod.stderr.write('[relay_server] models.json 读取失败（%s）：%r → 仅用出厂档案\n'
                              % (type(_exc).__name__, _exc))
    out = []
    for key, p in profs.items():
        p = p if isinstance(p, dict) else {}
        ap = p.get('appearance') if isinstance(p.get('appearance'), dict) else {}
        out.append({'key': str(key),
                    'display_name': str(p.get('display_name') or key),
                    'portrait_prefix': str(key),           # ⭐ v1 派生 ✓
                    'color': str(ap.get('color') or '')})
    out.sort(key=lambda r: r['key'])
    return out


def projects_payload(base_dir: str = '', log_path: str = '') -> dict:
    """项目列表（v1：**一个默认项目** ✓ 空态可读 ✗ 不返空数组 ✓）。"""
    base = str(base_dir or _BASE_DIR)
    name = os.path.basename(base.rstrip('\\/')) or 'default'
    last = 0
    try:
        if log_path and os.path.isfile(log_path):
            last = int(os.path.getmtime(log_path) * 1000)
    except Exception:
        last = 0
    return {'projects': [{'id': 'default', 'name': name, 'root': base,
                          'unread': 0, 'last_active': last}]}


def project_current_payload(base_dir: str = '', log_path: str = '') -> dict:
    """当前项目 ＋ 边界最小形式（≈ `PROJECT_CONTEXT` ✓ 与 rt_assembler 将来入参同形 ✓）。"""
    proj = projects_payload(base_dir, log_path)['projects'][0]
    return {'project': proj,
            'boundary': {'project_id': proj['id'], 'root': proj['root'],
                         'roles': [r['key'] for r in roles_payload(base_dir)]}}


class Handler(BaseHTTPRequestHandler):
    server_version = 'RelayServer/0.1'
    log: relay.RelayLog = None       # 由 create_server 注入
    ui_path: str = ''                # 静态前端路径（可空）

    # ---- 工具 ----
    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')     # 复核要实时，禁缓存
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode('utf-8'),
                   'application/json; charset=utf-8')

    def _err(self, code: int, msg: str):
        self._json({'error': msg, 'code': code}, code)

    def log_message(self, fmt, *args):      # 静音访问日志（避免污染 stdout）
        pass

    def _layer(self, q: dict) -> str:
        """layer 必须显式传入且合法 —— 导出面不设默认，避免“看起来对”的隐式行为。"""
        vals = q.get('layer')
        if not vals:
            return ''
        layer = vals[0]
        return layer if layer in LAYERS else ''

    # ---- 路由 ----
    def _json_body(self) -> dict:
        try:
            n = int(self.headers.get('Content-Length') or 0)
            raw = self.rfile.read(n) if n else b''
            return json.loads(raw.decode('utf-8')) if raw else {}
        except Exception:
            return {}

    def do_POST(self):
        """动作端点（默认关闭）。只做三件事：推一回合 / 打断 / 继续 —— 全部落到内核公开 API。"""
        u = urlparse(self.path)
        path = u.path.rstrip('/')
        # ⭐ 条款 IV E1：**窄写端点**—— 只落待办文件 ✓ ⛔ 不执行 ✗ ⛔ 不碰领域文件 ✗
        #    必须在下面那个 403 闸门**之前** ✓（它是契约特批通道 ✓ 与 --enable-actions 无关 ✓）
        if path == '/api/pending':
            return self._post_pending()
        if not ACTIONS_ALLOWED:
            return self._err(403, '动作端点未开启（需服务端 --enable-actions）')
        body = self._json_body()
        try:
            if path == '/api/step':
                r = self.log.step()
                return self._json({'ok': r.ok, 'stopped': r.stopped, 'reason': r.reason,
                                   'turn_no': r.turn_no, 'notice_human': r.notice_human,
                                   'cost_micro': r.cost_micro, 'provider_calls': r.provider_calls})
            if path == '/api/interrupt':
                m = self.log.interrupt(str(body.get('body') or '（人类插队）'))
                return self._json({'ok': True, 'id': m.id, 'seq': m.seq,
                                   'interrupted': self.log.snapshot()['interrupted']})
            if path == '/api/resume':
                ok = self.log.resume(str(body.get('text') or '继续'))
                return self._json({'ok': ok, 'interrupted': self.log.snapshot()['interrupted']})
        except Exception as exc:
            return self._err(500, repr(exc))
        return self._err(404, '未知动作：%s' % path)

    def _post_pending(self):
        """⭐ 窄写端点（条款 IV E1 **七约束** ✓）：**只落待办** ✗ 不执行 ✗ 不碰领域文件 ✗。

    ① 类型枚举（`pending_ops.validate_request` 把关 ✓）② 只写 `collab/pending/` ✓
    ③ 载荷含绝对路径/`..` 即拒 ✗（`root` 唯一例外 ✓）④ **只落文件不执行** ✗
    ⑤ 单写者（运行器归人 ✓）⑥ 失败必落结果（运行器职责 ✓）⑦ 人触发 ✓
    拒即**明报原因** ✓ 绝不静默 ✗
        """
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except Exception:
            n = 0
        if n > MAX_PENDING_BYTES:
            # ⚠️ 抖动根因：不读请求体就回包 ✗ → 客户端还在发大包 → 连接被 reset ✗
            #    （实测：单跑绿 ✓ 全量里偶发 ConnectionError ✗）→ ⭐ **有界排空**再回 ✓
            try:
                left = min(n, MAX_PENDING_BYTES * 2)
                while left > 0:
                    chunk = self.rfile.read(min(65536, left))
                    if not chunk:
                        break
                    left -= len(chunk)
            except Exception:
                pass
            return self._err(413, '载荷过大（上限 %d 字节）' % MAX_PENDING_BYTES)
        body = self._json_body()
        if not isinstance(body, dict) or not body:
            return self._err(400, '请求体必须是 JSON 对象')
        try:
            try:
                import pending_ops as _po               # ① 同目录（脚本模式 ✓）
            except ImportError:
                import sys as _s
                _cd = os.path.join(_BASE_DIR, 'collab')
                if _cd not in _s.path:
                    _s.path.insert(0, _cd)
                import pending_ops as _po               # ② 从仓库根导入时 ✓
        except Exception as exc:
            return self._err(500, '待办协议模块不可用：%r' % exc)
        ok, why = _po.validate_request(body)
        if not ok:
            return self._json({'ok': False, 'error': why, 'code': 400}, 400)   # ⭐ 明报 ✗
        try:
            p = _po.write_pending(body, base_dir=_pending_base())
        except Exception as exc:
            return self._err(500, '落待办失败：%r' % exc)
        return self._json({'ok': True, 'op_id': body.get('op_id'),
                           'file': os.path.basename(p), 'queued': True,
                           'note': '已落待办；⭐ 需**人触发**运行器才会执行 ✓'}, 202)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        path = u.path.rstrip('/') or '/'

        if path == '/api/health':
            return self._json({'ok': True, 'log': self.log.path,
                               'seq': self.log.snapshot()['seq'],
                               'msgs': len(self.log.replay())})

        if path == '/api/snapshot':
            return self._json(self.log.snapshot())

        if path == '/api/log.jsonl':
            try:
                with open(self.log.path, 'rb') as fh:
                    return self._send(200, fh.read(), 'application/x-ndjson; charset=utf-8')
            except FileNotFoundError:
                return self._send(200, b'', 'application/x-ndjson; charset=utf-8')

        # ⭐ 批 4 前置：三个**只读**端点（契约 ④-1 已预留 ✓ 只读 ✓ 不新增写端点 ✗）
        if path == '/api/projects':
            return self._json(projects_payload(log_path=self.log.path))

        if path == '/api/project/current':
            return self._json(project_current_payload(log_path=self.log.path))

        if path == '/api/roles':
            return self._json(roles_payload())

        # ⭐ 条款 IV E3：只读资产库存（最严形态：仅三个布尔 ✓ 无路径 ✗）
        if path == '/api/assets':
            return self._json(assets_payload())

        if path in ('/api/view', '/api/inbox'):
            layer = self._layer(q)
            if not layer:
                return self._err(400, 'layer 必须显式传且为 L1/L2/L3')
            if path == '/api/view':
                channel = (q.get('channel') or [''])[0]
                if not channel:
                    return self._err(400, '缺 channel')
                data = [ _msg(m) for m in self.log.view(channel, layer=layer) ]
            else:
                agent = (q.get('agent') or [''])[0]
                if not agent:
                    return self._err(400, '缺 agent')
                data = [ _msg(m) for m in self.log.inbox(agent, layer=layer) ]
            return self._json(data)

        if path in ('/', '/index.html'):
            if self.ui_path and os.path.isfile(self.ui_path):
                with open(self.ui_path, 'rb') as fh:
                    return self._send(200, fh.read(), 'text/html; charset=utf-8')
            return self._send(200, ('<!doctype html><meta charset="utf-8">'
                                    '<title>M2</title><p>前端未就绪（collab/index.html）'
                                    '</p>').encode('utf-8'), 'text/html; charset=utf-8')

        return self._err(404, '未知路径：%s' % path)


def create_server(log: relay.RelayLog, host: str = '127.0.0.1', port: int = 0,
                  ui_path: str = '', enable_actions: bool = False):
    """返回 (httpd, port)。**host 默认且仅建议 127.0.0.1**。"""
    global ACTIONS_ALLOWED
    ACTIONS_ALLOWED = bool(enable_actions)
    cls = type('BoundHandler', (Handler,), {'log': log, 'ui_path': ui_path})
    httpd = ThreadingHTTPServer((host, port), cls)
    return httpd, httpd.server_address[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--log', required=True)
    ap.add_argument('--port', type=int, default=0)
    ap.add_argument('--ui', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html'))
    ap.add_argument('--open', action='store_true')
    ap.add_argument('--enable-actions', action='store_true',
                    help='打开动作端点 /api/step|interrupt|resume（默认只读）')
    ap.add_argument('--demo-provider', action='store_true',
                    help='用不发真实请求的演示 provider（供 UI/复核用）')
    ap.add_argument('--issue-title', default='')
    args = ap.parse_args()

    # ⭐ 门槛第 1 件（Owner 2026-10-02 21:53 批：「成本上限默认值 → 自定义」）
    #   未设置 = 不覆盖默认（仍是不限 ✓）→ 这里**明报一次**（不静默 ✗）
    _limits = relay.load_limits()
    if not _limits:
        print('  ⚠️ 圆桌额度未设置（= 不限）—— 建议在桌宠「设置 → 用量与计费 → 圆桌额度」设一个上限')
    log = relay.RelayLog(args.log, provider=demo_provider if args.demo_provider else None,
                         limits=_limits)
    if args.issue_title:
        log.open_issue(relay.Issue(args.issue_title, '给出 3 条方案并收敛到 1 条', '出现可执行方案即停'))
    httpd, port = create_server(log, '127.0.0.1', args.port, args.ui,
                                enable_actions=args.enable_actions)
    url = 'http://127.0.0.1:%d/' % port
    print('协作台已启动：%s' % url)
    print('  只读导出：/api/view /api/inbox /api/snapshot /api/log.jsonl')
    print('  动作端点：%s' % ('已开启 /api/step /api/interrupt /api/resume'
                              if args.enable_actions else '关闭（默认只读）'))
    if args.open:
        try:
            os.startfile(url)      # 本机默认浏览器
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == '__main__':
    main()
