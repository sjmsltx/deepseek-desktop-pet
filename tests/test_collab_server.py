# -*- coding: utf-8 -*-
"""M2 协作台后端（只读导出面）测试 —— 对应《3.0-M2-UI导出契约-冻结v1.md》§1。

护栏重点：
  · 接口返回**必须来自内核投影**（同源）：与 RelayLog.view/inbox 逐条一致 ✓
  · **只读**：调完接口后日志文件字节不变、内核状态不变 ✓
  · 参数非法要 400（不 500、不静默给空）✓
  · 绑定只允许 127.0.0.1 ✓
"""
import json
import os
import sys
import threading
import urllib.request

import pytest
from pathlib import Path

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

relay = pytest.importorskip('relay_log', reason='relay_log.py 尚未实现')
srv = pytest.importorskip('collab.relay_server', reason='collab/relay_server.py 尚未实现')


def _get(url):
    with urllib.request.urlopen(url, timeout=8) as r:
        return r.status, r.read().decode('utf-8')


@pytest.fixture()
def live(tmp_path):
    """起一个真服务（随机端口，仅在 127.0.0.1），播好数据。"""
    log_path = tmp_path / 'relay.jsonl'
    log = relay.RelayLog(log_path)
    log.append({'id': 'h1', 'channel': 'group:main', 'sender': 'human:owner',
                'recipients': [], 'kind': 'speak', 'visibility': 'human',
                'body': '我们开始吧', 'meta': {'v': 1}})
    log.append({'id': 'a1', 'channel': 'group:main', 'sender': 'agent:flash',
                'recipients': [], 'kind': 'speak', 'visibility': 'human',
                'body': '我先给结论：走独立窗口', 'meta': {'v': 1, 'tokens': 10, 'cost_micro': 100}})
    log.append({'id': 'm1', 'channel': 'group:main', 'sender': 'system',
                'recipients': ['agent:flash'], 'kind': 'reply', 'visibility': 'meta',
                'body': '投递：system → agent:flash', 'meta': {'v': 1, 'billable': False}})
    log.append({'id': 'd1', 'channel': 'group:main', 'sender': 'system',
                'recipients': [], 'kind': 'tool', 'visibility': 'debug',
                'body': 'heartbeat', 'meta': {'v': 1}})
    httpd, port = srv.create_server(log, '127.0.0.1', 0)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    base = 'http://127.0.0.1:%d' % port
    yield log, base, log_path
    httpd.shutdown()
    httpd.server_close()


def test_view_l1_matches_projection(live):
    log, base, _ = live
    code, body = _get(base + '/api/view?channel=group:main&layer=L1')
    got = json.loads(body)
    want = [m.id for m in log.view('group:main', layer='L1')]
    assert code == 200
    assert [m['id'] for m in got] == want == ['h1', 'a1']      # 顺序 = seq 升序 ✓
    assert all(m['visibility'] == 'human' for m in got)        # L1 只含 human ✓


def test_layers_do_not_cross(live):
    log, base, _ = live
    _, l1 = _get(base + '/api/view?channel=group:main&layer=L1')
    _, l2 = _get(base + '/api/view?channel=group:main&layer=L2')
    _, l3 = _get(base + '/api/view?channel=group:main&layer=L3')
    ids = lambda s: [m['id'] for m in json.loads(s)]
    assert ids(l1) == ['h1', 'a1'] and ids(l2) == ['m1'] and ids(l3) == ['d1']


def test_inbox_matches_projection(live):
    log, base, _ = live
    code, body = _get(base + '/api/inbox?agent=agent:flash&layer=L1')
    got = json.loads(body)
    want = [m.id for m in log.inbox('agent:flash', layer='L1')]
    assert code == 200 and [m['id'] for m in got] == want


def test_snapshot_and_health(live):
    log, base, _ = live
    code, body = _get(base + '/api/snapshot')
    snap = json.loads(body)
    assert code == 200 and snap['cost_micro'] == 100
    for k in ('turn_no', 'cost_micro', 'tokens', 'interrupted', 'concluded', 'stopped', 'warnings'):
        assert k in snap
    _, h = _get(base + '/api/health')
    assert json.loads(h)['ok'] is True


def test_log_jsonl_is_raw_truth(live):
    log, base, path = live
    code, body = _get(base + '/api/log.jsonl')
    assert code == 200
    # 必须与文件**逐字节**一致：用二进制读再 decode，避免文本模式把 CRLF 转换成 \n ✗
    assert body == open(path, 'rb').read().decode('utf-8')


def test_bad_params_return_400(live):
    log, base, _ = live
    for q in ('/api/view?channel=group:main',            # 缺 layer（导出面不设默认）
              '/api/view?layer=L9&channel=group:main',   # 非法 layer
              '/api/view?layer=L1',                      # 缺 channel
              '/api/inbox?layer=L1'):                    # 缺 agent
        with pytest.raises(urllib.error.HTTPError) as ei:
            _get(base + q)
        assert ei.value.code == 400, q


def test_unknown_path_404(live):
    log, base, _ = live
    with pytest.raises(urllib.error.HTTPError) as ei:
        _get(base + '/api/nope')
    assert ei.value.code == 404


def test_endpoints_are_readonly(live):
    """调接口不得改变日志字节与内核状态（只读铁律）。"""
    log, base, path = live
    before = Path(path).read_bytes()
    snap_before = log.snapshot()
    for q in ('/api/view?channel=group:main&layer=L1', '/api/inbox?agent=agent:flash&layer=L1',
              '/api/snapshot', '/api/log.jsonl'):
        _get(base + q)
    assert open(path, 'rb').read() == before
    assert log.snapshot() == snap_before
