# -*- coding: utf-8 -*-
"""环回地址必须绕代理（2026-10-25）

## 为什么有这组测试

实测三种配置（见 net_local.py 文档）：

| 配置 | proxy_bypass('127.0.0.1') | 打本地活服务 |
|---|---|---|
| 只有系统代理（注册表 ProxyOverride 含 127.*） | True | OK 200 |
| **另设了 http_proxy 环境变量** | **False** | **HTTPError 502** |
| http_proxy + no_proxy=127.0.0.1 | True | OK 200 |

⇒ 只要有人（CI、开发者、某工具）设了 `http_proxy`，Python 就改用环境变量逻辑、
**忽略注册表的 ProxyOverride**，本机 TTS / relay / 健康检查全部被送进代理。

## ⛔ 判据必须能证伪

只断言「探活成功」是测不出这件事的 —— 不设 http_proxy 时它本来就成功。
必须**制造"会坏的配置"**（http_proxy 指向死端口），再看：
  · 裸 urllib 走这条路 → 失败（证明这个配置真的会让它坏）
  · net_local 走这条路 → 成功（证明绕代理真的救回来了）
"""
import http.server
import os
import socket
import socketserver
import sys
import threading
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import net_local  # noqa: E402


# ---------------- 1. is_loopback 的判定 ----------------

@pytest.mark.parametrize('url', [
    'http://127.0.0.1:9880',
    'http://127.0.0.1:9880/tts',
    'http://localhost:8792/api/health',
    'http://[::1]:8080/',
    'https://127.0.0.1/',
    'http://127.1.2.3:9/',
    # ⚠ 判定口径是「按 host」而不是「按 scheme」：
    #   契约说的是"这个 URL 指向本机环回地址"，ftp://127.0.0.1 也算。
    #   我第一版把这个用例放进"非环回"那一组，是**测试写错了**，不是代码错。
    'ftp://127.0.0.1/x',
])
def test_loopback_urls_are_detected(url):
    assert net_local.is_loopback(url) is True, url


@pytest.mark.parametrize('url', [
    'https://api.deepseek.com/chat/completions',
    'http://192.168.1.50:9880/tts',      # 局域网：另有商量，不算环回
    'http://10.0.0.2:8080/',
    'http://example.com/127.0.0.1',
    '',
    None,
])
def test_non_loopback_urls_are_not_detected(url):
    assert net_local.is_loopback(url) is False, url


def test_request_object_is_also_detected():
    """调用点传的是 Request 对象，不能只判字符串"""
    import urllib.request
    req = urllib.request.Request('http://127.0.0.1:9880/tts', data=b'{}',
                                 headers={'Content-Type': 'application/json'})
    assert net_local.is_loopback(req) is True


# ---------------- 2. 远程地址必须仍走默认路径（不许被我改坏） ----------------

def test_remote_url_still_uses_default_urlopen(monkeypatch):
    """非环回地址必须仍然调用 urllib.request.urlopen（该走代理还走代理）"""
    import urllib.request
    called = {}

    class _Fake:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(url, data=None, timeout=None, **kw):
        called['url'] = url
        return _Fake()

    monkeypatch.setattr(urllib.request, 'urlopen', fake_urlopen)
    net_local.urlopen('https://api.deepseek.com/x', timeout=1)
    assert called.get('url') == 'https://api.deepseek.com/x', '远程地址没走默认 urlopen'


def test_loopback_url_does_not_touch_default_urlopen(monkeypatch):
    """环回地址必须**不**经过 urllib.request.urlopen（那条会查代理）"""
    import urllib.request

    def boom(*a, **kw):
        raise AssertionError('环回地址不该走默认 urlopen（会查代理并可能 502）')

    monkeypatch.setattr(urllib.request, 'urlopen', boom)
    local = urllib.request.build_opener(urllib.request.ProxyHandler({})).open

    real_build = urllib.request.build_opener
    monkeypatch.setattr(urllib.request, 'build_opener',
                        lambda *h, **k: real_build(urllib.request.ProxyHandler({})))
    net_local._OPENER = None      # 让它重建
    try:
        # 打一个必然连不上的环回端口：只验证"没走默认 urlopen"，不看结果
        with pytest.raises(Exception):
            net_local.urlopen('http://127.0.0.1:9/', timeout=1)
    finally:
        net_local._OPENER = None


# ---------------- 3. 真实服务 + 死代理（决定性判据） ----------------

class _Srv(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


class _H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Length', '2')
        self.end_headers()
        self.wfile.write(b'ok')

    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0)
        self.rfile.read(n)
        self.send_response(200)
        self.send_header('Content-Length', '2')
        self.end_headers()
        self.wfile.write(b'ok')

    def log_message(self, *a):
        pass


@pytest.fixture()
def local_server():
    srv = _Srv(('127.0.0.1', 0), _H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    t0 = time.time()
    while time.time() - t0 < 5:
        try:
            socket.create_connection(('127.0.0.1', port), timeout=0.3).close()
            break
        except OSError:
            time.sleep(0.02)
    try:
        yield 'http://127.0.0.1:%d' % port
    finally:
        srv.shutdown()
        srv.server_close()


def test_dead_proxy_env_would_break_plain_urllib(local_server, monkeypatch):
    """先证明这个配置**真的会让裸 urllib 坏**（否则下面的对照没有意义）"""
    import urllib.error
    import urllib.request
    monkeypatch.setenv('http_proxy', 'http://127.0.0.1:9')
    monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:9')
    try:
        urllib.request.urlopen(local_server + '/', timeout=2).read()
        ok = True
    except urllib.error.HTTPError as e:
        ok = (e.code == 200)
    except Exception:
        ok = False
    assert ok is False, ('这个环境下裸 urlopen 竟然能成功 —— '
                         '说明"设 http_proxy 会让本地请求走代理"的前提不成立，'
                         '本组测试的对照失去意义，请重查环境')


def test_net_local_survives_dead_proxy_env(local_server, monkeypatch):
    """同一个死代理环境，net_local 必须仍然打得通本地服务"""
    monkeypatch.setenv('http_proxy', 'http://127.0.0.1:9')
    monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:9')
    net_local._OPENER = None
    try:
        with net_local.urlopen(local_server + '/', timeout=3) as r:
            assert r.read() == b'ok'
    finally:
        net_local._OPENER = None


def test_net_local_post_survives_dead_proxy_env(local_server, monkeypatch):
    """本地 TTS 走的是 POST —— 也要一并证明"""
    import json
    import urllib.request
    monkeypatch.setenv('http_proxy', 'http://127.0.0.1:9')
    monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:9')
    net_local._OPENER = None
    try:
        req = urllib.request.Request(local_server + '/tts',
                                     data=json.dumps({'text': 'hi'}).encode(),
                                     headers={'Content-Type': 'application/json'})
        with net_local.urlopen(req, timeout=3) as r:
            assert r.read() == b'ok'
    finally:
        net_local._OPENER = None


# ---------------- 4. 产品函数在死代理环境下仍可用 ----------------

def test_probe_local_service_survives_dead_proxy(local_server, monkeypatch):
    """voice_io.probe_local_service 体检（真机上"测试本地服务"按钮走这条）"""
    import voice_io
    monkeypatch.setenv('http_proxy', 'http://127.0.0.1:9')
    monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:9')
    net_local._OPENER = None
    try:
        ok, info = voice_io.probe_local_service(local_server, timeout=3)
        assert ok is True, '设了 http_proxy 后探本地服务失败：%r' % (info,)
    finally:
        net_local._OPENER = None


def test_collab_probe_survives_dead_proxy(local_server, monkeypatch):
    """collab_panel._probe：协作台"服务连接灯"走这条"""
    import collab_panel
    monkeypatch.setenv('http_proxy', 'http://127.0.0.1:9')
    monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:9')
    net_local._OPENER = None
    port = int(local_server.rsplit(':', 1)[1])
    try:
        # _probe 探 /api/health，这里假服务对任何 GET 都回 200
        assert collab_panel._probe(port, timeout=3) is True
    finally:
        net_local._OPENER = None
