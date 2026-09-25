# -*- coding: utf-8 -*-
"""L4-1 护栏：`recent_errors()` 纯函数整理层 + 与审计**同源**实测

微信侧 L4-1 核验清单（2026-09-25 `WX-桌宠-20260925-11`）：
  ① 倒序 ② 条数上限 ③ 字段齐 ④ **与审计同源实测**（写一条失败 → 能查到）
"""
from __future__ import annotations

import importlib
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _rec(ts, kind='error', detail='未知 ｜ 层=本地网络 ｜ boom', actor='ai.calls',
         action='对话', allowed=False):
    return {'ts': ts, 'kind': kind, 'actor': actor, 'action': action,
            'detail': detail, 'allowed': allowed}


# ── ① 倒序（新 → 旧）────────────────────────────────────────────────
def test_newest_first():
    import pet_diagnosis as d
    rows = d.recent_errors([
        _rec('2026-09-25T10:00:00'),
        _rec('2026-09-25T12:00:00'),
        _rec('2026-09-25T11:00:00'),
    ])
    assert [r['time'] for r in rows] == ['2026-09-25T12:00:00',
                                         '2026-09-25T11:00:00',
                                         '2026-09-25T10:00:00']


# ── ② 条数上限 ──────────────────────────────────────────────────────
def test_limit_caps_output():
    import pet_diagnosis as d
    recs = [_rec('2026-09-25T10:%02d:00' % i) for i in range(30)]
    assert len(d.recent_errors(recs, limit=5)) == 5
    assert len(d.recent_errors(recs)) == 20, '默认上限应为 20 ✓'
    assert len(d.recent_errors(recs, limit=0)) == 20, 'limit<=0 视为默认 ✓'


# ── ③ 字段齐 ────────────────────────────────────────────────────────
def test_all_fields_present():
    import pet_diagnosis as d
    rows = d.recent_errors([_rec('2026-09-25T10:00:00')])
    assert len(rows) == 1
    r = rows[0]
    for k in ('time', 'kind', 'actor', 'action', 'layer', 'summary', 'allowed'):
        assert k in r, f'缺字段 {k} ✗'
        assert str(r[k]).strip() != '' or k == 'time', f'字段 {k} 为空 ✗'
    assert r['layer'] == '本地网络', r
    assert '层=' not in r['summary'], '摘要里不该再带层标记 ✗'


def test_layer_filter_and_unknown_default():
    import pet_diagnosis as d
    recs = [_rec('2026-09-25T10:00:00', detail='某错 ｜ 层=鉴权 ｜ 401'),
            _rec('2026-09-25T10:01:00', detail='没有层标记的错误')]
    only_auth = d.recent_errors(recs, layer='鉴权')
    assert len(only_auth) == 1 and only_auth[0]['layer'] == '鉴权'
    all_rows = d.recent_errors(recs)
    assert {r['layer'] for r in all_rows} == {'鉴权', '未知'}


def test_only_failure_kinds_kept():
    import pet_diagnosis as d
    recs = [_rec('2026-09-25T10:00:00', kind='call', allowed=True),      # 正常调用 → 不留
            _rec('2026-09-25T10:01:00', kind='deny', allowed=False),     # 拒绝 → 留
            _rec('2026-09-25T10:02:00', kind='error', allowed=False)]    # 失败 → 留
    rows = d.recent_errors(recs)
    assert [r['kind'] for r in rows] == ['error', 'deny']


def test_bad_records_do_not_crash():
    import pet_diagnosis as d
    rows = d.recent_errors([None, 42, 'x', {}, {'kind': 'error'}, _rec('2026-09-25T10:00:00')])
    assert len(rows) == 2, '坏记录应跳过、不炸 ✓'
    assert d.recent_errors([]) == [] and d.recent_errors(None) == []


# ── ④ 与审计同源实测：写一条失败 → 能查到 ✓ ──────────────────────────
def test_same_source_as_audit(monkeypatch, tmp_path):
    import governance as gov
    monkeypatch.setattr(gov, 'LOG_DIR', str(tmp_path), raising=True)
    monkeypatch.setattr(gov, 'audit_enabled', lambda: True, raising=True)
    monkeypatch.setattr(gov, '_cfg', lambda: {'audit_log': True}, raising=True)
    importlib.reload  # noqa: F841  (保留习惯写法，不改模块)

    import desktop_pet as dp
    dp._audit_failure(RuntimeError('boom'), context='对话')          # 写审计（kind=error）✓

    raw = gov.read_recent(limit=50, day=None)
    assert raw, '审计里应有刚写的一条 ✗'

    import pet_diagnosis as d
    rows = d.recent_errors(raw)
    assert rows, 'recent_errors 应能整理出这条失败 ✗'
    assert rows[0]['kind'] == 'error'
    assert rows[0]['layer'] in ('未知', '本地网络', '上游故障', '鉴权')   # 归因后的层名 ✓
    assert rows[0]['actor'] == 'ai.calls'


def test_recent_failure_records_is_readonly(monkeypatch, tmp_path):
    """跨天读取器：只读 ✓ 不抛异常 ✓（审计不可用时返回 [] ✓）"""
    import governance as gov
    monkeypatch.setattr(gov, 'LOG_DIR', str(tmp_path), raising=True)
    assert gov.recent_failure_records(days=2, limit=10) == []


# ── 纯函数边界：recent_errors 不得读文件 ✗ ───────────────────────────
def test_recent_errors_is_pure():
    """AST 护栏：`recent_errors` 函数体内不得出现 open(/IO ✓"""
    import ast as _ast
    tree = _ast.parse(io.open(ROOT / 'pet_diagnosis.py', encoding='utf-8').read())
    fn = next(n for n in _ast.walk(tree)
              if isinstance(n, _ast.FunctionDef) and n.name == 'recent_errors')
    bad = []
    for node in _ast.walk(fn):
        if isinstance(node, _ast.Call):
            nm = getattr(node.func, 'id', None) or getattr(node.func, 'attr', None)
            if nm in ('open', 'read', 'urlopen', 'probe_status'):
                bad.append('%s@%d' % (nm, node.lineno))
    assert not bad, f'recent_errors 必须保持纯函数 ✗：{bad}'
