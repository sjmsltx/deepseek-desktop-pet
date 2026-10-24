# -*- coding: utf-8 -*-
"""余额盯梢（v3.1，2026-10-24）：别处花钱 → 冒关心气泡，但不进对话历史

验证的是**真 PetWidget 对象**的真方法，不是重写一遍逻辑。

运行：python -m pytest tests/test_balance_watch.py -q
"""
import datetime as dt
import os
import sys
import threading

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def _pet():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(sys.argv)
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    return p


class _StatsStub(object):
    """只提供盯梢要用的两个东西：lock + calls"""

    def __init__(self, calls):
        self.lock = threading.Lock()
        self.calls = calls


def _setup(p, calls, bubbles):
    p.balance_watch = True
    p._balance_watch_last = 0
    p.api_stats = _StatsStub(calls)
    p.say_care = lambda text, **k: bubbles.append((text, k))


def _ts(minutes_ago):
    return (dt.datetime.now() - dt.timedelta(minutes=minutes_ago)).strftime('%Y-%m-%d %H:%M:%S')


def _call(cost, minutes_ago):
    return {'time': _ts(minutes_ago), 'cost': cost, 'model': 'deepseek-flash'}


# ---------- 核心：别处花了钱 → 报 ----------

def test_reports_other_spend():
    """余额掉 0.42、本机只花 0.0101 → 应报「别处约 ¥0.4099」"""
    p = _pet()
    bubbles = []
    _setup(p, [_call(0.0101, 3)], bubbles)
    prev = {'at': _ts(5), 'total': 13.90, 'ok': True}
    info = {'ok': True, 'total': 13.48}
    p._report_other_spend(prev, info)
    assert len(bubbles) == 1, '别处花了 ¥0.41 却没冒气泡'
    text, kw = bubbles[0]
    assert '别处用了约 ¥0.4099' in text, '金额算错：%s' % text
    assert kw.get('mark_purpose') is False, '盯梢气泡不该打「主动关心」用途标'


def test_ignores_when_all_spent_by_self():
    """余额掉 0.0101、本机正好花 0.0101 → 别的程序没花钱 → 不报"""
    p = _pet()
    bubbles = []
    _setup(p, [_call(0.0101, 3)], bubbles)
    p._report_other_spend({'at': _ts(5), 'total': 13.90}, {'ok': True, 'total': 13.8899})
    assert bubbles == [], '本机自己花的钱被误报成「别处花费」'


def test_ignores_topup():
    """余额变多（充值）→ 不报"""
    p = _pet()
    bubbles = []
    _setup(p, [], bubbles)
    p._report_other_spend({'at': _ts(5), 'total': 13.48}, {'ok': True, 'total': 20.00})
    assert bubbles == [], '充值不该报成花费'


def test_ignores_stale_snapshot():
    """旧快照超过 1 小时 → 窗口太长不归因"""
    p = _pet()
    bubbles = []
    _setup(p, [], bubbles)
    p._report_other_spend({'at': _ts(120), 'total': 20.00}, {'ok': True, 'total': 13.48})
    assert bubbles == [], '两小时的窗口不该报（说不清是谁花的）'


def test_ignores_below_one_cent():
    """别处只花了 0.005（不到 1 分）→ 当噪声不报"""
    p = _pet()
    bubbles = []
    _setup(p, [], bubbles)
    p._report_other_spend({'at': _ts(5), 'total': 13.90}, {'ok': True, 'total': 13.895})
    assert bubbles == [], '不到 1 分钱不该打扰'


def test_ignores_when_disabled():
    p = _pet()
    bubbles = []
    _setup(p, [], bubbles)
    p.balance_watch = False
    p._report_other_spend({'at': _ts(5), 'total': 13.90}, {'ok': True, 'total': 13.48})
    assert bubbles == [], '开关关掉后不该报'


def test_cooldown_prevents_spam():
    """连续两次大额差 → 第二次被最小间隔挡住"""
    p = _pet()
    bubbles = []
    _setup(p, [], bubbles)
    prev = {'at': _ts(5), 'total': 13.90}
    p._report_other_spend(prev, {'ok': True, 'total': 13.48})
    p._report_other_spend(prev, {'ok': True, 'total': 13.48})
    assert len(bubbles) == 1, '最小间隔没生效（连冒了 %d 条）' % len(bubbles)


# ---------- 关键性质：盯梢气泡不污染聊天面板 ----------

def test_watch_bubble_does_not_enter_chat_history():
    """真控件验证：say_care 不写 display_msgs、不打用途标"""
    p = _pet()
    n0 = len(p.display_msgs)
    p._pending_purpose = ''
    p.say_care('别处用了约 ¥0.4099（17:39 → 17:44）', mark_purpose=False)
    assert len(p.display_msgs) == n0, '盯梢气泡被写进了聊天面板（污染回归）'
    assert p._pending_purpose == '', 'mark_purpose=False 仍打了用途标（会污染记账分项）'


def test_normal_care_still_marks_purpose():
    """默认行为不变：普通主动关心仍打 care 标"""
    p = _pet()
    p._pending_purpose = ''
    p.say_care('记得站起来活动一下', kind='care')
    assert p._pending_purpose == 'care', '普通关心应仍打 care 标（改坏了）'


# ---------- 线路：定时器与开关 ----------

def test_timer_not_started_until_armed():
    p = _pet()
    assert not p.balance_watch_timer.isActive(), '盯梢定时器不该一开机就跑'
    p._balance_watch_arm()
    assert p.balance_watch_timer.isActive(), 'arm 之后定时器应启动'
    p.balance_watch_timer.stop()


def test_tick_silent_when_disabled():
    p = _pet()
    hits = []
    p._query_balance_async = lambda manual=False: hits.append(manual)
    p.balance_watch = False
    p._balance_watch_tick()
    assert hits == [], '开关关掉后不该再查余额'
    p.balance_watch = True
    p._balance_watch_tick()
    assert hits == [False], '开启后应静默查一次余额'


def test_toggle_switch_persists():
    p = _pet()
    saved = []
    p._save_cfg_value = lambda k, v: saved.append((k, v)) or True
    p.balance_watch = True
    p.toggle_balance_watch()
    assert p.balance_watch is False
    assert saved[-1] == ('balance_watch', False), '开关状态没写进 config'

# ---------- 接线：走真实入口 _on_balance_result，验「覆盖前存旧快照」 ----------

class _StatsStub2(object):
    def __init__(self, calls, bal):
        self.lock = threading.Lock()
        self.calls = calls
        self.balance = bal

    def set_balance(self, info):
        self.balance = dict(info) if info else None

    def balance_text(self, detail=False):
        return ''


def test_on_balance_result_captures_prev_and_reports(monkeypatch):
    """真入口验证：_on_balance_result 必须在覆盖余额前拿到旧快照"""
    p = _pet()
    bubbles = []
    calls = [_call(0.0101, 3)]
    p.api_stats = _StatsStub2(calls, {'at': _ts(5), 'total': 13.90, 'ok': True})
    p.balance_watch = True
    p._balance_watch_last = 0
    p.say_care = lambda text, **k: bubbles.append((text, k))
    p._on_balance_result({'ok': True, 'total': 13.48})
    assert len(bubbles) == 1, '走真实入口没触发盯梢（旧快照没取到 / 没调到 _report_other_spend）'
    assert '别处用了约 ¥0.4099' in bubbles[0][0]
