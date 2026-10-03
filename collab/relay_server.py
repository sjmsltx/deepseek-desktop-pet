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
