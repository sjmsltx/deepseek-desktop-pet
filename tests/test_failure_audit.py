# -*- coding: utf-8 -*-
"""L5 护栏：失败必须写审计（`kind=error`），且审计不可用不得影响主流程

范本：tests/test_foreground_privacy.py（只扫源码/不依赖运行环境部分）+ 行为断言
背景：今天两个缺陷（75/76）正是从 `_silent_log` 里捞出来的 —— L5 要让关键失败「同时落审计」。
"""
from __future__ import annotations

import io
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_audit_failure_writes_error_record(monkeypatch):
    """失败 → 审计里出现 kind='error'、actor='ai.calls'、allowed=False，detail 带归因。"""
    import desktop_pet as dp
    import governance as gov

    captured = []
    monkeypatch.setattr(gov, 'log_event',
                        lambda kind, actor, action, detail='', allowed=True, extra=None, ms=None:
                        captured.append((kind, actor, action, detail, allowed)), raising=True)

    d = dp._audit_failure(RuntimeError('boom'), detail='something weird', context='对话')

    assert d is not None, '应返回归因结构供卡片复用'
    assert len(captured) == 1, f'应恰好写一条审计，实际 {len(captured)}'
    kind, actor, action, detail, allowed = captured[0]
    assert kind == 'error' and actor == 'ai.calls' and allowed is False
    assert '层=' in detail and '未知' in detail


def test_audit_failure_maps_auth_error():
    """401 应被归到「认证」层，并写进审计 detail。"""
    import desktop_pet as dp
    import governance as gov
    import urllib.error as ue

    captured = []
    gov.log_event = lambda kind, actor, action, detail='', allowed=True, extra=None, ms=None: \
        captured.append(detail)
    try:
        d = dp._audit_failure(ue.HTTPError('https://x', 401, 'Unauthorized', {}, None), context='对话')
        assert d.layer == '鉴权'
        assert '鉴权' in captured[0]
    finally:
        import importlib
        importlib.reload(gov)


def test_audit_failure_never_raises_when_audit_broken(monkeypatch):
    """审计写失败时：不得抛异常（主流程优先），仍返回归因结构。"""
    import desktop_pet as dp
    import governance as gov
    import logging

    def _boom(*a, **k):
        raise RuntimeError('audit subsystem down')
    monkeypatch.setattr(gov, 'log_event', _boom, raising=True)

    d = dp._audit_failure(RuntimeError('x'))
    assert d is not None and d.layer


def test_audit_failure_survives_diagnosis_failure(monkeypatch):
    """归因模块坏掉时：仍要写出一条退化审计（不许静默丢失败）。"""
    import desktop_pet as dp
    import governance as gov
    import sys

    monkeypatch.setitem(sys.modules, 'pet_diagnosis', None)
    captured = []
    monkeypatch.setattr(gov, 'log_event',
                        lambda kind, actor, action, detail='', allowed=True, extra=None, ms=None:
                        captured.append((kind, detail)), raising=True)

    d = dp._audit_failure(RuntimeError('boom'))
    assert d is None
    assert captured and captured[0][0] == 'error' and 'RuntimeError' in captured[0][1]


def test_failure_path_is_wired_in_source():
    """源码护栏：AI 失败分支必须调用 `_audit_failure(`（防以后有人把审计摘掉）。

    v1-B 起：卡片改走**唯一出口** `_notify_failure_card(`（不再就地 to_card ✗），
    护栏随之改为：**先写审计、再经单点出口出卡** ✓
    """
    src = Path(ROOT / 'desktop_pet.py').read_text(encoding='utf-8')
    assert '_audit_failure(e' in src, '失败分支必须调用 _audit_failure(...)，把失败写进审计（L5）'
    assert '_notify_failure_card(_d' in src, \
        '失败分支必须经**唯一出口** _notify_failure_card(...) 出卡（v1-B 定案 ③：单点不得绕过）✗'
    # 且审计要在卡片之前（先落盘、再给用户看）
    i_audit = src.index('_audit_failure(e')
    i_card = src.index('_notify_failure_card(_d')
    assert i_audit < i_card, '应先写审计、再渲染卡片'
