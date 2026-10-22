# -*- coding: utf-8 -*-
"""批 C 护栏：**成本用途分项**（Owner 2026-09-26 14:14 批「做」✓）

微信侧委托的六条验收（`WX-桌宠-20260926-04` §二）：
  ① 给 `api_stats.record()` 加 purpose 维度 ✓
  ② ⭐ **向前兼容旧数据** ✓（历史无 purpose → 不丢账 ✗ 不炸旧文件 ✗）
  ③ 呈现：用量页在「桌宠今日花费」下**按用途分列** ✓（金额 + 次数/占比 ✓ 措辞仍点明余额共享 ✓）
  ④ ⭐ **对账：各分项之和 = 总花费** ✓
  ⑤ ⭐ **不得影响拦截** ✗（拦不拦只看 `today_cost()` ✓ 余额仍不作依据 ✓）
  ⑥ 验收：旧数据兼容 / 求和一致 / `check_cost` 体内仍无 `balance` / 新维度有新增用例 ✓
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _src(name):
    return Path(ROOT / name).read_text(encoding='utf-8')


def _stats(tmp_path):
    """造一个干净的 ApiStats（不读真档 ✓）"""
    import api_stats
    st = api_stats.ApiStats(str(tmp_path / 'api_stats.json'))
    st.today = {'count': 0, 'prompt': 0, 'completion': 0, 'total': 0, 'cost': 0.0,
                'cache_hit': 0, 'cache_miss': 0, 'date': __import__('datetime').date.today().isoformat(),
                'unknown': 0}
    return st


def _usage(p=1000, c=500):
    return {'prompt_tokens': p, 'completion_tokens': c}


# ── ① + ④ 分项记得到 + **守恒**（分项之和 = 总账）──────────────────────
def test_purpose_recorded_and_conserved(tmp_path):
    st = _stats(tmp_path)
    st.record(_usage(), 'deepseek-flash', purpose='chat')
    st.record(_usage(), 'deepseek-flash', purpose='chat')
    st.record(_usage(), 'deepseek-flash', purpose='care')
    st.record(_usage(), 'deepseek-flash', purpose='tools')
    rows = st.purpose_breakdown()
    assert rows, '用途分项为空 ✗'
    assert {r['purpose'] for r in rows} == {'chat', 'care', 'tools'}, rows
    total = float(st.today['cost'])
    ssum = sum(float(r['cost']) for r in rows)
    assert abs(ssum - total) < 1e-6, f'⭐ 对账失败：分项之和 {ssum} ≠ 总账 {total} ✗'
    assert st.today['count'] == 4, st.today['count']
    # 次数也要对得上
    assert sum(int(r['count']) for r in rows) == st.today['count'], '次数之和 ≠ 总次数 ✗'


def test_breakdown_sorted_desc_and_share(tmp_path):
    st = _stats(tmp_path)
    for _ in range(3):
        st.record(_usage(2000, 1000), 'deepseek-flash', purpose='care')
    st.record(_usage(100, 50), 'deepseek-flash', purpose='chat')
    rows = st.purpose_breakdown()
    assert rows[0]['purpose'] == 'care', rows
    assert 0.0 < rows[0]['share'] <= 1.0, rows
    assert abs(sum(r['share'] for r in rows) - 1.0) < 1e-6, '占比之和应为 1 ✓'


# ── ② 向前兼容：旧数据（无 by_purpose）→ 不丢账 · 不炸 ─────────────────
def test_legacy_file_compatible(tmp_path):
    import api_stats
    p = tmp_path / 'api_stats.json'
    p.write_text(json.dumps({'date': __import__('datetime').date.today().isoformat(),
                             'today': {'count': 7, 'cost': 1.23, 'prompt': 10, 'completion': 5,
                                       'total': 15, 'cache_hit': 0, 'cache_miss': 10, 'unknown': 0,
                                       'date': __import__('datetime').date.today().isoformat()},
                             'total': {'count': 7, 'cost': 1.23, 'prompt': 10, 'completion': 5,
                                       'total': 15, 'cache_hit': 0, 'cache_miss': 10, 'unknown': 0}}),
              encoding='utf-8')
    st = api_stats.ApiStats(str(p))
    assert st.purpose_breakdown() == [], '旧档应返回空分项 ✓'
    assert getattr(st, 'purpose_legacy', False) is True, '旧档应标记 legacy ✓'
    assert float(st.today.get('cost') or 0) == 1.23, '⭐ 总账不得丢 ✗'
    # 旧档上继续记账 → 自动长出 by_purpose ✓ 且总账继续累加 ✓
    st.record(_usage(), 'deepseek-flash', purpose='care')
    rows = st.purpose_breakdown()
    assert rows and rows[0]['purpose'] == 'care', rows
    assert float(st.today['cost']) > 1.23, '总账应继续累加 ✓'


# ── ③ 白名单：未知用途 → other（不报错 ✗）─────────────────────────────
def test_unknown_purpose_falls_back(tmp_path):
    st = _stats(tmp_path)
    st.record(_usage(), 'deepseek-flash', purpose='whatever')
    st.record(_usage(), 'deepseek-flash', purpose=None)
    st.record(_usage(), 'deepseek-flash')                      # 缺省 → chat ✓
    got = {r['purpose'] for r in st.purpose_breakdown()}
    assert 'other' in got and 'chat' in got, got


# ── 回归：**默认参数不改变既有行为**（逐字段一致 ✓）────────────────────
def test_default_call_unchanged(tmp_path):
    a = _stats(tmp_path / 'a')
    b = _stats(tmp_path / 'b')
    a.record(_usage(300, 200), 'deepseek-flash')               # 新签名（缺省 purpose）✓
    b.record(_usage(300, 200), 'deepseek-flash', purpose='chat')
    for k in ('count', 'prompt', 'completion', 'total', 'cost', 'cache_hit', 'cache_miss'):
        assert a.today[k] == b.today[k], f'{k} 不一致 ✗'
    assert abs(float(a.today['cost']) - float(b.today['cost'])) < 1e-9


# ── ⑤ 拦截不受影响（分项只看得清 ✗）──────────────────────────────────
def test_check_cost_source_still_has_no_balance():
    src = _src('governance.py')
    i = src.index('def check_cost')
    j = src.index('def ', i + 10)
    body = src[i:j]
    for bad in ('balance', 'query_balance', 'total_balance', 'purpose'):
        assert bad not in body, f'check_cost 里出现 {bad} ✗（拦截只看 today_cost ✓）'


def test_settings_shows_purpose_split_and_shared_wording():
    s = _src('settings_ui.py')
    assert 'lb_purposes' in s, '缺用途分列控件 ✗'
    assert 'purpose_breakdown()' in s, '分列应取 purpose_breakdown() ✓'
    assert '按用途' in s, '应显示"按用途" ✓'
    assert '账户余额（全项目共享）' in s, '余额共享措辞必须保留 ✓'
    assert '历史数据无用途维度' in s, '旧档应明示而非编数字 ✗'


def test_record_exposes_purpose_kwarg():
    import inspect
    import api_stats
    sig = inspect.signature(api_stats.ApiStats.record)
    assert 'purpose' in sig.parameters, 'record 缺 purpose 参数 ✗'
    assert sig.parameters['purpose'].default == 'chat', '缺省必须为 chat ✓（否则改变既有行为 ✗）'
