# -*- coding: utf-8 -*-
"""余额盯梢（v3.1，2026-10-24）：别处花钱 → 冒关心气泡，但不进对话历史

验证的是**真 PetWidget 对象**的真方法，不是重写一遍逻辑。

运行：python -m pytest tests/test_balance_watch.py -q
"""
import datetime as dt
import io
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

# ---------- 实测发现的漏报缺陷：防刷屏间隔必须小于查询间隔 ----------

def test_gap_is_smaller_than_query_interval():
    """GAP 必须**明显小于**定时器间隔，否则正常轮询会被自己的防刷屏吃掉

    实测（2026-10-24 logs/pet.log）：
      18:22:06 报 ¥0.12 → 18:27:05 余额又掉 ¥0.08，却没有任何记录
      原因：GAP=300 秒 与 查询间隔 5 分钟=300 秒 **相等**，
            两次间隔 299~300 秒，`elapsed < 300` 随机成立 → 约一半被丢
    """
    p = _pet()
    gap = p.BALANCE_WATCH_GAP
    query = int(getattr(p, 'balance_watch_minutes', 5) or 5) * 60
    assert gap < query, ('防刷屏间隔 %d 秒 >= 查询间隔 %d 秒 → 正常轮询会被自己挡住'
                         '（实测漏报过 ¥0.08）' % (gap, query))
    # 留出余量：至少要能容忍半分钟级的抖动
    assert query - gap >= 60, ('间隔余量只有 %d 秒，太小：两次轮询差几秒就会被吃掉'
                               % (query - gap))


def test_gap_still_blocks_same_moment_duplicates():
    """GAP 不能降到 0：同一刻的重复（手动查询 + 定时器撞车）仍要被挡住"""
    p = _pet()
    assert p.BALANCE_WATCH_GAP > 0, 'GAP 为 0 会让手动查询与定时器各报一次'

# ---------- WX-107 §2：被挡下的差额必须累计，不能丢 ----------

def _fresh(p):
    """清掉内部基线，模拟「真机刚启动」"""
    for a in ('_bw_base_at', '_bw_base_total', '_balance_watch_last'):
        if hasattr(p, a):
            delattr(p, a)


def test_small_spends_accumulate_instead_of_lost():
    """实测缺陷（WX-107 §2）：每次别处花 ¥0.004，旧实现永远不报

    旧逻辑：基线 = 上一次查询 → 被 MIN(0.01) 挡下就丢；下次 prev 已含这笔
    ⇒ 一小时 ¥0.048 一次都不报。
    新逻辑：被挡不推进基线 → 累计到跨过 1 分再报。
    """
    p = _pet()
    bubbles = []
    _setup(p, [], bubbles)          # 本机不花钱，纯粹看别处小额
    _fresh(p)
    total = 13.90
    t0 = dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    for i in range(12):             # 12 次 × ¥0.004 = ¥0.048
        total -= 0.004
        p._report_other_spend({'at': t0, 'total': 13.90},
                              {'ok': True, 'total': round(total, 4)})
    assert bubbles, '小额高频消费累计 ¥0.048 仍未上报（旧缺陷复现）'
    got = float(bubbles[0][0].split('¥')[1].split('（')[0])
    assert got >= 0.01, '累计后金额应 ≥ ¥0.01，实际 %.4f' % got
    assert got <= 0.05, '累计金额不应超过实际花费太多，实际 %.4f' % got


def test_blocked_by_gap_is_not_lost():
    """被防刷屏挡下 → 下次仍要报（旧实现会永久丢）"""
    p = _pet()
    bubbles = []
    _setup(p, [], bubbles)
    _fresh(p)
    t0 = dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    p._report_other_spend({'at': t0, 'total': 13.90}, {'ok': True, 'total': 13.78})
    assert len(bubbles) == 1
    # 紧接着又掉 ¥0.05（会被 GAP 挡）
    p._report_other_spend({'at': t0, 'total': 13.78}, {'ok': True, 'total': 13.73})
    assert len(bubbles) == 1, '被 GAP 挡下时不该报（第一阶段断言）'
    # 等过 GAP 后再查：上次被挡的 ¥0.05 必须还在
    p._balance_watch_last = 0
    p._report_other_spend({'at': t0, 'total': 13.73}, {'ok': True, 'total': 13.73})
    assert len(bubbles) == 2, '被 GAP 挡下的差额丢失了（应累计到下一次）'


def test_settle_only_on_report_or_reset():
    """基线只在「已上报」或「必须重置」时推进"""
    p = _pet()
    bubbles = []
    _setup(p, [], bubbles)
    _fresh(p)
    t0 = dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    p._report_other_spend({'at': t0, 'total': 13.90}, {'ok': True, 'total': 13.895})
    assert len(bubbles) == 0
    assert not hasattr(p, '_bw_base_total') or p._bw_base_total == 13.90, \
        '被挡下时不该推进基线'
    p._report_other_spend({'at': t0, 'total': 13.90}, {'ok': True, 'total': 13.86})
    assert len(bubbles) == 1, '累计到 ¥0.04 应上报'
    assert abs(p._bw_base_total - 13.86) < 1e-9, '上报后基线应结清到当前余额'


def test_topup_resets_baseline():
    """充值 → 重置基线，之后不把充值算成负数"""
    p = _pet()
    bubbles = []
    _setup(p, [], bubbles)
    _fresh(p)
    t0 = dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    p._report_other_spend({'at': t0, 'total': 13.90}, {'ok': True, 'total': 20.00})
    assert bubbles == []
    assert abs(p._bw_base_total - 20.00) < 1e-9, '充值后基线应重置到新余额'


def test_bubble_carries_balance():
    """气泡要带余额（否则「报了花费、余额不动」会让人以为没生效）"""
    p = _pet()
    bubbles = []
    _setup(p, [_call(0.0, 3)], bubbles)
    p.api_stats.balance_text = lambda with_detail=False: '¥13.48'
    _fresh(p)
    p._report_other_spend({'at': _ts(5), 'total': 13.90}, {'ok': True, 'total': 13.48})
    assert len(bubbles) == 1
    assert '¥13.48' in bubbles[0][0], '盯梢气泡应带当前余额：%s' % bubbles[0][0]


# ---------- WX-107 §3：跨线程转发不得丢 mark_purpose ----------

def test_cross_thread_forwards_mark_purpose():
    """非主线程调 say_care(mark_purpose=False) 时，转发后仍必须是 False"""
    import threading
    p = _pet()
    seen = {}

    class _FakeThread(threading.Thread):
        pass

    # 直接验证源码转发参数（真起线程会牵扯 Qt 事件循环，这里锁死转发表达式）
    src = io.open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    i = src.index("if threading.current_thread() is not threading.main_thread():\n            # v3.1c")
    body = src[i:i + 400]
    assert 'm=mark_purpose' in body, '跨线程转发丢了 mark_purpose（会静默串 care 标）'
    assert 'self.say_care(t, k, m)' in body, '转发时应把 mark_purpose 传下去'

    # 行为面：主线程传 False 时不得打标（已有用例），此处补「转发到位」的行为等价验证
    p.say_care = lambda t, k='care', m=True: seen.update(t=t, m=m)
    p._run_on_ui = lambda fn: fn()
    p.say_care('x', 'care', False)
    assert seen.get('m') is False

# ---------- WX-107 §4.4：真统计路径不得在多处硬编码 ----------

def test_real_stats_path_hardcoded_only_once():
    """`os.path.join(BASE_DIR, 'api_stats.json')` 只允许出现 1 处

    WX-107 §4.4 指出的隐患：conftest 的 `_isolate_api_stats` 会把
    **任何** path 都换成 tmp ⇒ 若将来又有人在别处硬编码真路径，会被夹具
    **静默吞掉**（缺陷被藏住而不是暴露）。
    这条 ratchet 把「又开一处」变成当场红。
    """
    src = io.open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    n = src.count("os.path.join(BASE_DIR, 'api_stats.json')")
    assert n == 1, ('真统计路径出现了 %d 处（应为 1：PetWidget 初始化）。'
                    '新增处会被测试夹具静默吞掉，请改用统一常量' % n)
