# -*- coding: utf-8 -*-
"""回归测试：花费构成堆叠图 + 余额历史 + 悬浮窗配色（2026-10-28）

## Owner 需求原话

> 「把他俩的那个颜色区分开来…相当于顺手给他整成那个累加柱状图」

## 钉住 7 件事

1. `_StackedBarChart._paint()` **直接调用不抛异常**（上轮 `drawText` 少参数被 try/except 吞成纯色空图的教训）
2. 绿段有最小可见高度（实测「自己」只占 1.0%，按真实比例只有 1px）
3. 不可拆日（recharge/noisy/nodata）**不画橙段**（避免被读成「别处 0 元」）
4. `spend_split_by_day` 四种 state 判定正确
5. `balance_history` **只记变化点**（余额没变不追加）
6. 余额历史写**独立文件** `balance_history.json`，不进 `api_stats.json`
   （旧版进程每次 save 都会重写 api_stats.json，放一起会被淡默覆盖）
7. 悬浮窗：今日/累计用 `v`（绿），余额用 `vb`（橙）
"""
import io
import json
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
def _qapp():
    _app()
    yield


# ---------------- ① 图能画 ----------------

def _chart():
    import stats_ui
    w = stats_ui._StackedBarChart()
    w.resize(700, 160)
    return w


ROWS = [
    ('2026-10-24', 0.040396, 0.0, 'recharge'),
    ('2026-10-25', 0.051952, 15.218048, 'ok'),
    ('2026-10-26', 0.128563, 12.721437, 'ok'),
    ('2026-10-27', 0.027473, 12.802527, 'ok'),
    ('2026-10-28', 0.151412, 0.0, 'recharge'),
]


def test_stacked_chart_paint_does_not_raise():
    """★ 直接调 _paint：异常必须抛出来，不能被 paintEvent 吞掉"""
    w = _chart()
    w.set_data(ROWS, note='测试')
    w._paint()


def test_stacked_chart_all_states_paint():
    """四种 state 都要能画（空态/全不可拆/全可拆/混合）"""
    w = _chart()
    for rows in (
        [],                                                     # 空
        [('2026-10-24', 0.04, 0.0, 'recharge')],                # 全不可拆
        [('2026-10-25', 0.05, 15.2, 'ok')],                     # 全可拆
        [('2026-10-26', 0.1, 0.0, 'nodata'),
         ('2026-10-27', 0.1, 0.0, 'noisy')],                    # 另两种不可拆
        ROWS,
    ):
        w.set_data(rows)
        w._paint()


def _is_green(c):
    return (abs(c.red() - 110) < 12 and abs(c.green() - 203) < 12
            and abs(c.blue() - 122) < 12)


def test_stacked_chart_green_segment_visible_when_tiny():
    """★ 绿段最小可见高度：本机只占 1% 时也不能只剩 1px

    实测：本机 ¥0.3998 / 别处 ¥40.7420 ⇒ 1.0%。按真实比例算出来 0.34px。

    ⚠ 判据必须是「单根柱子的绿段高度」，不能是「绿像素总数」：
      总数 3px→654、1px→218，两者都过 200 的阈值 ⇒ 抓不住（证伪 B 实测全绿）。
      扫单列则 3px vs 1px 一清二楚。
    """
    w = _chart()
    w.set_data(ROWS, note='真实比例')
    w.show()
    _app().processEvents()
    img = w.grab().toImage()

    # 几何：700 宽 / 5 根柱；pad_l=10，slot=(700-20)/5=136，柱宽 bw=min(34, 136*0.62)=34
    pad_l, pad_r = 10, 10
    n = len(ROWS)
    slot = (img.width() - pad_l - pad_r) / float(n)
    heights = []
    for i in range(n):
        cx = int(pad_l + slot * i + slot / 2.0)      # 柱子中心
        cnt = 0
        # 只扫下半部分：避开顶部图例（「■ 桌宠自己」也是绿色）
        for y in range(img.height() // 2, img.height()):
            if _is_green(img.pixelColor(cx, y)):
                cnt += 1
        heights.append(cnt)
    assert max(heights) >= 2, (
        '单根柱子的绿段只有 %d px 高 ⇒ 最小可见高度失效（应为 3px）' % max(heights))


def test_stacked_chart_unattributable_has_no_orange():
    """★ 不可拆日不能画橙段 —— 否则被读成「那天别处花 0 元」"""
    w = _chart()
    w.set_data([('2026-10-24', 0.5, 20.0, 'recharge')])   # other 有值但 state 不可拆
    w.show()
    _app().processEvents()
    img = w.grab().toImage()
    orange = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if (abs(c.red() - 255) < 12 and abs(c.green() - 160) < 12
                    and abs(c.blue() - 64) < 12):
                orange += 1
    # 图例里有橙字，所以不能要求 0；但柱子区域不该有大块橙
    assert orange < 400, '不可拆日的橙像素 %d 过多（疑似画了橙段）' % orange


# ---------------- ② 拆分算法 ----------------

def _mk_stats(tmp_path):
    import api_stats as AS
    p = tmp_path / 'api_stats.json'
    p.write_text(json.dumps({'by_day': {}, 'calls': []}), encoding='utf-8')
    return AS.ApiStats(str(p))


def test_balance_history_uses_separate_file(tmp_path):
    """★ 余额历史必须落独立文件，不能进 api_stats.json

    原因：在跑的旧版进程每次 save 都重写 api_stats.json（字典里没这个键）
    ⇒ 放一起会被静默覆盖。
    """
    st = _mk_stats(tmp_path)
    st.set_balance({'ok': True, 'total': 50.0, 'granted': 0.0,
                    'topped_up': 50.0, 'currency': 'CNY',
                    'at': '2026-10-28 10:00:00'})
    hist = tmp_path / 'balance_history.json'
    assert hist.exists(), '没生成 balance_history.json'
    data = json.loads(hist.read_text(encoding='utf-8'))
    assert data['points'][0]['total'] == 50.0
    # api_stats.json 里不该有 balance_history
    main = json.loads((tmp_path / 'api_stats.json').read_text(encoding='utf-8'))
    assert 'balance_history' not in main, '余额历史混进了 api_stats.json'


def test_balance_history_only_records_changes(tmp_path):
    """只记变化点：余额相同的重复查询不追加"""
    st = _mk_stats(tmp_path)
    for i, v in enumerate([50.0, 50.0, 50.0, 49.5, 49.5, 49.0]):
        st.set_balance({'ok': True, 'total': v, 'granted': 0.0, 'topped_up': v,
                        'currency': 'CNY', 'at': '2026-10-28 10:0%d:00' % i})
    assert len(st.balance_history) == 3, '应只记 3 个变化点，实际 %d' % len(st.balance_history)
    assert [p['total'] for p in st.balance_history] == [50.0, 49.5, 49.0]


def test_balance_history_survives_reload(tmp_path):
    st = _mk_stats(tmp_path)
    st.set_balance({'ok': True, 'total': 42.0, 'granted': 0.0, 'topped_up': 42.0,
                    'currency': 'CNY', 'at': '2026-10-28 10:00:00'})
    import api_stats as AS
    st2 = AS.ApiStats(str(tmp_path / 'api_stats.json'))
    assert len(st2.balance_history) == 1
    assert st2.balance_history[0]['total'] == 42.0


def test_spend_split_four_states(tmp_path):
    """四种 state 的判定边界"""
    st = _mk_stats(tmp_path)
    st.by_day = {
        '2026-10-24': {'cost': 0.04},   # 前一天无余额点 → nodata
        '2026-10-25': {'cost': 0.05},   # 正常
        '2026-10-26': {'cost': 5.00},   # 本机 > 账户扣费 → noisy
        '2026-10-27': {'cost': 0.03},   # 余额上升 → recharge
    }
    st.balance_history = [
        {'at': '2026-10-24 23:00:00', 'total': 50.0},
        {'at': '2026-10-25 23:00:00', 'total': 49.95},   # 扣 0.05
        {'at': '2026-10-26 23:00:00', 'total': 47.95},   # 扣 2.00
        {'at': '2026-10-27 23:00:00', 'total': 60.00},   # 充值
    ]
    rows = {r['date']: r for r in st.spend_split_by_day()}
    assert rows['2026-10-24']['state'] == 'nodata'
    assert rows['2026-10-25']['state'] == 'ok'
    assert abs(rows['2026-10-25']['other'] - 0.0) < 1e-9      # 0.05 - 0.05
    assert rows['2026-10-26']['state'] == 'noisy'
    assert rows['2026-10-27']['state'] == 'recharge'


def test_spend_split_other_is_account_minus_own(tmp_path):
    st = _mk_stats(tmp_path)
    st.by_day = {'2026-10-25': {'cost': 0.2}}
    st.balance_history = [
        {'at': '2026-10-24 23:00:00', 'total': 100.0},
        {'at': '2026-10-25 23:00:00', 'total': 90.0},
    ]
    r = st.spend_split_by_day()[0]
    assert r['account'] == pytest.approx(10.0)
    assert r['own'] == pytest.approx(0.2)
    assert r['other'] == pytest.approx(9.8)


def test_spend_split_empty_when_no_by_day(tmp_path):
    st = _mk_stats(tmp_path)
    assert st.spend_split_by_day() == []


# ---------------- ③ 悬浮窗配色 ----------------

def test_stats_window_colors_split():
    """★ 今日/累计（桌宠自己）= v 绿色；余额（账户级）= vb 橙色

    实测证据：改前三者都是 objectName('v')，同一个绿色。
    """
    import desktop_pet as dp
    from PySide6.QtWidgets import QLabel
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p._notify = lambda *a, **k: None
    p.say_plain = lambda t, **kw: None
    try:
        p._toggle_api_stats_window()
        _app().processEvents()
        win = getattr(p, '_api_stats_win', None)
        assert win is not None, '悬浮窗没建出来'
        got = {}
        for lb in win.findChildren(QLabel):
            t = lb.text()
            for k, pre in (('today', '今日'), ('total', '累计'), ('bal', '余额')):
                if t.startswith(pre):
                    got[k] = lb.objectName()
        assert got.get('today') == 'v', '今日 objectName=%r（应 v）' % got.get('today')
        assert got.get('total') == 'v', '累计 objectName=%r（应 v）' % got.get('total')
        assert got.get('bal') == 'vb', '余额 objectName=%r（应 vb，账户级要分色）' % got.get('bal')
        win.close()
    finally:
        p.close()


def test_stats_window_renders_two_colors():
    """渲染层确认真有两种颜色（不只改名字）"""
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p._notify = lambda *a, **k: None
    p.say_plain = lambda t, **kw: None
    try:
        p._toggle_api_stats_window()
        _app().processEvents()
        win = getattr(p, '_api_stats_win', None)
        assert win is not None
        img = win.grab().toImage()
        # ⚠ 必须逐像素：11px 字体的笔画只有 1~2px 宽，
        #   步长 2 采样会整行跳过（第一版就是这么假红的）
        seen = set()
        for y in range(img.height()):
            for x in range(img.width()):
                c = img.pixelColor(x, y)
                if c.alpha() > 0:
                    seen.add((c.red(), c.green(), c.blue()))
        assert (110, 203, 122) in seen, (
            '没渲染出绿色（今日/累计）。出现的颜色前 12 种：%s'
            % sorted(seen, key=lambda c: -(c[0] + c[1] + c[2]))[:12])
        assert (255, 160, 64) in seen, (
            '没渲染出橙色（余额）。出现的颜色前 12 种：%s'
            % sorted(seen, key=lambda c: -(c[0] + c[1] + c[2]))[:12])
        win.close()
    finally:
        p.close()


# ---------------- ④ 装配 ----------------

def test_fill_spend_split_is_wired_into_refresh():
    """★ 装配：`_fill_insights` 必须真的调到 `_fill_spend_split`

    上轮教训：只测零件不测装配，撤掉调用点测试仍全绿。
    """
    import desktop_pet as dp
    from stats_ui import UsageStatsDialog
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p._notify = lambda *a, **k: None
    p.say_plain = lambda t, **kw: None
    try:
        p.api_stats.by_day = {'2026-10-25': {'cost': 0.05, 'count': 1, 'prompt': 10,
                                             'completion': 1, 'total': 11,
                                             'cache_hit': 0, 'cache_miss': 10}}
        p.api_stats.balance_history = [
            {'at': '2026-10-24 23:00:00', 'total': 100.0},
            {'at': '2026-10-25 23:00:00', 'total': 95.0},
        ]
        dlg = UsageStatsDialog(p)
        try:
            dlg.lb_stack.setText('构成：—')
            dlg._fill_insights([])
            txt = dlg.lb_stack.text()
            assert txt != '构成：—', '_fill_insights 没调到 _fill_spend_split'
            assert '合计' in txt
        finally:
            dlg.close()
    finally:
        p.close()
