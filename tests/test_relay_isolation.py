# -*- coding: utf-8 -*-
"""新增测试：多个 relay 服务并发时，各自的开关必须隔离

背景（2026-10-25 压力测试抓到的真实竞态）
------------------------------------------
CPU 满载下连跑 15 轮，第 6 轮红在
    assert relay_server.ACTIONS_ALLOWED is False

根因不是测试写得烂，是**产品自己的竞态**：
    create_server() 里 `global ACTIONS_ALLOWED; ACTIONS_ALLOWED = bool(enable_actions)`
    请求处理里 `if not ACTIONS_ALLOWED: return 403`
同一进程里跑两个服务时，后启动的会把前一个的闸门开关改掉。
生产上「起第二个实例」也会踩到，不只是测试。

修法：开关绑到处理器类的 `actions_allowed` 上，请求处理读实例属性。

⛔ 判据必须能证伪：先起 A（关），再起 B（开），然后回头问 A ——
   修之前 A 会放行（闸门失效），修之后 A 必须仍返回 403。
   只在"B 能开"上断言是测不出这个 bug 的。
"""
import http.client
import json
import os
import socket
import sys
import tempfile
import threading
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, 'collab')):
    if p not in sys.path:
        sys.path.insert(0, p)

import relay_log      # noqa: E402
import relay_server   # noqa: E402


def _start(enable_actions, monkeypatch=None):
    tmp = tempfile.mkdtemp(prefix='iso_srv_')
    lg = relay_log.RelayLog(os.path.join(tmp, 'log.jsonl'))
    # 模块级全局仍会被 create_server 赋值；测试跑完必须还原，
    # 否则 conftest 的 _guard_actions_allowed_global 会判红（那条守卫是对的）。
    # 用 monkeypatch 让它自动还原 —— 与 EXP.0104「mock 必须可自动恢复」同族。
    if monkeypatch is not None:
        monkeypatch.setattr(relay_server, 'ACTIONS_ALLOWED', False, raising=False)
    httpd, port = relay_server.create_server(lg, '127.0.0.1', 0, ui_path='',
                                             enable_actions=enable_actions)
    httpd.daemon_threads = True
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    _wait_ready(port)
    return httpd, port, th


def _wait_ready(port, timeout=5.0):
    """等端口真的能连上。

    ⚠ 2026-10-29：原来这里是**静默超时** —— 5 秒连不上就 break 出去直接 return，
      什么都不报。而 tests/test_write_endpoints.py 的 _wait_ready 会 raise
      （那条 10-25 修过）。两处脚手架不一致 ⇒ 红的时候分不清是
      「压根没就绪」还是「连上了又被断」，只能靠猜。这里对齐成会 raise。
    """
    last = None
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.25):
                return
        except OSError as exc:
            last = exc
            time.sleep(0.02)
    raise TimeoutError('端口 %d 在 %.1f 秒内没就绪（最后错误：%s）' % (port, timeout, last))


#: 只重试这三类**传输层**偶发（握手后立刻被断）。
#: ⛔ 故意不含 http.client.HTTPException —— 那是协议层（状态行/响应格式）问题，
#:   拿它重试会把「服务端真的回了错东西」也一并糊过去。
#:   有 test_retry_scope_is_transport_only 钉住这条边界。
_TRANSPORT_ERR = (ConnectionAbortedError, ConnectionResetError,
                  http.client.RemoteDisconnected)


def _post(port, path, body=None, attempts=3):
    """POST 一次。传输层偶发（连上就被断）重试，**HTTP 状态一律不重试**。

    ⛔ 为什么这个重试不掩盖真问题：
       403 / 200 是 `getresponse()` **正常返回**的 status，根本走不到 except
       ⇒ 重试只发生在「一个字节响应都没拿到」的情况，断言语义不变。
    """
    last = None
    for i in range(max(1, attempts)):
        c = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        try:
            c.request('POST', path, json.dumps(body or {}).encode('utf-8'),
                      headers={'Content-Type': 'application/json'})
            r = c.getresponse()
            raw = r.read().decode('utf-8', 'replace')
            return r.status, raw
        except _TRANSPORT_ERR as exc:
            last = exc
            time.sleep(0.05 * (i + 1))
        finally:
            c.close()
    raise last


def _health_actions(port, attempts=3):
    """读 /api/health。与 _post 同口径：只重试传输层，不重试 HTTP 状态。"""
    last = None
    for i in range(max(1, attempts)):
        c = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        try:
            c.request('GET', '/api/health')
            r = c.getresponse()
            d = json.loads(r.read().decode('utf-8') or '{}')
            return d.get('actions')
        except _TRANSPORT_ERR as exc:
            last = exc
            time.sleep(0.05 * (i + 1))
        finally:
            c.close()
    raise last


def test_two_servers_do_not_share_action_switch(monkeypatch):
    """先起关的 A，再起开的 B，回头问 A —— A 必须仍然是 403"""
    hdA, portA, thA = _start(enable_actions=False, monkeypatch=monkeypatch)
    try:
        st, _ = _post(portA, '/api/step')
        assert st == 403, 'A 一开始就该是 403（实际 %s）' % st

        hdB, portB, thB = _start(enable_actions=True, monkeypatch=monkeypatch)
        try:
            # 关键一步：B 启动后是否污染了 A
            stA, bodyA = _post(portA, '/api/step')
            assert stA == 403, (
                'B 启动后 A 的闸门被打开了 —— 模块级全局又被共用（实际 %s，%s）'
                % (stA, bodyA[:120]))

            stB, _ = _post(portB, '/api/step')
            assert stB != 403, 'B 自己的闸门是开的（实际 %s）' % stB

            # health 报的必须是**各自**的状态
            assert _health_actions(portA) is False, 'A 的 health 报成了开'
            assert _health_actions(portB) is True, 'B 的 health 报成了关'
        finally:
            hdB.shutdown()
            hdB.server_close()
            thB.join(timeout=5)
    finally:
        hdA.shutdown()
        hdA.server_close()
        thA.join(timeout=5)


@pytest.mark.parametrize('enable', [False, True])
def test_single_server_switch_matches_argument(enable, monkeypatch):
    """单服务时开关必须等于 create_server 的参数（基础行为别被改坏）"""
    httpd, port, th = _start(enable_actions=enable, monkeypatch=monkeypatch)
    try:
        st, _ = _post(port, '/api/step')
        if enable:
            assert st != 403, '开了动作面却仍 403（实际 %s）' % st
        else:
            assert st == 403, '没开动作面却放行（实际 %s）' % st
        assert _health_actions(port) is enable
    finally:
        httpd.shutdown()
        httpd.server_close()
        th.join(timeout=5)

# ---------------- ③ 兜底必须 fail-closed（2026-10-25 WX-119 §3.1） ----------------

def test_bare_handler_without_switch_attribute_is_closed(monkeypatch):
    """不带 `actions_allowed` 属性的处理器，闸门必须**关**，不许读模块级全局

    背景（微信侧 WX-119 §3.1 实测）：修完实例属性之后，闸门写的是
        if not getattr(self, 'actions_allowed', ACTIONS_ALLOWED):
    兜底仍然回落到模块级全局 —— 而那个全局的语义是
    「**本进程最后一次 create_server 的值**」＝ 别人留下的状态。
    实测：裸 Handler（无该类属性）起服务后 `POST /api/step` **返回 200 放行**。

    ⇒ 安全闸门的兜底只能是 fail-closed。本条锁的就是这个方向。

    ⛔ 判据必须能证伪：先把全局置成 True（模拟"另一个服务刚把它改真了"），
      再让裸 Handler 收到请求 —— 修之前会 200，修之后必须 403。
      只断言"带开关的服务能正常关"是测不出这个 bug 的。
    """
    from http.server import ThreadingHTTPServer

    # 模拟：本进程里刚有别的 create_server(enable_actions=True) 跑过
    monkeypatch.setattr(relay_server, 'ACTIONS_ALLOWED', True, raising=False)
    assert relay_server.ACTIONS_ALLOWED is True

    tmp = tempfile.mkdtemp(prefix='iso_bare_')
    lg = relay_log.RelayLog(os.path.join(tmp, 'log.jsonl'))
    # 关键：这个类**不带** actions_allowed（老用法 / 直接继承 Handler）
    Cls = type('BareHandler', (relay_server.Handler,), {'log': lg, 'ui_path': ''})
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), Cls)
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    _wait_ready(port)          # 同口径：没就绪就明确报错，不静默继续
    try:
        st, body = _post(port, '/api/step')
        assert st == 403, (
            '裸 Handler 兜底读到了模块级全局 True ⇒ 动作端点被放行（%r）：%r'
            % (st, body[:200]))
        assert _health_actions(port) is False, \
            '裸 Handler 的 health 报了 actions=真（应假）'
    finally:
        httpd.shutdown()
        httpd.server_close()


# ---------------- ④ 重试的范围与降级（2026-10-29）----------------

def test_retry_scope_is_transport_only():
    """重试范围必须只有传输层异常，不许把 HTTP 协议异常也包进来

    判据能证伪：若有人图省事把 `http.client.HTTPException` 加进 `_TRANSPORT_ERR`，
    这条立刻红 —— 因为那等于「服务端回了不合规响应也当偶发重试」，
    会把真缺陷糊成"多试几次就好了"。
    """
    assert not issubclass(http.client.HTTPException, _TRANSPORT_ERR), \
        '重试范围太宽：HTTP 协议异常被当成传输层偶发'
    for t in _TRANSPORT_ERR:
        assert issubclass(t, OSError) or t is http.client.RemoteDisconnected, \
            '意外的重试类型：%r' % (t,)


def test_403_is_returned_as_is_without_retry(monkeypatch):
    """动作面关着时，403 必须**原样一次返回**（不许被重试改成别的结果）

    这是上面那个重试的护栏：403 走的是 getresponse() 正常返回，
    永远进不到 except 分支。
    """
    calls = {'n': 0}
    real_post = http.client.HTTPConnection.request

    def counted(self, method, url, *a, **kw):
        calls['n'] += 1
        return real_post(self, method, url, *a, **kw)

    monkeypatch.setattr(http.client.HTTPConnection, 'request', counted)

    hd, port, th = _start(enable_actions=False, monkeypatch=monkeypatch)
    try:
        st, body = _post(port, '/api/step')
        assert st == 403, '动作面关着却没回 403（实际 %s）' % st
        assert calls['n'] == 1, '403 被重试了（实际发了 %d 次请求）' % calls['n']
    finally:
        hd.shutdown()
        hd.server_close()
        th.join(timeout=5)


def test_wait_ready_raises_instead_of_silently_continuing():
    """没被监听的端口必须**明确报错**，不许静默返回

    这是 2026-10-29 修的那处：原来 5 秒连不上就 break 出去直接 return，
    后续请求撞上 WinError 10053，看着像"服务有问题"，其实是"根本没起来"。
    """
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()                      # 立刻释放：该端口上没有服务在听
    with pytest.raises(TimeoutError):
        _wait_ready(port, timeout=0.6)
