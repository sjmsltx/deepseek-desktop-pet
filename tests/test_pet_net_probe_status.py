# -*- coding: utf-8 -*-
"""L3-1 护栏：上游公告探测（`pet_net.probe_status`）+ 卡片公告行

微信侧 L3-1 核验清单（2026-09-25 `WX-桌宠-20260925-07`）：
  ① 白名单拒绝 ② 超时降级**不阻塞** ③ **无公告不显示** ④ 与四段卡片**不打架**
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / 'desktop_pet.py'


# ── 护栏③：未配置 → unknown（调用方不显示行 ✓）──────────────────────
def test_probe_unknown_when_no_url():
    import pet_net
    r = pet_net.probe_status('')
    assert r['state'] == 'unknown' and r['text'] == ''
    r2 = pet_net.probe_status(None)
    assert r2['state'] == 'unknown'


# ── 护栏①：白名单外 → denied，且**一次请求都不发** ✓ ──────────────────
def test_probe_denied_never_issues_request(monkeypatch):
    import pet_net
    import governance as gov
    import urllib.request as ur

    def _boom(*a, **k):
        raise AssertionError('白名单外不得发起任何请求 ✗')
    monkeypatch.setattr(gov, 'net_allowed', lambda url: (False, '不在白名单'), raising=True)
    monkeypatch.setattr(ur, 'urlopen', _boom, raising=True)

    r = pet_net.probe_status('https://not-allowed.example.com/status.json')
    assert r['state'] == 'denied', r
    assert '不在白名单' in r['text']


# ── 护栏②：超时/异常 → error，且**不抛异常**（不阻塞主流程 ✓）──────────
def test_probe_timeout_degrades_without_raising(monkeypatch):
    import pet_net
    import governance as gov

    monkeypatch.setattr(gov, 'net_allowed', lambda url: (True, 'ok'), raising=True)

    def _boom(*a, **k):
        raise TimeoutError('timed out')
    monkeypatch.setattr(pet_net, 'get_json', _boom, raising=True)
    monkeypatch.setattr(pet_net, 'get_text', _boom, raising=True)

    r = pet_net.probe_status('https://allowed.example.com/status.json')   # 不得抛 ✗
    assert r['state'] == 'error', r
    assert 'TimeoutError' in r['text']


# ── 公告解析：JSON 常见字段 / 纯文本首行 / 无内容 → ok ✓ ────────────────
@pytest.mark.parametrize('payload,expect_state,expect_in', [
    ({'notice': '上游正在维护，预计 20:00 恢复'}, 'notice', '维护'),
    ({'status': {'description': 'Partial Outage'}}, 'notice', 'Outage'),
    ({'status': 'ok'}, 'ok', ''),
    ({'foo': 'bar'}, 'ok', ''),
])
def test_probe_parses_notice(monkeypatch, payload, expect_state, expect_in):
    import pet_net
    import governance as gov

    monkeypatch.setattr(gov, 'net_allowed', lambda url: (True, 'ok'), raising=True)
    monkeypatch.setattr(pet_net, 'get_json', lambda url, **k: (payload, ''), raising=True)
    r = pet_net.probe_status('https://allowed.example.com/status.json')
    assert r['state'] == expect_state, r
    if expect_in:
        assert expect_in in r['text']


def test_probe_plaintext_first_line(monkeypatch):
    import pet_net
    import governance as gov

    monkeypatch.setattr(gov, 'net_allowed', lambda url: (True, 'ok'), raising=True)
    monkeypatch.setattr(pet_net, 'get_json', lambda url, **k: (None, '不是合法 JSON'), raising=True)
    monkeypatch.setattr(pet_net, 'get_text',
                        lambda url, **k: ('\n\n  上游限流升级中  \n更多说明…', ''), raising=True)
    r = pet_net.probe_status('https://allowed.example.com/status.txt')
    assert r['state'] == 'notice' and r['text'] == '上游限流升级中', r


# ── 护栏③ + ④：卡片**只在有公告时**多一行，且不与四段冲突 ✓ ────────────
def test_card_notice_line_only_when_present():
    import pet_diagnosis as d
    diag = d.Diag('上游故障', '上游服务故障', '这一轮没有回答', '稍等再发', 'HTTP 503')
    plain = d.to_card(diag)
    assert '上游公告' not in plain, '无公告时不得出现该行 ✗'
    assert plain.count('　· ') == 4, '四段结构不得被破坏 ✗'
    with_notice = d.to_card(diag, notice='上游维护中')
    assert '　· 上游公告：上游维护中' in with_notice
    assert '出在哪：上游故障' in with_notice and '原始错误：HTTP 503' in with_notice


# ── 集成护栏：只有上游三层才去取公告；且只在**唯一出口**里取 ✓ ──────────
def test_notice_only_for_upstream_layers_in_source():
    src = io.open(SRC, encoding='utf-8').read()
    assert "UPSTREAM_LAYERS = ('上游超时', '上游故障', '上游限流')" in src, '上游层清单缺失 ✗'
    i_card = src.index('def _notify_failure_card')
    i_probe = src.index('_upstream_notice()', i_card)
    assert i_probe > i_card, '公告只能在单点出口内获取 ✓'


def test_probe_status_is_single_network_gate():
    """护栏：pet_diagnosis 保持纯函数（不得出现 probe_status / urllib / open()）✗

    ⭐ 用 **AST**（剔 docstring/注释）而非行匹配 —— 否则会命中文档里的规则 = **假红** ✗
    （这个坑我方已记入教训：130 号护栏事件）
    """
    import ast as _ast
    tree = _ast.parse(io.open(ROOT / 'pet_diagnosis.py', encoding='utf-8').read())
    bad = []
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Name) and node.id in ('probe_status', 'urllib', 'socket'):
            bad.append('name:%s@%d' % (node.id, node.lineno))
        if isinstance(node, _ast.Attribute) and node.attr in ('probe_status', 'urlopen'):
            bad.append('attr:%s@%d' % (node.attr, node.lineno))
        if isinstance(node, _ast.Import):
            for a in node.names:
                # urllib.error 是 v1-A 用来**判异常类型**（非出网 ✓）→ 放行 ✓；只禁 urllib.request/requests/http.client ✗
                if a.name.split('.')[0] in ('requests', 'http') or 'request' in a.name:
                    bad.append('import:%s@%d' % (a.name, node.lineno))
        if isinstance(node, _ast.Call) and getattr(node.func, 'id', None) == 'open':
            bad.append('open()@%d' % node.lineno)
    # socket 是 v1-A 判超时所用的**标准库类型**（非出网）→ 单独放行 ✓
    bad = [b for b in bad if not b.startswith('name:socket')]
    assert not bad, f'pet_diagnosis 出现非纯函数符号 ✗：{bad}'
