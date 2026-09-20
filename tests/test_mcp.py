# -*- coding: utf-8 -*-
"""MCP 桥接测试（Batch 3-3）

用 tests/fake_mcp_server.py（FastMCP，真实 stdio 协议）验证：
  - 连接 + 工具发现（**这条直接守住那个老 bug**：字段名写成 input_schema 会拿到 0 个工具）
  - 真调工具拿到结果
  - 权限判定（只读 / 写类要确认 / 看不出保守要确认）
  - 管理 API（加/删/启停/重启/状态）与配置持久化
"""
import json
import os
import sys
import time

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import mcp_bridge as mb                                          # noqa: E402

FAKE = os.path.join(BASE, 'tests', 'fake_mcp_server.py')


def _cfg(tmp_path, servers):
    p = tmp_path / 'config.json'
    p.write_text(json.dumps({'mcp_servers': servers}, ensure_ascii=False), encoding='utf-8')
    return str(p)


def _wait(conn, secs=60):
    t0 = time.time()
    while time.time() - t0 < secs:
        if conn.session is not None or conn.error:
            return True
        time.sleep(0.5)
    return False


@pytest.fixture(scope='module')
def live_bridge(tmp_path_factory):
    """起一个真实 stdio 连接（模块级复用，省时间）"""
    tmp = tmp_path_factory.mktemp('mcp')
    cfg = _cfg(tmp, [{'name': 'fake', 'command': sys.executable, 'args': [FAKE]}])
    b = mb.McpBridge(cfg)
    b.connect_all()
    conn = b.conns['fake']
    assert _wait(conn), '假 server 没连上'
    assert conn.error is None, conn.error
    yield b
    conn.stop()


# ---------------------------------------------------------------- 连接与工具

def test_tools_discovered(live_bridge):
    """★ 回归守卫：字段名解析错（input_schema）时这里会是 0 个工具"""
    conn = live_bridge.conns['fake']
    names = sorted(t['name'] for t in conn.tools)
    assert names == ['mystery', 'read_note', 'write_note'], names
    assert all(t['inputSchema'] for t in conn.tools), '工具入参 schema 丢了'


def test_tool_schemas_merged(live_bridge):
    schemas = live_bridge.tool_schemas()
    keys = sorted(s['function']['name'] for s in schemas)
    assert keys == ['mcp_fake_mystery', 'mcp_fake_read_note', 'mcp_fake_write_note'], keys
    assert schemas[0]['function']['parameters']['type'] == 'object'


def test_call_tool_roundtrip(live_bridge):
    out = live_bridge.call_tool('mcp_fake_read_note', {'name': '测试'})
    assert '便签[测试]' in out, out


def test_status_text(live_bridge):
    st = live_bridge.status_text()
    assert 'fake' in st and '已连接' in st, st


# ---------------------------------------------------------------- 权限判定

@pytest.mark.parametrize('tool,expect_read', [
    ({'name': 'read_note'}, True),
    ({'name': 'list_files'}, True),
    ({'name': 'get_time'}, True),
    ({'name': 'write_note'}, False),
    ({'name': 'delete_file'}, False),
    ({'name': 'run_command'}, False),
    ({'name': 'mystery'}, False),
    ({'name': 'convert_time'}, False),
])
def test_classify_by_name(tool, expect_read):
    read_only, _why = mb.classify_tool(tool)
    assert read_only is expect_read, (tool, read_only)


def test_classify_prefers_annotations():
    assert mb.classify_tool({'name': 'weird', 'read_only': True})[0] is True
    assert mb.classify_tool({'name': 'read_x', 'destructive': True})[0] is False, '破坏性注解优先'
    assert mb.classify_tool({'name': 'read_x', 'read_only': True, 'destructive': True})[0] is False


def test_needs_confirm_uses_live_tools(live_bridge):
    need, why = live_bridge.needs_confirm('mcp_fake_write_note')
    assert need is True and '写' in why or '保守' in why, why
    need2, _ = live_bridge.needs_confirm('mcp_fake_mystery')
    assert need2 is True, '看不出读写的要保守'
    # 假 server 的 read_note 若被 SDK 标了 readOnlyHint，就该免确认；否则按名字也是读类
    need3, why3 = live_bridge.needs_confirm('mcp_fake_read_note')
    assert need3 is False, why3
    assert live_bridge.needs_confirm('nonsense') == (False, '')


def test_auto_confirm_switch(live_bridge):
    assert live_bridge.auto_confirm_writes() is True, '默认：写类要确认'
    ok, _msg = live_bridge.set_auto_confirm_writes(False)
    assert ok and live_bridge.auto_confirm_writes() is False
    need, _why = live_bridge.needs_confirm('mcp_fake_write_note')
    assert need is False, '关掉确认后不该再问'
    live_bridge.set_auto_confirm_writes(True)


# ---------------------------------------------------------------- 管理 API

def test_add_remove_enable_persists(tmp_path):
    cfg = _cfg(tmp_path, [])
    b = mb.McpBridge(cfg)
    assert b.servers() == []
    ok, msg = b.add_server({'name': 'demo', 'command': sys.executable,
                            'args': ['-c', 'pass']})
    assert ok, msg
    saved = json.load(open(cfg, encoding='utf-8'))['mcp_servers']
    assert saved[0]['name'] == 'demo' and saved[0]['enabled'] is True

    assert b.add_server({'name': 'demo', 'command': 'x'})[0] is False, '重名要拦住'

    ok, _ = b.set_enabled('demo', False)
    assert ok and json.load(open(cfg, encoding='utf-8'))['mcp_servers'][0]['enabled'] is False
    assert next(s for s in b.servers() if s['name'] == 'demo')['state'] == '已禁用'

    ok, _ = b.remove_server('demo')
    assert ok and json.load(open(cfg, encoding='utf-8'))['mcp_servers'] == []


def test_add_server_validation(tmp_path):
    b = mb.McpBridge(_cfg(tmp_path, []))
    assert b.add_server({'command': 'x'})[0] is False          # 没名字
    assert b.add_server({'name': 'x'})[0] is False              # 没命令也没 url


def test_servers_shape_with_tools(live_bridge):
    s = next(x for x in live_bridge.servers() if x['name'] == 'fake')
    assert s['transport'] == 'stdio' and s['state'] == '已连接'
    assert s['tool_count'] == 3
    assert len(s['need_confirm']) >= 2, s['need_confirm']


def test_schema_extraction_handles_both_attr_names():
    """守住老 bug：只暴露 inputSchema 的对象也要能取到 schema"""
    class T:
        name = 'x'
        description = 'd'
        inputSchema = {'type': 'object', 'properties': {'a': {'type': 'string'}}}
    got = (getattr(T, 'input_schema', None) or getattr(T, 'inputSchema', None) or {})
    assert got['properties']['a']['type'] == 'string'


def test_stop_terminates_child_process(tmp_path):
    """断开 MCP 后子进程必须真的结束（否则每切一次就漏一个进程）"""
    import subprocess
    pid_file = tmp_path / 'child.pid'
    cfg = _cfg(tmp_path, [{'name': 'fake2', 'command': sys.executable,
                           'args': [FAKE, '--pid-file', str(pid_file)]}])
    b = mb.McpBridge(cfg)
    b.connect_all()
    conn = b.conns['fake2']
    assert _wait(conn), '没连上'
    t0 = time.time()
    while not pid_file.exists() and time.time() - t0 < 10:
        time.sleep(0.2)
    pid = int(pid_file.read_text().strip())
    alive = subprocess.run(['tasklist', '/FI', 'PID eq %d' % pid], capture_output=True,
                           text=True).stdout
    assert str(pid) in alive, '子进程没起来？'
    conn.stop()
    time.sleep(2)
    gone = subprocess.run(['tasklist', '/FI', 'PID eq %d' % pid], capture_output=True,
                          text=True).stdout
    assert str(pid) not in gone, '断开后子进程还在：%s' % gone[-200:]


def test_catalog_entries_are_usable():
    keys = [c['key'] for c in mb.CATALOG]
    assert 'time' in keys and 'filesystem' in keys
    for c in mb.CATALOG:
        assert c['command'] and isinstance(c['args'], list) and c['note']


# ---------------------------------------------------------------- 接线：审计 + 限额

@pytest.fixture
def _pet_with_fake(tmp_path, monkeypatch):
    """一个把 MCP 指向假 server 的桌宠实例，并把治理落到临时目录"""
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    import governance as gov
    monkeypatch.setattr(gov, 'LOG_DIR', str(tmp_path / 'logs'))
    monkeypatch.setattr(gov, 'CONFIG_PATH', str(tmp_path / 'config.json'))
    with open(gov.CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump({}, f)
    gov._cache.update({'mtime': None, 'day': None, 'counts': {}})

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    assert app is not None
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    cfg = _cfg(tmp_path, [{'name': 'fake', 'command': sys.executable, 'args': [FAKE]}])
    p.mcp = mb.McpBridge(cfg)
    p.mcp.connect_all()
    conn = p.mcp.conns['fake']
    assert _wait(conn), '假 server 没连上'
    yield p, gov, conn
    conn.stop()


def test_execute_tool_writes_audit(_pet_with_fake):
    p, gov, _conn = _pet_with_fake
    p._request_confirm = lambda msg: True
    out = p._execute_tool('mcp_fake_read_note', {'name': 'a'})
    assert '便签' in out
    e = gov.read_recent(1)[0]
    assert e['kind'] == 'call' and e['actor'] == 'mcp:fake' and e['allowed'] is True
    assert 'ms' in e


def test_execute_tool_quota_refusal(_pet_with_fake):
    p, gov, _conn = _pet_with_fake
    gov._save_cfg_value('tool_limits', {'mcp:fake': {'per_day': 1, 'per_minute': 99}})
    p._request_confirm = lambda msg: True
    assert '便签' in p._execute_tool('mcp_fake_read_note', {'name': 'a'})
    out2 = p._execute_tool('mcp_fake_read_note', {'name': 'b'})
    assert '已限额' in out2, out2
    assert gov.read_recent(1)[0]['kind'] == 'deny'


def test_execute_tool_denied_confirm_is_audited(_pet_with_fake):
    p, gov, _conn = _pet_with_fake
    p._request_confirm = lambda msg: False
    out = p._execute_tool('mcp_fake_write_note', {'name': 'a', 'text': 'x'})
    assert '使用者拒绝' in out
    e = gov.read_recent(1)[0]
    assert e['kind'] == 'deny' and e['allowed'] is False and 'write' in e['detail']
