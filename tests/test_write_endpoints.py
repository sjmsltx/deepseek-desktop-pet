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

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, 'collab')):
    if p not in sys.path:
        sys.path.insert(0, p)

import relay_log  # noqa: E402
import relay_server  # noqa: E402


@pytest.fixture()
def srv(tmp_path, monkeypatch):
    """真起一个只读服务 ✓ 且把 `_BASE_DIR` 指到临时目录（⭐ 绝不污染真仓库 ✗）。"""
    monkeypatch.setattr(relay_server, '_BASE_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(relay_server, 'ACTIONS_ALLOWED', False, raising=False)
    lg = relay_log.RelayLog(str(tmp_path / 'log.jsonl'))
    httpd, port = relay_server.create_server(lg, '127.0.0.1', 0, ui_path='')
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    yield port, tmp_path
    httpd.shutdown()


def _post(port, path, body):
    c = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    c.request('POST', path, body=json.dumps(body).encode('utf-8'),
              headers={'Content-Type': 'application/json'})
    r = c.getresponse()
    return r.status, json.loads(r.read().decode('utf-8') or '{}')


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
    assert relay_server.ACTIONS_ALLOWED is False, '本用例前提：动作端点**关闭** ✓'
    st, body = _post(port, '/api/pending', _req())
    assert st == 202 and body.get('ok') is True, '⭐ 关着 --enable-actions 也必须能用 ✓'
    assert body.get('queued') is True
    # ⭐ 而其它动作端点仍被 403 挡住（闸门本身没坏 ✓）
    st2, _ = _post(port, '/api/step', {})
    assert st2 == 403, '⛔ 其它动作端点不得因此被放开 ✗'


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
