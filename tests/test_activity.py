# -*- coding: utf-8 -*-
"""回归测试：时间活跃度双轴图 + 成本效率 + 余额盯梢间隔设置项（2026-10-28）

## Owner 需求原话

> 「给它加个设置项吧。然后你去优化一下那个用量分析，可以把那个时间与花费的量来
>   作为两个维度进行这个 xy 轴建立，来看这个时间活跃度。」

## 本文件钉住四件事

1. `_DualAxisChart` 能画（**直接调 `_paint()` 让异常抛出来**，不靠 grab 吞）
2. `_fill_activity` 的数字与独立算法一致（用合成数据，不依赖真 api_stats.json）
3. 空数据不崩且空态文案正确
4. `balance_watch_minutes` 能设、能夹、能写入

## 为什么第 1 条要「直接调 _paint()」

我第一版 `drawText` 少给一个参数（5 个而非 6 个），`paintEvent` 的 try/except
把它吞成日志，界面上只是一张 **991 字节的纯色空图** —— 看起来像"画了但没数据"。
⇒ 自绘图形必须在测试里直接调 `_paint()`，让异常暴露。
"""
import os
import sys

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture(autouse=True)
def _ensure_qapp():
    _app()
    yield


def _chart():
    import stats_ui
    w = stats_ui._DualAxisChart()
    w.resize(700, 160)
    return w


def _bars_seed():
    """4 个钟点有数据、20 个没有 —— 用来验证「没数据的小时也画 0」"""
    return [(h,
             10 if h in (10, 13, 18, 23) else 0,
             0.1 if h in (10, 18) else (0.05 if h in (13, 23) else 0.0))
            for h in range(24)]


# ---------------- ① 图能画 ----------------

def test_dual_chart_paint_does_not_raise():
    """★ 直接调 _paint()：异常必须抛出来，不能被 paintEvent 吞掉

    第一版我 `drawText` 少一个参数 ⇒ TypeError 被吞 ⇒ 界面显示纯色空图，
    看起来像"没数据"而不是"画错了"。
    """
    w = _chart()
    w.set_data(_bars_seed(), note='测试')
    w._paint()          # 有异常这里会红


def test_dual_chart_renders_non_empty_pixmap():
    """grab 出来的图必须有多种颜色（纯色 = 什么都没画）"""
    w = _chart()
    w.set_data(_bars_seed(), note='测试')
    w.show()
    _app().processEvents()
    pm = w.grab()
    assert not pm.isNull()
    img = pm.toImage()
    colors = set()
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            colors.add(img.pixelColor(x, y).name())
    assert len(colors) >= 5, '画面颜色只有 %d 种，可能是纯色空图' % len(colors)


def test_dual_chart_empty_state_message():
    w = _chart()
    w.set_data([], empty_text='暂无调用明细')
    w._paint()          # 空态也要能画（画的是文案）
    assert w._empty_text == '暂无调用明细'


def test_dual_chart_all_zero_does_not_divide_by_zero():
    """24 个小时全 0（有 bars 但没数据）—— 不能除零"""
    w = _chart()
    w.set_data([(h, 0, 0.0) for h in range(24)])
    w._paint()


# ---------------- ② 数字与独立算法一致 ----------------

def _make_calls(n_per_hour=2, days=3):
    """合成调用记录：每天若干小时，每小时 n 条"""
    calls = []
    for d in range(days):
        for hour in (9, 12, 15, 18, 21):
            for k in range(n_per_hour):
                calls.append({
                    'time': '2026-10-%02d %02d:%02d:00' % (20 + d, hour, k * 7),
                    'model': 'deepseek-flash',
                    'prompt': 1000, 'completion': 100, 'total': 1100,
                    'cost': 0.01, 'cache_hit': 600, 'cache_miss': 400,
                })
    return calls


def _expected(calls):
    """独立算法（不看被测实现）"""
    import datetime as dt
    by_hour, days, costs = {}, set(), []
    tp = tc = hit = miss = 0
    for c in calls:
        costs.append(float(c['cost']))
        tp += c['prompt']
        tc += c['completion']
        hit += c['cache_hit']
        miss += c['cache_miss']
        d = dt.datetime.strptime(c['time'][:19], '%Y-%m-%d %H:%M:%S')
        days.add(d.date())
        by_hour[d.hour] = by_hour.get(d.hour, 0) + 1
    tot = sum(costs)
    tt = tp + tc
    return {
        'n': len(calls), 'days': len(days),
        'hours_used': len([h for h, v in by_hour.items() if v]),
        'tot': tot, 'avg': tot / len(costs),
        'max': max(costs),
        'hit_pct': 100.0 * hit / (hit + miss),
        'p_pct': 100.0 * tp / tt,
        'per1k': tot / (tt / 1000.0),
    }


def _dialog_with_calls(calls):
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **kw: True
    p._notify = lambda *a, **kw: None
    p.say_plain = lambda t, **kw: None
    p.api_stats.calls = list(calls)
    from stats_ui import UsageStatsDialog
    dlg = UsageStatsDialog(p)
    return p, dlg


def test_activity_numbers_match_independent_calc():
    calls = _make_calls()
    exp = _expected(calls)
    p, dlg = _dialog_with_calls(calls)
    try:
        dlg._fill_activity()
        act = dlg.lb_act.text()
        eff = dlg.lb_cost_eff.text()
        assert str(exp['n']) in act
        assert '覆盖 %d 天' % exp['days'] in act
        assert '%d/24' % exp['hours_used'] in act
        assert '¥%.4f' % exp['tot'] in eff
        assert '¥%.5f' % exp['avg'] in eff
        assert '¥%.4f' % exp['max'] in eff
        assert '%.0f%%' % exp['hit_pct'] in eff
        assert '%.0f%%' % exp['p_pct'] in eff
        assert '¥%.5f' % exp['per1k'] in eff
    finally:
        dlg.close()
        p.close()


def test_activity_chart_gets_24_buckets():
    """即使只有 5 个钟点有数据，也必须给 24 个桶（才能看出哪段是空的）"""
    p, dlg = _dialog_with_calls(_make_calls())
    try:
        dlg._fill_activity()
        assert len(dlg.chart_act._bars) == 24
        hours = [h for h, c, v in dlg.chart_act._bars]
        assert hours == list(range(24))
    finally:
        dlg.close()
        p.close()


def test_activity_empty_calls_no_crash():
    p, dlg = _dialog_with_calls([])
    try:
        dlg._fill_activity()
        assert '暂无' in dlg.lb_act.text()
    finally:
        dlg.close()
        p.close()


def test_activity_bad_timestamp_counted_not_crashing():
    """时间戳无法解析时不该崩，且要在样本说明里标出来"""
    calls = _make_calls()
    calls.append({'time': 'not-a-time', 'cost': 0.01, 'prompt': 10,
                  'completion': 1, 'cache_hit': 0, 'cache_miss': 10})
    p, dlg = _dialog_with_calls(calls)
    try:
        dlg._fill_activity()
        assert '无法解析' in dlg.chart_act._note
    finally:
        dlg.close()
        p.close()


def test_fill_insights_actually_calls_activity():
    """★ 装配测试：`_fill_insights` 必须真的调到 `_fill_activity`

    为什么补这条：我把调用点改成 `pass` 做证伪时，**11 条测试全绿** ——
    因为前面每条都直接调 `dlg._fill_activity()`，绕过了「有没有接进刷新流程」。
    ⇒ 这就是「测试了零件、没测试装配」。
    """
    calls = _make_calls()
    p, dlg = _dialog_with_calls(calls)
    try:
        # ⚠ 不能断言「初始是占位」：`__init__` 内部已经 reload 过一次，文案早被填好了。
        #   要测「调用链还在不在」，必须**手动重置成占位**再去跑刷新。
        dlg.lb_act.setText('活跃度：—')
        dlg.lb_cost_eff.setText('成本效率：—')

        dlg._fill_insights([])      # 走刷新流程（不是直接调 _fill_activity）

        txt = dlg.lb_act.text()
        assert txt != '活跃度：—', '_fill_insights 没调到 _fill_activity（文案还停在占位）'
        assert str(len(calls)) in txt, '填了但样本数不对：%r' % txt
        eff = dlg.lb_cost_eff.text()
        assert eff != '成本效率：—', '_fill_insights 没填成本效率'
        assert '合计' in eff
    finally:
        dlg.close()
        p.close()


# ---------------- ③ balance_watch_minutes 设置项 ----------------

def test_set_balance_watch_minutes_writes_and_clamps():
    import desktop_pet as dp
    p = dp.PetWidget()
    saved = []
    p._save_cfg_value = lambda k, v, **kw: (saved.append((k, v)), True)[1]
    p._notify = lambda *a, **kw: None
    p.say_plain = lambda t, **kw: None
    try:
        assert p._set_balance_watch_minutes(10) == 10
        assert p.balance_watch_minutes == 10
        assert saved[-1] == ('balance_watch_minutes', 10)
        assert p._set_balance_watch_minutes(0) == 1          # 下限夹紧
        assert p._set_balance_watch_minutes(999) == 60       # 上限夹紧
        assert isinstance(p._set_balance_watch_minutes('abc'), int)   # 非法值不崩
    finally:
        p.close()


def test_balance_watch_minutes_timer_reschedules_when_active():
    """定时器已启动时改间隔 → 立即重排（这是「立即生效」的关键路径）"""
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **kw: True
    p._notify = lambda *a, **kw: None
    p.say_plain = lambda t, **kw: None
    try:
        tmr = p.balance_watch_timer
        tmr.start(5 * 60000)
        assert tmr.isActive()
        p._set_balance_watch_minutes(12)
        assert tmr.interval() == 12 * 60000
        p._set_balance_watch_minutes(1)
        assert tmr.interval() == 60000      # 60000 下限保护
    finally:
        p.close()


def test_settings_has_balance_watch_minutes_spinbox():
    """设置页必须有「1~60 分钟」的控件，且回填 host 当前值"""
    import desktop_pet as dp
    from PySide6.QtWidgets import QSpinBox
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **kw: True
    p._notify = lambda *a, **kw: None
    p.say_plain = lambda t, **kw: None
    p.balance_watch_minutes = 12
    dlg = dp.SettingsDialog(p)
    try:
        found = None
        for sb in dlg.findChildren(QSpinBox):
            if sb.suffix() == ' 分钟' and sb.minimum() == 1 and sb.maximum() == 60:
                found = sb
                break
        assert found is not None, '设置页找不到 1~60 分钟的 QSpinBox'
        assert found.value() == 12, '回填值不对：%r' % found.value()
    finally:
        dlg.close()
        p.close()
