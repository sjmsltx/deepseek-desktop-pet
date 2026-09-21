# -*- coding: utf-8 -*-
"""治理增强测试（Batch 4 · 2026-09-21）

覆盖：
  ① 审计查看：read_filtered 三种筛选 / export_csv 内容与编码 / clear_day 先备份再清
  ② 出网白名单：net_explain 与 net_allowed 判定一致（不写第二套逻辑）
另含护栏：整个过程不改动真实 config.json（按 EXP.0105 的铁律，先比对哈希）
"""
import csv
import hashlib
import json
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import governance as gov  # noqa: E402

CFG = os.path.join(BASE, 'config.json')


def _hash(path):
    if not os.path.isfile(path):
        return ''
    with open(path, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """把审计目录指到临时目录，并让审计强制开启（不动真实 config）"""
    logdir = tmp_path / 'logs'
    logdir.mkdir()
    monkeypatch.setattr(gov, 'LOG_DIR', str(logdir))
    monkeypatch.setattr(gov, 'audit_enabled', lambda: True)
    monkeypatch.setattr(gov, '_cache', {'mtime': None, 'day': None, 'counts': {}})
    return logdir


def _seed(n=20):
    """造 20 条混合审计：两个对象、四种类型、其中 5 条被拒"""
    for i in range(n):
        actor = 'skill.alpha' if i % 2 == 0 else 'mcp.beta'
        kind = ['call', 'deny', 'net', 'install'][i % 4]
        allowed = (i % 4 != 1)
        gov.log_event(kind, actor, 'act%d' % i, detail='detail-%d' % i, allowed=allowed)


# ---------------- ① 审计查看 ----------------

def test_read_filtered_by_kind(sandbox):
    _seed(20)
    only = gov.read_filtered(kind='call', limit=500)
    assert len(only) == 5 and all(e['kind'] == 'call' for e in only)
    # '全部' 等价于不过滤
    assert len(gov.read_filtered(kind='全部', limit=500)) == 20


def test_read_filtered_by_actor(sandbox):
    _seed(20)
    only = gov.read_filtered(actor='mcp.beta', limit=500)
    assert len(only) == 10 and all(e['actor'] == 'mcp.beta' for e in only)


def test_read_filtered_only_denied(sandbox):
    _seed(20)
    denied = gov.read_filtered(only_denied=True, limit=500)
    assert len(denied) == 5
    assert all(e['allowed'] is False for e in denied)
    # 组合筛选：被拒 + 指定类型
    combo = gov.read_filtered(kind='deny', only_denied=True, limit=500)
    assert all(e['kind'] == 'deny' and e['allowed'] is False for e in combo)


def test_read_filtered_limit_and_order(sandbox):
    _seed(20)
    out = gov.read_filtered(limit=3)
    assert len(out) == 3
    # 新→旧：最后写入的 act19 应排在最前
    assert out[0]['action'] == 'act19'


def test_export_csv_content(sandbox, tmp_path):
    _seed(20)
    out = str(tmp_path / 'audit_export.csv')
    ok, n = gov.export_csv(out)
    assert ok and n == 20
    raw = open(out, 'rb').read()
    assert raw.startswith(b'\xef\xbb\xbf'), '必须是 utf-8-sig（Excel 双击不乱码）'
    with open(out, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.reader(f))
    assert rows[0] == ['时间', '类型', '对象', '动作', '是否允许', '耗时ms', '详情', '附加']
    assert len(rows) == 21                      # 表头 + 20 条
    assert all(len(r) == 8 for r in rows)       # 列齐全
    assert rows[1][4] in ('是', '否')            # 时间正序第一条（i=0，allowed=True）
    assert any(r[4] == '否' for r in rows)       # 被拒的也导出了


def test_clear_day_backs_up_first(sandbox):
    _seed(5)
    path = gov.audit_path()
    assert os.path.isfile(path)
    ok, msg = gov.clear_day()
    assert ok and '备份' in msg
    baks = [f for f in os.listdir(str(sandbox)) if f.startswith('audit_') and '.bak-' in f]
    assert len(baks) == 1, '必须先改名备份而不是直接删'
    # 备份里内容完整（5 条）
    with open(os.path.join(str(sandbox), baks[0]), encoding='utf-8') as f:
        assert len([l for l in f if l.strip()]) == 5
    # 清空后新日志里应有一条「清空当日」自身的审计
    after = gov.read_recent(limit=10)
    assert any('清空当日' in (e.get('action') or '') for e in after)


def test_clear_day_when_nothing(sandbox):
    ok, msg = gov.clear_day()
    assert not ok and '没有' in msg


# ---------------- ② 出网白名单 ----------------

def test_net_explain_empty_allowlist_blocks(sandbox, monkeypatch):
    monkeypatch.setattr(gov, 'net_allowlist', lambda: [])
    ok, why, rule, host = gov.net_explain('https://api.deepseek.com/v1/chat')
    assert ok is False and rule is None and host == 'api.deepseek.com'
    assert '白名单是空的' in why


def test_net_explain_wildcard(sandbox, monkeypatch):
    monkeypatch.setattr(gov, 'net_allowlist', lambda: ['*.github.com'])
    ok, why, rule, _h = gov.net_explain('https://raw.github.com/x/y')
    assert ok is True and rule == '*.github.com' and '命中' in why
    bad, why2, rule2, _h2 = gov.net_explain('https://evil.com/x')
    assert bad is False and rule2 is None and '不在出网白名单' in why2


def test_net_allowed_matches_net_explain(sandbox, monkeypatch):
    """试算与真实拦截必须一致（同一套判定，禁止第二套逻辑）"""
    monkeypatch.setattr(gov, 'net_allowlist', lambda: ['api.example.com'])
    for url in ('https://api.example.com/a', 'https://other.example.com/a', 'not-a-url'):
        ok1, why1, _r, _h = gov.net_explain(url)
        ok2, why2 = gov.net_allowed(url)
        assert ok1 == ok2 and why1 == why2, url


def test_add_net_rule_persists_without_duplication(monkeypatch):
    """加规则走既有 setter（不新增配置键），重复加不产生重复项"""
    saved = {}
    monkeypatch.setattr(gov, '_cfg', lambda: {'net_allowlist': ['a.com']})
    monkeypatch.setattr(gov, '_save_cfg_value', lambda k, v: saved.__setitem__(k, list(v)))
    monkeypatch.setattr(gov, 'net_allowlist', lambda: ['a.com'])
    gov.add_net_rule('b.com')
    assert saved.get('net_allowlist') == ['a.com', 'b.com']
    saved.clear()
    gov.add_net_rule('a.com')                   # 已存在
    assert saved.get('net_allowlist') is None, '重复规则不应重写配置'


# ---------------- 护栏：不动真实配置 ----------------

def test_real_config_untouched(sandbox, monkeypatch, tmp_path):
    before = _hash(CFG)
    _seed(10)
    gov.read_filtered(kind='call', limit=10)
    gov.export_csv(str(tmp_path / 'x.csv'))
    monkeypatch.setattr(gov, 'net_allowlist', lambda: ['*.example.com'])
    gov.net_explain('https://a.example.com/x')
    gov.clear_day()
    assert _hash(CFG) == before, '这些只读/查询操作不得改动真实 config.json'
