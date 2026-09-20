# -*- coding: utf-8 -*-
"""治理三件测试（audit / quota / net，v6.69）

要点：审计、额度、白名单共享**一份事实来源**（当日审计日志），
所以这里既验各自行为，也验“日志里能看到的，就是限额算过的”。
"""
import json
import os
import sys
import time

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import governance as gov                                         # noqa: E402


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """把日志目录与配置文件都指到临时目录，绝不碰真实 logs/ 与 config.json"""
    monkeypatch.setattr(gov, 'LOG_DIR', str(tmp_path / 'logs'))
    monkeypatch.setattr(gov, 'CONFIG_PATH', str(tmp_path / 'config.json'))
    with open(gov.CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump({}, f)
    gov._cache.update({'mtime': None, 'day': None, 'counts': {}})
    yield


# ---------------------------------------------------------------- 审计

def test_log_and_read_recent():
    gov.log_event('call', 'skill:pdf_tools', 'pdf_tool', '合并 2 个文件')
    gov.log_event('deny', 'skill:pdf_tools', 'pdf_tool', '使用者拒绝', allowed=False)
    items = gov.read_recent(limit=10)
    assert len(items) == 2
    assert items[0]['kind'] == 'deny' and items[0]['allowed'] is False   # 新→旧
    assert items[1]['actor'] == 'skill:pdf_tools'
    assert os.path.isfile(gov.audit_path())


def test_log_truncates_long_fields():
    gov.log_event('call', 'x' * 500, 'y' * 500, 'z' * 5000)
    e = gov.read_recent(1)[0]
    assert len(e['actor']) <= 80 and len(e['action']) <= 80 and len(e['detail']) <= 400


def test_audit_can_be_switched_off():
    gov._save_cfg_value('audit_log', False)
    assert gov.log_event('call', 'a', 'b') is None
    assert gov.read_recent() == []


def test_audit_stats():
    gov.log_event('call', 'mcp:time', 'get_current_time', 'ok')
    gov.log_event('deny', 'mcp:time', 'convert_time', '使用者拒绝', allowed=False)
    st = gov.audit_stats()
    assert st['total'] == 2 and st['denied'] == 1 and 'mcp:time' in st['actors']


def test_purge_old_files(monkeypatch):
    os.makedirs(gov.LOG_DIR, exist_ok=True)
    old = os.path.join(gov.LOG_DIR, 'audit_2000-01-01.jsonl')
    with open(old, 'w', encoding='utf-8') as f:
        f.write('{}\n')
    os.utime(old, (time.time() - 90 * 86400,) * 2)
    new = os.path.join(gov.LOG_DIR, 'audit_2999-01-01.jsonl')
    with open(new, 'w', encoding='utf-8') as f:
        f.write('{}\n')
    removed = gov.purge_old(days=30)
    assert 'audit_2000-01-01.jsonl' in removed and os.path.isfile(new)


# ---------------------------------------------------------------- 额度

def test_default_limits_and_override():
    assert gov.limit_for('skill:x') == gov.DEFAULT_LIMITS
    gov._save_cfg_value('tool_limits', {'*': {'per_day': 5}, 'skill:x': {'per_minute': 2}})
    lim = gov.limit_for('skill:x')
    assert lim['per_day'] == 5 and lim['per_minute'] == 2


def test_quota_blocks_after_limit():
    gov._save_cfg_value('tool_limits', {'skill:pdf_tools': {'per_day': 3, 'per_minute': 100}})
    for _ in range(3):
        ok, why, _u = gov.check_quota('skill:pdf_tools')
        assert ok, why
        gov.log_event('call', 'skill:pdf_tools', 'pdf_tool', 'ok')
    ok, why, used = gov.check_quota('skill:pdf_tools')
    assert not ok and '上限 3' in why and used == 3


def test_quota_per_minute():
    gov._save_cfg_value('tool_limits', {'mcp:time': {'per_minute': 2, 'per_day': 100}})
    for _ in range(2):
        gov.log_event('call', 'mcp:time', 'get_current_time', 'ok')
    ok, why, _u = gov.check_quota('mcp:time')
    assert not ok and '一分钟' in why


def test_quota_can_be_disabled():
    gov._save_cfg_value('tool_limits_enabled', False)
    gov._save_cfg_value('tool_limits', {'skill:x': {'per_day': 1}})
    gov.log_event('call', 'skill:x', 't', 'ok')
    gov.log_event('call', 'skill:x', 't', 'ok')
    ok, _why, _u = gov.check_quota('skill:x')
    assert ok, '关掉限额后不该再拦'


def test_denied_calls_do_not_consume_quota():
    """被拒的调用不算“用过”（只数 kind=call）"""
    gov._save_cfg_value('tool_limits', {'skill:x': {'per_day': 1}})
    gov.log_event('deny', 'skill:x', 't', '拒绝', allowed=False)
    ok, _why, _u = gov.check_quota('skill:x')
    assert ok


# ---------------------------------------------------------------- 出网白名单

def test_net_allowlist_default_denies():
    ok, why = gov.net_allowed('https://api.example.com/x')
    assert not ok and '白名单是空的' in why


def test_net_allowlist_patterns():
    gov.set_net_allowlist(['api.deepseek.com', '*.github.com'])
    assert gov.net_allowed('https://api.deepseek.com/v1')[0] is True
    assert gov.net_allowed('https://raw.github.com/a/b')[0] is True
    assert gov.net_allowed('https://evil.com/x')[0] is False
    assert gov.host_of('https://A.Example.COM/x') == 'a.example.com'


def test_net_allowlist_wildcard_all():
    gov.set_net_allowlist(['*'])
    assert gov.net_allowed('https://anything.anywhere/x')[0] is True


def test_net_bad_url():
    ok, why = gov.net_allowed('not-a-url')
    assert not ok and '看不懂' in why


def test_http_get_blocked_logs_denial():
    gov.set_net_allowlist(['allowed.com'])
    data, err = gov.http_get('https://blocked.com/x')
    assert data is None and '不在出网白名单' in err
    items = gov.read_recent(5)
    assert items and items[0]['kind'] == 'net' and items[0]['allowed'] is False


def test_pet_net_module_wraps_governance():
    import pet_net
    gov.set_net_allowlist([])
    data, err = pet_net.http_get('https://example.com')
    assert data is None and '白名单' in err
    ok, why = pet_net.allowed('https://example.com')
    assert ok is False and '白名单' in why
