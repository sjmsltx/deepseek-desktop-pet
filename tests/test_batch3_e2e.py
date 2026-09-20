# -*- coding: utf-8 -*-
"""Batch 3 端到端验证（2026-09-20 微信侧会话接手时做的真机验证，固化成回归测试）。

覆盖三件事的**真实行为**（不是接口存在性）：
  ① 技能包生命周期：安装 → 注册 → 卸载移入停放区（只留最近 5 个）
  ② 治理三件：审计日志 / 额度限制 / 出网白名单（真计数、真拦截）
  ③ MCP 桥接：工具分类与写类确认策略（真实第三方 server 的连通测试见文件末尾，默认跳过）

设计前提：全部跑在临时目录，**绝不动使用者的 config.json 与正式 logs/**
（governance 的 CONFIG_PATH / LOG_DIR 被 monkeypatch 掉）。
"""
import json
import os
import sys
import time
import zipfile

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import governance as gov  # noqa: E402
import mcp_bridge  # noqa: E402
import skill_pack as sp  # noqa: E402


@pytest.fixture
def gov_env(tmp_path, monkeypatch):
    """把治理模块的配置/日志路径指到临时目录，并清掉当天计数缓存"""
    cfg = tmp_path / 'config.json'
    cfg.write_text(json.dumps({'audit_log': True, 'tool_limits_enabled': True}), encoding='utf-8')
    monkeypatch.setattr(gov, 'CONFIG_PATH', str(cfg))
    monkeypatch.setattr(gov, 'LOG_DIR', str(tmp_path / 'logs'))
    gov._cache.update({'mtime': -1, 'day': None, 'counts': {}})
    return gov


# ============================================================ ① 技能包生命周期

GOOD_ENTRY = 'def run(args):\n    """示例工具"""\n    return "ok"\n'


def _pack(root, name, entry=GOOD_ENTRY, perms=None, version='1.0.0'):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, sp.MANIFEST_NAME), 'w', encoding='utf-8') as f:
        json.dump({'manifest_version': 2, 'name': name, 'version': version, 'type': 'tool',
                   'entry': 'main.py', 'permissions': perms or {}}, f, ensure_ascii=False)
    with open(os.path.join(d, 'main.py'), 'w', encoding='utf-8') as f:
        f.write(entry)
    return d


def test_pack_lifecycle_and_parking_keeps_five(tmp_path):
    plugins = str(tmp_path / 'plugins')
    os.makedirs(plugins)
    for i in range(7):
        r = sp.install_from_dir(_pack(str(tmp_path), f'park{i}'), plugins)
        assert r[0], r[1]
        time.sleep(0.02)
        ok, msg = sp.uninstall(plugins, f'park{i}')
        assert ok, msg
    park = os.path.join(plugins, sp.PARK_DIR)
    kept = sorted(os.listdir(park))
    assert len(kept) == sp.PARK_KEEP, f'停放区应只留 {sp.PARK_KEEP} 个，实有 {kept}'
    assert any(k.startswith('park6') for k in kept), '最新卸载的包应还在（文件不是被删掉）'
    assert not any(k.startswith('park0') for k in kept), '最老的应被清理'


def test_registry_records_hash_and_declared(tmp_path):
    plugins = str(tmp_path / 'plugins')
    os.makedirs(plugins)
    ok, msg, _ = sp.install_from_dir(
        _pack(str(tmp_path), 'demo', perms={'files.read': '读一下'}), plugins, granted={'files.read'})
    assert ok, msg
    entry = sp.read_registry(plugins).get('demo') or {}
    assert entry.get('hash'), '登记表要记目录哈希'
    assert entry.get('declared') == ['files.read']


@pytest.mark.parametrize('label, manifest, files, keyword', [
    ('os.system', {'name': 'p1', 'type': 'tool', 'entry': 'main.py', 'permissions': {}},
     {'main.py': 'import os\ndef run(a):\n    os.system("calc")\n'}, '永禁'),
    ('eval', {'name': 'p2', 'type': 'tool', 'entry': 'main.py', 'permissions': {}},
     {'main.py': 'def run(a):\n    return eval(a)\n'}, '永禁'),
    ('未声明权限就出网', {'name': 'p3', 'type': 'tool', 'entry': 'main.py', 'permissions': {}},
     {'main.py': 'import requests\ndef run(a):\n    return requests.get("http://x").text\n'}, 'network'),
    ('未声明权限就读文件', {'name': 'p4', 'type': 'tool', 'entry': 'main.py', 'permissions': {}},
     {'main.py': 'def run(a):\n    return open("config.json").read()\n'}, 'files.read'),
    ('entry 越界', {'name': 'p5', 'type': 'tool', 'entry': '../x.py', 'permissions': {}},
     {'main.py': 'def run(a):\n    return 1\n'}, '相对路径'),
])
def test_malicious_packs_rejected(tmp_path, label, manifest, files, keyword):
    d = os.path.join(str(tmp_path), 'candidate')
    os.makedirs(d, exist_ok=True)
    manifest = dict(manifest, manifest_version=2, version='1.0.0')
    with open(os.path.join(d, sp.MANIFEST_NAME), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False)
    for rel, content in files.items():
        with open(os.path.join(d, rel), 'w', encoding='utf-8') as f:
            f.write(content)
    plugins = str(tmp_path / 'plugins')
    os.makedirs(plugins, exist_ok=True)
    ok, msg, _ = sp.install_from_dir(d, plugins)
    assert not ok, f'{label} 应当被拒绝，却装上了'
    assert keyword in msg, f'{label} 的拒绝理由应提到 {keyword}，实际：{msg}'


def test_zip_slip_and_bad_ext_rejected(tmp_path):
    plugins = str(tmp_path / 'plugins')
    os.makedirs(plugins)
    z = str(tmp_path / 'slip.zip')
    with zipfile.ZipFile(z, 'w') as zf:
        zf.writestr('plugin.json', json.dumps({'manifest_version': 2, 'name': 'slip', 'type': 'tool', 'entry': 'main.py'}))
        zf.writestr('../evil.py', 'print(1)')
    ok, msg, _ = sp.install_from_zip(z, plugins)
    assert not ok and '非法路径' in msg

    z2 = str(tmp_path / 'exe.zip')
    with zipfile.ZipFile(z2, 'w') as zf:
        zf.writestr('plugin.json', json.dumps({'manifest_version': 2, 'name': 'hasexe', 'type': 'tool', 'entry': 'main.py'}))
        zf.writestr('main.py', GOOD_ENTRY)
        zf.writestr('payload.exe', b'MZ\x90\x00')
    ok2, msg2, _ = sp.install_from_zip(z2, plugins)
    assert not ok2 and '不允许的文件类型' in msg2


# ============================================================ ② 治理三件

def test_audit_log_roundtrip(gov_env):
    gov_env.log_event('tool', 'skill:demo', 'run', '端到端验证', allowed=True, ms=12)
    recent = gov_env.read_recent(limit=10)
    assert any(e.get('action') == 'run' and e.get('actor') == 'skill:demo' for e in recent)
    st = gov_env.audit_stats()
    assert st['total'] >= 1 and st['actors'] == ['skill:demo']
    assert os.path.isfile(gov_env.audit_path())


def test_quota_blocks_third_call_in_a_minute(gov_env):
    gov_env.set_limit('skill:q', per_minute=2, per_day=5)
    got = []
    for i in range(3):
        ok, why, used = gov_env.check_quota('skill:q')
        got.append(ok)
        gov_env.log_event('call', 'skill:q', 'run', f'第{i + 1} 次', allowed=ok)
    assert got == [True, True, False], f'额度应按 2 次/分 生效，实际 {got}'
    ok, why, used = gov_env.check_quota('skill:q')
    assert not ok and '上限' in why


def test_quota_day_limit(gov_env):
    gov_env.set_limit('skill:d', per_minute=99, per_day=1)
    ok, _, _ = gov_env.check_quota('skill:d')
    assert ok
    gov_env.log_event('call', 'skill:d', 'run', '一次')
    ok2, why2, _ = gov_env.check_quota('skill:d')
    assert not ok2 and '今天已调用' in why2


def test_net_allowlist_blocks_by_default(gov_env):
    assert gov_env.net_allowlist() == []
    allowed, why = gov_env.net_allowed('https://example.com/x')
    assert allowed is False and '白名单' in why
    # 真发请求的入口也必须被拦（不是只判断函数）
    out = gov_env.http_get('https://example.com/')
    assert isinstance(out, tuple) and out[0] is None and '白名单' in str(out[1])


def test_net_allowlist_rule_allows_only_that_host(gov_env):
    gov_env.add_net_rule('example.com')
    assert gov_env.net_allowed('https://example.com/x')[0] is True
    assert gov_env.net_allowed('https://evil.example.net/')[0] is False
    assert gov_env.net_allowed('https://sub.other.com/')[0] is False


def test_host_of_returns_hostname_without_port(gov_env):
    """白名单按域名匹配（不带端口）——记录既定行为，别当成 bug"""
    assert gov_env.host_of('https://a.b.com:8443/p?q=1') == 'a.b.com'


def test_purge_old_uses_mtime(gov_env):
    os.makedirs(gov_env.LOG_DIR, exist_ok=True)
    old = os.path.join(gov_env.LOG_DIR, 'audit_2020-01-01.jsonl')
    with open(old, 'w', encoding='utf-8') as f:
        f.write('{"ts":"2020-01-01T00:00:00"}\n')
    past = time.time() - 400 * 86400
    os.utime(old, (past, past))
    fresh = os.path.join(gov_env.LOG_DIR, 'audit_fresh.jsonl')
    with open(fresh, 'w', encoding='utf-8') as f:
        f.write('{"ts":"now"}\n')
    removed = gov_env.purge_old()
    assert removed == ['audit_2020-01-01.jsonl']
    assert os.path.isfile(fresh)


# ============================================================ ③ MCP 策略（离线部分）

def test_mcp_tool_name_parsing_and_confirm(tmp_path):
    br = mcp_bridge.McpBridge(str(tmp_path / 'config.json'))
    # 名字格式不对 / 没这个 server → 不要求确认
    assert br.needs_confirm('not_a_tool') == (False, '')
    assert br.needs_confirm('mcp_nosuch_read_file')[0] is False


def test_mcp_classify_read_write():
    read_tool = {'name': 'read_file', 'description': '读文件', 'read_only': True, 'destructive': False}
    write_tool = {'name': 'write_file', 'description': '写文件', 'read_only': False, 'destructive': True}
    unknown = {'name': 'mystery', 'description': '看不出读写', 'read_only': False, 'destructive': False}
    assert mcp_bridge.classify_tool(read_tool)[0] is True
    assert mcp_bridge.classify_tool(write_tool)[0] is False
    # 名字看不出读写的 → 保守按写处理（要确认）
    assert mcp_bridge.classify_tool(unknown)[0] is False


# ============================================================ 真机（默认跳过）

@pytest.mark.skipif(os.environ.get('RUN_SLOW_MCP') != '1',
                    reason='需要外网 + npx，设 RUN_SLOW_MCP=1 才跑（真机对接第三方 MCP server）')
def test_third_party_mcp_server_end_to_end(tmp_path):
    """对接 npm 官方 @modelcontextprotocol/server-filesystem（真机证据，见 HANDOFF 坑 #2）"""
    import subprocess

    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    (data_dir / 'hello.txt').write_text('端到端验证内容\n', encoding='utf-8')
    cfg = tmp_path / 'config.json'
    cfg.write_text('{}', encoding='utf-8')
    br = mcp_bridge.McpBridge(str(cfg))
    ok, msg = br.add_server({'name': 'fs', 'command': 'npx',
                             'args': ['-y', '@modelcontextprotocol/server-filesystem', str(data_dir)]})
    assert ok, msg
    try:
        deadline = time.time() + 180
        state, tools = '', []
        while time.time() < deadline:
            srv = (br.servers() or [{}])[0]
            state, tools = srv.get('state'), srv.get('tools') or []
            if state in ('已连接', '连接失败'):
                break
            time.sleep(3)
        assert state == '已连接', f'第三方 server 没连上：{srv.get("error")}'
        names = [t['name'] for t in tools]
        assert 'read_file' in names and 'write_file' in names
        # schema 真的取到了（历史 bug：input_schema/inputSchema 字段名）
        schemas = {s['function']['name']: s['function']['parameters'] for s in br.tool_schemas()}
        assert 'path' in (schemas['mcp_fs_read_file'].get('properties') or {})
        # 真读
        assert 'hello.txt' in str(br.call_tool('mcp_fs_list_directory', {'path': str(data_dir)}))
        assert '端到端验证内容' in str(br.call_tool('mcp_fs_read_file', {'path': str(data_dir / 'hello.txt')}))
        # 真写（落盘）
        dst = data_dir / 'written.txt'
        br.call_tool('mcp_fs_write_file', {'path': str(dst), 'content': 'MCP 写入'})
        assert dst.exists() and 'MCP 写入' in dst.read_text(encoding='utf-8')
        # 写类要确认
        assert br.needs_confirm('mcp_fs_write_file')[0] is True
    finally:
        br.remove_server('fs')
        time.sleep(4)
        procs = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*"
             + str(data_dir) + "*' -and $_.Name -ne 'powershell.exe' } | "
             'Select-Object -ExpandProperty ProcessId'],
            capture_output=True, text=True, timeout=60)
        assert not procs.stdout.strip(), f'断开后残留子进程：{procs.stdout}'
