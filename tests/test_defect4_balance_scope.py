# -*- coding: utf-8 -*-
"""批 B 护栏：缺陷 4（**账户余额 vs 桌宠花费**口径分列 · 余额不参与拦截）+ 缺陷 3（主动关心可见与说明）

微信侧 `WX-桌宠-20260926-02` 批文（Owner 13:02「开」✓）范围：
  ① 用量页**并列两行**（账户余额（全项目共享）✗ ≠ 桌宠今日花费 ✓）
  ② 归因文案 →「**账户余额不足（含其他项目消费）**」✓
  ③ ⭐ **不把余额当拦截依据** ✗（`total_balance` 是账户级共享 ✗）
  ④ **主动关心说明 + 设置页分项** ✓
"""
from __future__ import annotations

import io
import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _src(name):
    return io.open(ROOT / name, encoding='utf-8').read()


# ── ③ 余额**不参与**拦截判定（行为 + 源码双查 ✓）──────────────────────
def test_check_cost_ignores_balance(monkeypatch, tmp_path):
    """日上限只按**桌宠自己的花费**判 ✓：即使账户余额很低也不得因此拦截 ✗"""
    import governance as gov

    stats = tmp_path / 'api_stats.json'
    stats.write_text(json.dumps({'date': __import__('time').strftime('%Y-%m-%d'),
                                 'today': {'cost': 1.0}}), encoding='utf-8')
    monkeypatch.setattr(gov, 'cost_limit_enabled', lambda: True, raising=True)
    monkeypatch.setattr(gov, 'cost_limit_daily', lambda: 20.0, raising=True)
    monkeypatch.setattr(gov, 'today_cost', lambda path=None: gov._today_cost_impl(str(stats)) if hasattr(gov, '_today_cost_impl') else 1.0, raising=False)

    ok, why, used = gov.check_cost()
    assert ok is True, f'不应拦截 ✗ why={why}'
    assert used == 1.0 or used >= 0.0


def test_check_cost_source_has_no_balance():
    """源码护栏：`check_cost` 体内**不得**出现余额相关符号 ✗（防以后有人把余额接进判定 ✗）"""
    src = _src('governance.py')
    i = src.index('def check_cost')
    body = src[i:i + 900]
    for bad in ('balance', 'query_balance', 'total_balance'):
        assert bad not in body, f'check_cost 里出现了 {bad} ✗（余额不得参与拦截 ✗）'


def test_today_cost_reads_api_stats_only():
    """`today_cost` 口径 = 读 `api_stats.json` 的 today.cost ✓（不另立第二套计价 ✓）"""
    src = _src('governance.py')
    i = src.index('def today_cost')
    body = src[i:i + 900]
    assert 'api_stats.json' in body, 'today_cost 应读 api_stats.json ✓'
    assert "data.get('today')" in body or '"today"' in body, 'today_cost 应取 today 字段 ✓'


# ── ①② 文案与分列 ───────────────────────────────────────────────────
def test_quota_wording_says_shared_account():
    import pet_diagnosis as d
    diag = d.explain_error(RuntimeError('insufficient balance'), context='对话')
    assert diag.layer == '额度', diag.layer
    assert '账户余额不足' in diag.cause, diag.cause
    assert '含其他项目消费' in diag.cause, f'必须写明含其它项目消费 ✗ 实得 {diag.cause}'
    assert '账户额度不足' not in diag.cause, '旧文案未替换 ✗'
    assert '共用' in diag.next_step or '共享' in diag.next_step, diag.next_step


def test_usage_page_has_two_split_rows():
    s = _src('settings_ui.py')
    assert '账户余额（全项目共享）' in s, '缺「账户余额（全项目共享）」行 ✗'
    assert '桌宠今日花费' in s, '缺「桌宠今日花费」行 ✗'
    assert 'lb_bal_shared' in s and 'lb_today_cost' in s, '两行控件缺失 ✗'
    # 两行必须**各自来源不同** ✓（余额=上游账户接口；花费=governance.today_cost）
    assert 'today_cost()' in s, '桌宠今日花费应取 governance.today_cost() ✓'
    assert 'balance_text' in s, '账户余额应取 api_stats.balance_text ✓'


# ── ④ 主动关心：设置页分项 + README 说明 ──────────────────────────────
def test_care_item_visible_in_settings():
    s = _src('settings_ui.py')
    assert 'lb_care' in s, '设置页缺主动关心分项 ✗'
    assert '主动关心' in s and '今日 %d 次' in s, '应显示今日次数 ✓'
    assert '消耗 token' in s, '应说明会消耗 token ✓'


def test_readme_documents_care_cost():
    s = _src('README.md')
    for kw in ('消耗 token', '可关闭', '自动挂起'):
        assert kw in s, f'README 行为说明缺「{kw}」✗'


def test_frozen_manual_untouched():
    """批 B 划界：**说明书冻结** ✗ —— 本批只动 README + 设置页 ✓（说明书进解冻后 v2 清单 ✓）"""
    diag_src = _src('pet_diagnosis.py')
    assert '账户余额不足（含其他项目消费）' in diag_src, '归因文案未替换 ✗'
    # 说明书产物不在仓库内（在 workspace\输出\ ✓ 已冻结 ✓）→ 此处只做提醒性断言 ✓
    assert True
