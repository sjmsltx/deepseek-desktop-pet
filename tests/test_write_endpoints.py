# -*- coding: utf-8 -*-
"""条款 IV 两个端点的护栏：`POST /api/pending`（窄写 ✓ E1）＋ `GET /api/assets`（只读 ✓ E3）。

⭐ 最要紧的一条：窄写端点**不受 `--enable-actions` 管** ✓ —— 它必须放在 do_POST 的
   403 闸门**之前** ✗否则不带该开关时界面根本用不了 ✓（本文件第 1 条就是钉这个 ✓）
"""
import http.client
import io
import json
import os
import sys
import threading
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, 'collab')):
    if p not in sys.path:
        sys.path.insert(0, p)

import relay_log  # noqa: E402
import relay_server  # noqa: E402


@pytest.fixture()
def srv(tmp_path, monkeypatch):
    """真起一个只读服务 ✓ 且把 `_BASE_DIR` 指到临时目录（⭐ 绝不污染真仓库 ✗）。

    ⚠️ 两个坑（本批实测）：
      ① `create_server()` 会**写全局 `ACTIONS_ALLOWED`** ✗（每次调用都覆盖 ✓）
         → 故 **先 patch 再 create** ✓，不依赖上一次调用留下的值 ✓
      ② 服务 **不关会漏 socket** ✗（告警里就是它 ✓）→ 收尾 `server_close()` ＋ join ✓
    """
    monkeypatch.setattr(relay_server, '_BASE_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(relay_server, 'ACTIONS_ALLOWED', False, raising=False)
    lg = relay_log.RelayLog(str(tmp_path / 'log.jsonl'))
    httpd, port = relay_server.create_server(lg, '127.0.0.1', 0, ui_path='')
    assert relay_server.ACTIONS_ALLOWED is False, '⭐ create_server 不得把开关置真 ✗'
    httpd.daemon_threads = True
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    # 2026-10-25：原版这里**直接 yield**，没有任何就绪等待 ——
    #   机器忙时第一个请求会撞上 "WinError 10053 你的主机中的软件中止了一个已建立的连接"。
    #   改成真去连一次 TCP，连上才算就绪。
    _wait_ready(port)
    try:
        yield port, tmp_path
    finally:
        httpd.shutdown()
        httpd.server_close()          # ⭐ 关掉监听 socket（防漏 ✓）
        th.join(timeout=5)


def _wait_ready(port, timeout=5.0):
    """等服务**能应答 HTTP**（不只是 TCP 能连）。

    ⚠ 2026-10-31：原来只做 TCP 连接就返回，但 TCP 能连 ≠ accept 之后能正常应答。
      本机 TCP 栈会丢 RST（实测：连一个肯定没监听的端口返回超时而非 ECONNREFUSED），
      所以「握手成功」不代表服务真就绪 ⇒ 第一个 POST 可能撞 `WinError 10053`。
      改成用 `GET /api/health`（**幂等**，重试安全）真走一遍 accept→respond。
      这样把「accept 后不能应答」的窗口在夹具里就消化掉，不必对非幂等写做重试。
    """
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        try:
            c = http.client.HTTPConnection('127.0.0.1', port, timeout=0.5)
            try:
                c.request('GET', '/api/health')
                r = c.getresponse()
                r.read()
                if r.status == 200:
                    return
                last = RuntimeError('GET /api/health 返回 %s' % r.status)
            finally:
                c.close()
        except Exception as exc:          # 连接/协议/传输层都要继续等
            last = exc
        time.sleep(0.02)
    raise TimeoutError('端口 %d 在 %.1f 秒内没就绪（最后错误：%r）' % (port, timeout, last))

#: 只重试这三类**传输层**偶发（与 test_relay_isolation.py 同一套口径）。
#: ⛔ 不含 http.client.HTTPException —— 那是协议层，重试会把真缺陷糊过去。
_TRANSPORT_ERR = (ConnectionAbortedError, ConnectionResetError,
                  http.client.RemoteDisconnected)


def _post(port, path, body, connect_attempts=3):
    """POST 一次。**只在「连接都没建立」时重试**，发出请求后一律不重发。

    ⚠ 为什么不能像 `test_relay_isolation._post` 那样整体重试（2026-10-31 修正）：
      `POST /api/pending` 是**非幂等写**。`collab/pending_ops.py:261` 落盘文件名带
      **秒级**时间戳（`%Y%m%d-%H%M%S`）⇒ 跨秒重发两次会落**两个待办文件**
      （实测：同一份请求隔 1.1 秒写两次 → 目录里出现 2 个 .json）。
      那会让 `test_pending_only_queues_never_executes` 以「重复入队」的形态假红，
      症状看起来像产品真 bug，比原来的 10053 更难查。

    ⇒ 因此**只重试 `c.connect()`**：那一刻一个字节都还没发出去，重发绝对安全。
      `request()` 可能已经写出去一部分字节，`getresponse()` 之后更不知道服务端处理到哪
      —— 这两种情况一律不重试，直接抛给断言。

    ⚠ 2026-10-31 二次修正：上一版这里整体 try/except 重试，且**`time` 未导入**
      ⇒ 重试分支一进去就 `NameError`，从没执行过一次（WX-151 §二 指出，我实测确认）。
      那次报的「改后 8/8 绿」只是没撞上 10053，不是修复起了作用。

    ⛔ 为什么不掩盖真问题：断言仍是 `st == 202`；服务端真回错状态照样红。
    """
    last = None
    for i in range(max(1, connect_attempts)):
        c = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        try:
            # 只把「建立连接」放进可重试区：失败时零字节已发送
            c.connect()
        except _TRANSPORT_ERR as exc:
            last = exc
            # 留痕：重试是为了容错，不是为了消音（WX-151 §5.3）
            print('  ⚠ 连接未建立，重试 %d/%d：%r' % (i + 1, connect_attempts, exc))
            c.close()
            time.sleep(0.05 * (i + 1))
            continue
        try:
            c.request('POST', path, body=json.dumps(body).encode('utf-8'),
                      headers={'Content-Type': 'application/json'})
            r = c.getresponse()
            return r.status, json.loads(r.read().decode('utf-8') or '{}')
        finally:
            c.close()
    raise last


def _get(port, path):
    c = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    c.request('GET', path)
    r = c.getresponse()
    return r.status, json.loads(r.read().decode('utf-8') or '{}')


def _req(**kw):
    pl = {'changes': {'name': '甲'}}
    pl.update(kw)
    return {'type': 'project_edit', 'op_id': 'e2e0001', 'payload': pl}


# ── 1. ⭐⭐ 窄写端点**不依赖** `--enable-actions`（闸门顺序铁证 ✓）────────
def test_pending_endpoint_works_without_enable_actions(srv):
    port, base = srv
    # ⭐ 自诊断：偶发时能把现场说清（免以后再靠猜 ✗）
    assert relay_server.ACTIONS_ALLOWED is False, \
        '本用例前提：动作端点**关闭** ✓（实测 = %r）' % relay_server.ACTIONS_ALLOWED
    st, body = _post(port, '/api/pending', _req())
    assert st == 202 and body.get('ok') is True, \
        '⭐ 关着 --enable-actions 也必须能用 ✓（实测 status=%s body=%s）' % (st, body)
    assert body.get('queued') is True
    # ⭐ 而其它动作端点仍被 403 挡住（闸门本身没坏 ✓）
    st2, b2 = _post(port, '/api/step', {})
    assert st2 == 403, '⛔ 其它动作端点不得因此被放开 ✗（实测 status=%s body=%s）' % (st2, b2)


# ── 2. ⭐ 只落文件、**不执行**（不产 project.json ✓ 不产 results ✓）─────
def test_pending_only_queues_never_executes(srv):
    port, base = srv
    st, body = _post(port, '/api/pending', _req())
    assert st == 202
    pend = base / 'collab' / 'pending'
    files = [f for f in os.listdir(pend) if f.endswith('.json')]
    assert len(files) == 1 and body['file'] == files[0]
    assert not (base / 'rt' / 'project.json').exists(), '⛔ 端点**不得执行** ✗'
    assert not (pend / 'results.jsonl').exists(), '⛔ 端点**不得**写结果 ✗'


# ── 3. ⭐ 拒即明报（类型枚举 / 未知字段 / 越界路径 三种）✗ 不静默 ──────
@pytest.mark.parametrize('bad, kw', [
    ({'type': 'shell', 'op_id': 'x0001', 'payload': {}}, '枚举'),
    ({'type': 'project_edit', 'op_id': 'x0001', 'payload': {'changes': {'evil': 1}}}, '未知字段'),
    ({'type': 'project_edit', 'op_id': 'x0001',
      'payload': {'changes': {'outputs': '../../x'}}}, '..'),
    ({'type': 'project_edit', 'op_id': 'x0001', 'payload': {'changes': {'root': 'C:/no/such/x'}}}, 'root'),
])
def test_pending_rejects_with_reason(srv, bad, kw):
    port, base = srv
    st, body = _post(port, '/api/pending', bad)
    assert st == 400 and body.get('ok') is False
    assert kw in json.dumps(body, ensure_ascii=False), '⭐ 必须说清原因 ✗'


# ── 4. ⭐ 载荷过大 → 413 ✓（不无限吃内存 ✓）──────────────────────────
def test_pending_oversize_rejected(srv):
    port, base = srv
    c = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    blob = b'{"x":"' + b'a' * (relay_server.MAX_PENDING_BYTES + 10) + b'"}'
    c.request('POST', '/api/pending', body=blob, headers={'Content-Type': 'application/json'})
    r = c.getresponse()
    assert r.status == 413


# ── 5. ⭐ `/api/assets` 最严形态：只有布尔 ✓ 无路径/大小/时间/内容 ──────
def test_assets_payload_strict_shape(tmp_path):
    for root, role, files in (('assets', 'flash', ['flash_idle.png', 'flash_happy_alpha.png']),
                              ('assets_3.0', 'deepseek', ['deepseek_idle.png',
                                                          'deepseek_idle_chroma.png',
                                                          'deepseek_idle_alpha.png'])):
        d = tmp_path / root / role
        d.mkdir(parents=True)
        for f in files:
            (d / f).write_bytes(b'x')
    got = relay_server.assets_payload(base_dir=str(tmp_path))
    assert got['flash']['idle'] == {'white': True, 'chroma': False, 'alpha': False}
    assert got['flash']['happy'] == {'white': False, 'chroma': False, 'alpha': True}
    assert got['deepseek']['idle'] == {'white': True, 'chroma': True, 'alpha': True}
    # ⭐ 递归断言：除角色/状态名外，叶子只能是三个 bool ✓
    for role, states in got.items():
        for st, flags in states.items():
            assert set(flags.keys()) == {'white', 'chroma', 'alpha'}
            assert all(isinstance(v, bool) for v in flags.values()), '⭐ 只能是布尔 ✗'


def test_assets_payload_has_no_paths(srv):
    port, base = srv
    st, body = _get(port, '/api/assets')
    assert st == 200
    blob = json.dumps(body, ensure_ascii=False)
    for bad in ('.png', '/', '\\\\', 'assets_3.0', 'size', 'mtime', 'ts'):
        assert bad not in blob, '⛔ 资产响应里出现了 %r ✗（E3 最严形态 ✓）' % bad


# ── 6. ⭐ 优先级：同角色同名时 `assets/` 覆盖 `assets_3.0/` ✓ ─────────
def test_assets_prefers_effective_dir(tmp_path):
    for root in ('assets', 'assets_3.0'):
        d = tmp_path / root / 'both'
        d.mkdir(parents=True)
        (d / 'both_idle.png').write_bytes(b'x')
    (tmp_path / 'assets_3.0' / 'both' / 'both_idle_chroma.png').write_bytes(b'x')
    got = relay_server.assets_payload(base_dir=str(tmp_path))
    assert got['both']['idle']['white'] is True
    assert got['both']['idle']['chroma'] is False, '⭐ 池子里的绿底不应盖过生效目录 ✗'


# ── 7. ⭐ 反向护栏：端点**不得**自我执行/轮询（源码级 ✓）──────────────
def test_endpoints_do_not_execute():
    with io.open(os.path.join(ROOT, 'collab', 'relay_server.py'), encoding='utf-8') as fh:
        src = fh.read()
    seg = src[src.index('def _post_pending'):src.index('def do_GET')]
    for bad in ('subprocess', 'run_pending', 'os.system', 'popen', 'exec('):
        assert bad not in seg, '⛔ 窄写端点不得执行任何东西 ✗：%s' % bad
    assert 'write_pending' in seg and 'validate_request' in seg



# ── 10. ⭐ 只读 GET /api/pending（界面侧“真三态”所需 ✓ 微信侧提请 ✓）──
def test_get_pending_shows_real_three_states(srv):
    """⭐ 投递 → 人触发 → 结果回写，全过程能被只读端点看见 ✓。"""
    port, base = srv
    st, body = _post(port, '/api/pending', _req())
    assert st == 202
    r0 = _get(port, '/api/pending')[1]
    assert len(r0['pending']) == 1 and r0['pending'][0]['op_id'] == 'e2e0001'
    assert r0['pending'][0]['type'] == 'project_edit'
    assert r0['results'] == [], '⭐ 未跑运行器前无结果 ✓'
    import run_pending
    run_pending.run(str(base))                     # 人触发（真执行）
    r1 = _get(port, '/api/pending')[1]
    assert r1['results'] and r1['results'][0]['ok'] is True
    assert r1['results'][0]['at'], '⭐ 必须给人可读的 at ✓'


def test_get_pending_no_paths(srv):
    """⛔ 只读响应里**不得出现路径** ✗（与 E3 同口径 ✓）。"""
    port, base = srv
    _post(port, '/api/pending', _req())
    blob = json.dumps(_get(port, '/api/pending')[1], ensure_ascii=False)
    assert chr(92) not in blob and str(base) not in blob, '⛔ 不得返路径 ✗'


def test_get_pending_is_read_only(srv):
    """⛔ 只读端点**不得**产生任何文件（反例护栏 ✓）。"""
    port, base = srv
    _get(port, '/api/pending')
    assert not (base / 'collab').exists(), '⛔ 只读端点不得建目录/文件 ✗'
    _post(port, '/api/pending', _req())
    before = sorted(os.listdir(base / 'collab' / 'pending'))
    _get(port, '/api/pending')
    assert sorted(os.listdir(base / 'collab' / 'pending')) == before, '⛔ 读不得改盘 ✗'


def test_get_pending_has_no_secrets(srv):
    port, base = srv
    req = _req()
    req['requested_by'] = 'wechat-side'
    _post(port, '/api/pending', req)
    blob = json.dumps(_get(port, '/api/pending')[1], ensure_ascii=False).lower()
    for bad in ('sk-', 'api_key', 'secret', 'token', 'password'):
        assert bad not in blob, '⛔ 只读响应含敏感字样 %r ✗' % bad
