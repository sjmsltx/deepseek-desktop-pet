# -*- coding: utf-8 -*-
"""治理增强③：日成本上限测试（2026-09-21）

要点：
  · 成本口径**只读 api_stats.json**，不写第二套计价
  · 关上限 / 上限为 0 / 统计文件缺失 / 跨天 → 一律放行
  · 超限 → 拒绝并给可操作提示（含到哪调）
  · 拦截点在 _run_task（真正花钱前），且**不动 config.json**
"""
import json
import os
import sys
import time

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import governance as gov  # noqa: E402


def _write_stats(tmp_path, cost, date=None):
    p = tmp_path / 'api_stats.json'
    p.write_text(json.dumps({'date': date or time.strftime('%Y-%m-%d'),
                             'today': {'cost': cost, 'count': 1}, 'total': {}}), encoding='utf-8')
    return str(p)


def test_default_enabled_and_limit_20(tmp_path, monkeypatch):
    monkeypatch.setattr(gov, '_cfg', lambda: {})
    assert gov.cost_limit_enabled() is True
    assert gov.cost_limit_daily() == 20.0


def test_today_cost_reads_stats_file(tmp_path):
    p = _write_stats(tmp_path, 3.5)
    assert gov.today_cost(p) == pytest.approx(3.5)


def test_today_cost_zero_when_file_missing(tmp_path):
    assert gov.today_cost(str(tmp_path / 'nope.json')) == 0.0


def test_today_cost_ignores_stale_date(tmp_path):
    """统计文件是昨天的 → 今日成本按 0 算（跨天不误拦）"""
    p = _write_stats(tmp_path, 99.0, date='2000-01-01')
    assert gov.today_cost(p) == 0.0


def test_check_cost_passes_under_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(gov, '_cfg', lambda: {'cost_limit_enabled': True, 'cost_limit_daily': 20})
    monkeypatch.setattr(gov, 'today_cost', lambda path=None: 5.0)
    ok, why, used = gov.check_cost()
    assert ok is True and why == '' and used == 5.0


def test_check_cost_blocks_over_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(gov, '_cfg', lambda: {'cost_limit_enabled': True, 'cost_limit_daily': 20})
    monkeypatch.setattr(gov, 'today_cost', lambda path=None: 20.5)
    ok, why, used = gov.check_cost()
    assert ok is False and used == 20.5
    assert '已花 ¥20.50' in why and '¥20.00' in why
    assert '用量与计费' in why, '提示必须告诉用户去哪儿调'


def test_check_cost_counts_estimate(tmp_path, monkeypatch):
    monkeypatch.setattr(gov, '_cfg', lambda: {'cost_limit_enabled': True, 'cost_limit_daily': 10})
    monkeypatch.setattr(gov, 'today_cost', lambda path=None: 9.5)
    assert gov.check_cost()[0] is True
    assert gov.check_cost(estimate=1.0)[0] is False


def test_check_cost_disabled_or_zero_always_passes(monkeypatch):
    monkeypatch.setattr(gov, 'today_cost', lambda path=None: 999.0)
    monkeypatch.setattr(gov, '_cfg', lambda: {'cost_limit_enabled': False, 'cost_limit_daily': 1})
    assert gov.check_cost()[0] is True
    monkeypatch.setattr(gov, '_cfg', lambda: {'cost_limit_enabled': True, 'cost_limit_daily': 0})
    assert gov.check_cost()[0] is True, '上限 0 = 不限'


def test_run_task_is_gated_and_config_untouched(monkeypatch):
    """端到端：超限时 _run_task 不发请求、给提示、写 deny 审计；且不动 config.json"""
    import hashlib

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    assert app is not None
    import desktop_pet as dp

    cfg = os.path.join(BASE, 'config.json')
    before = hashlib.md5(open(cfg, 'rb').read()).hexdigest() if os.path.isfile(cfg) else ''

    blocked = {'why': ''}
    monkeypatch.setattr(gov, 'check_cost', lambda estimate=0.0: (False, '今日已花 ¥25.00，达到上限 ¥20.00', 25.0))
    monkeypatch.setattr(gov, 'log_event', lambda *a, **k: blocked.__setitem__('why', a[3] if len(a) > 3 else ''))

    p = dp.PetWidget()
    emitted = []
    p.ai_reply_signal.connect(lambda s: emitted.append(s))
    started = []
    import threading as _threading
    monkeypatch.setattr(_threading, 'Thread',
                        lambda *a, **k: type('T', (), {'start': lambda self: started.append(1)})())
    p._run_task('测试一句话')

    assert started == [], '超限时不得起线程（不发请求）'
    assert emitted and '已暂停本次调用' in emitted[0] and '¥20.00' in emitted[0], emitted
    assert '¥20.00' in blocked['why'], '要写一条 deny 审计'
    assert getattr(p, '_ai_busy', False) is False, '不得把界面卡在 busy（闸门要在改状态之前）'
    after = hashlib.md5(open(cfg, 'rb').read()).hexdigest() if os.path.isfile(cfg) else ''
    assert after == before, '成本判定不得改动 config.json'
