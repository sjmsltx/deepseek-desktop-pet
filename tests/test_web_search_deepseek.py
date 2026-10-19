# -*- coding: utf-8 -*-
"""联网搜索已从 Tavily 换成 DeepSeek 官方 Search API

2026-10-19（Owner 批准方案 A）：
  · 复用已有 DeepSeek Key —— 用户不必再单独注册 Tavily
  · 与模型无关：是本地发 HTTP，不要求模型支持内置 web_search
    （官方内置 web_search 只在 deepseek-v4-pro 生效，走方案 B 会强制换贵 3.4~7.5 倍的模型）
"""
import io
import json
import os
import sys
import time
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import desktop_pet  # noqa: E402
from desktop_pet import PetWidget  # noqa: E402


class _FakePet:
    """只提供 _web_search 需要的那点接口，避免实例化整个 PetWidget"""

    _last_search_ts = 0.0

    def __init__(self, key='sk-test-key'):
        self._key = key

    def _api_key_for_field(self, field):
        return self._key if field == 'deepseek_api_key' else ''


def _resp(payload, status=200):
    class _R:
        status = 200

        def read(self):
            return json.dumps(payload).encode('utf-8')

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    _R.status = status
    return _R()


def _raise(code):
    def _fn(*a, **k):
        raise urllib.error.HTTPError('https://api.deepseek.com', code, 'err', {}, None)
    return _fn


# ============ 基本行为 ============

def test_no_key_returns_actionable_hint(monkeypatch):
    """没配 Key 时，要告诉用户去哪里配、且说明不用注册别的服务"""
    out = PetWidget._web_search(_FakePet(key=''), 'q')
    assert 'DeepSeek API Key' in out
    assert '不需要另外注册' in out or '不用另外注册' in out


def test_fields_are_mapped(monkeypatch):
    """title / url / site_name / date 都要进结果；无 summary 时退回 snippet"""
    payload = {'results': [
        {'title': '标题一', 'url': 'https://a.example/1', 'summary': '摘要一' * 30,
         'site_name': '站点A', 'date': '2026-10-17T00:00:00+00:00'},
        {'title': '标题二', 'url': 'https://a.example/2', 'snippet': '短摘要二',
         'site_name': '站点B', 'date': ''},
    ]}
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **k: _resp(payload))

    out = PetWidget._web_search(_FakePet(), 'q')

    assert '标题一' in out and 'https://a.example/1' in out
    assert '站点A' in out and '2026-10-17' in out
    assert '标题二' in out and '短摘要二' in out


def test_empty_results(monkeypatch):
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **k: _resp({'results': []}))
    assert '无结果' in PetWidget._web_search(_FakePet(), 'q')


# ============ 三种错误码要分得清（之前一律"搜索失败"）============

def test_401_says_key_invalid(monkeypatch):
    monkeypatch.setattr('urllib.request.urlopen', _raise(401))
    out = PetWidget._web_search(_FakePet(), 'q')
    assert 'Key 无效' in out or '已过期' in out


def test_402_says_balance_low(monkeypatch):
    monkeypatch.setattr('urllib.request.urlopen', _raise(402))
    out = PetWidget._web_search(_FakePet(), 'q')
    assert '余额不足' in out


def test_429_says_rate_limited(monkeypatch):
    monkeypatch.setattr('urllib.request.urlopen', _raise(429))
    out = PetWidget._web_search(_FakePet(), 'q')
    assert '限流' in out


def test_other_http_code_falls_back(monkeypatch):
    monkeypatch.setattr('urllib.request.urlopen', _raise(500))
    out = PetWidget._web_search(_FakePet(), 'q')
    assert 'HTTP 500' in out


# ============ 节流（官方 QPS 5）============

def test_throttle_sleeps_when_too_fast(monkeypatch):
    slept = []
    monkeypatch.setattr('time.sleep', lambda s: slept.append(s))
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **k: _resp({'results': []}))

    pet = _FakePet()
    PetWidget._web_search(pet, 'q1')          # 第一次：记录时间戳
    PetWidget._web_search(pet, 'q2')          # 紧接着：应触发等待

    assert slept, '连续调用之间应当等待（QPS 5）'
    assert all(s > 0 for s in slept)


# ============ 结构钉：不许再走回 Tavily ============

def test_source_no_longer_uses_tavily_endpoint():
    src = io.open(desktop_pet.__file__, encoding='utf-8').read()
    assert 'api.tavily.com' not in src, '搜索不应再请求 Tavily 端点'
    assert 'api.deepseek.com/v1/tools/search' in src, '应当走 DeepSeek 官方 Search'


def test_search_uses_profile_key_resolver():
    """Key 必须通过 _api_key_for_field 取，不能硬编码字段名直接读 self.ai_key"""
    src = io.open(desktop_pet.__file__, encoding='utf-8').read()
    start = src.index('def _web_search(')
    end = src.index('def ', start + 10)
    body = src[start:end]
    assert '_api_key_for_field' in body
    assert 'search_api_key' not in body, '不得再依赖旧的 Tavily key 字段'
