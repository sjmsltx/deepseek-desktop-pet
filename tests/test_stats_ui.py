# -*- coding: utf-8 -*-
"""用量分析窗口（v3.4，2026-10-24 Owner 需求「统计更丰富，花到哪个模块、时间」）

边界划分（本文件锁的是这个）
- 只读展示：窗口不写任何文件、不改 api_stats 的任何值
- 同源：表格/柱状/用途三者数据都来自 by_day，不另算一套（吃过 D11-3 的苦）
- 旧档：无 by_day 时明说「历史未留存」，**不拿总数摊出假曲线**
- 入口：设置页打开时必须显式传 parent（否则重演「看得见点不动」）

运行：python -m pytest tests/test_stats_ui.py -q
"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import api_stats as _as  # noqa: E402
import stats_ui  # noqa: E402


class _Host(object):
    def __init__(self, st):
        self.theme = {}
        self.api_stats = st


def _st(tmp_path, days=None):
    st = _as.ApiStats(str(tmp_path / 's.json'))
    if days is not None:
        st.by_day = days
        st.day_legacy = not bool(days)
    return st


def _day(cost, count, purpose_cost=None):
    bp = {'chat': {'count': count, 'cost': purpose_cost if purpose_cost is not None else cost}}
    return {'count': count, 'prompt': 100, 'completion': 10, 'total': 110,
            'cost': cost, 'by_purpose': bp}


def _dlg(tmp_path, days=None):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(sys.argv)
    return stats_ui.UsageStatsDialog(_Host(_st(tmp_path, days)))


# ---------- 1. 有数据：三块同源 ----------

def test_table_and_chart_share_same_rows(tmp_path):
    """表格行数必须等于柱状图条数（同源，不能一处有数据一处没有）"""
    d = _dlg(tmp_path, {'2026-10-22': _day(0.01, 2),
                        '2026-10-23': _day(0.02, 3),
                        '2026-10-24': _day(0.03, 4)})
    try:
        assert d.tbl.rowCount() == 3, '表格应有 3 行'
        assert len(d.chart._rows) == 3, '柱状图应有 3 条'
    finally:
        d.close()


def test_summary_has_total_and_daily_avg(tmp_path):
    """汇总行要能回答「一共花了多少、日均多少」"""
    d = _dlg(tmp_path, {'2026-10-23': _day(0.02, 2), '2026-10-24': _day(0.04, 4)})
    try:
        txt = d.lb_sum.text()
        assert '合计' in txt and '日均' in txt, '汇总行缺合计/日均：%r' % txt
        assert '0.03' in txt, '日均应为 (0.02+0.04)/2=0.03，实际：%r' % txt
    finally:
        d.close()


def test_purpose_summarised_over_range_not_today(tmp_path):
    """用途要按**所选范围**汇总，不是只看今天（Owner 问的是「花到哪个模块」）"""
    d = _dlg(tmp_path, {'2026-10-23': _day(0.02, 2, 0.02),
                        '2026-10-24': _day(0.04, 4, 0.04)})
    try:
        txt = d.lb_purpose.text()
        assert '范围内用途' in txt, '用途应标「范围内」：%r' % txt
        assert '¥0.0600' in txt, '应累加两天共 ¥0.06，实际：%r' % txt
    finally:
        d.close()


def test_purpose_range_counts_unknown_days(tmp_path):
    """某天没记用途时要明说「未记用途」，不能悄悄当成 0"""
    days = {'2026-10-23': {'count': 1, 'cost': 0.01, 'prompt': 1, 'completion': 1,
                           'total': 2, 'by_purpose': {}},
            '2026-10-24': _day(0.02, 2)}
    d = _dlg(tmp_path, days)
    try:
        txt = d.lb_purpose.text()
        assert '未记用途' in txt, '应提示有 1 天未记用途：%r' % txt
    finally:
        d.close()


def test_range_filter_limits_rows(tmp_path):
    """范围选「近 7 天」时只显示 7 行（数据多于 7 天）"""
    days = {'2026-10-%02d' % i: _day(0.001, 1) for i in range(1, 11)}
    d = _dlg(tmp_path, days)
    try:
        d.cb_range.setCurrentIndex(0)          # 近 7 天
        assert d.tbl.rowCount() == 7, '近 7 天应显示 7 行，实际 %d' % d.tbl.rowCount()
        d.cb_range.setCurrentIndex(3)          # 全部
        assert d.tbl.rowCount() == 10, '全部应显示 10 行'
    finally:
        d.close()


# ---------- 2. 旧档：不编数字 ----------

def test_legacy_no_fake_chart(tmp_path):
    """旧档无 by_day → 表格空 + 柱状图空 + 明说未留存（绝不画假曲线）"""
    d = _dlg(tmp_path, {})
    try:
        assert d.tbl.rowCount() == 0, '旧档不该凭空造出表格行'
        assert len(d.chart._rows) == 0, '旧档不该画柱（那是编数据）'
        assert '未留存' in d.lb_note.text(), '应明说历史未留存'
        assert '未留存' in d.chart._empty_text
    finally:
        d.close()


def test_legacy_still_readable_today(tmp_path):
    """旧档虽然没按天数据，今日视角的用途/模型仍要能读（不整窗报错）"""
    d = _dlg(tmp_path, {})
    try:
        assert '读取失败' not in d.lb_model.text(), '模型行不该报错'
        assert '读取失败' not in d.lb_purpose.text(), '用途行不该报错'
    finally:
        d.close()


# ---------- 3. 只读：不许改数据 ----------

def test_dialog_does_not_mutate_stats(tmp_path):
    """打开/刷新窗口不得改动 api_stats 的任何值"""
    import copy
    st = _st(tmp_path, {'2026-10-24': _day(0.03, 3)})
    before_day = copy.deepcopy(st.by_day)
    before_today = copy.deepcopy(st.today)
    before_total = copy.deepcopy(st.total)
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(sys.argv)
    d = stats_ui.UsageStatsDialog(_Host(st))
    try:
        d.reload()
        assert st.by_day == before_day, 'by_day 被改了（本窗口必须只读）'
        assert st.today == before_today, 'today 被改了'
        assert st.total == before_total, 'total 被改了'
    finally:
        d.close()


# ---------- 4. 入口源码护栏 ----------

def test_settings_entry_passes_parent():
    """设置页入口必须显式传 self（否则重演「看得见点不动」）"""
    src = open(os.path.join(BASE, 'settings_ui.py'), encoding='utf-8').read()
    assert '_open_usage_stats(self)' in src, \
        '设置页打开用量分析必须传 self 当 parent（否则被应用级模态挡住）'


def test_menu_entry_exists():
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    assert '_open_usage_stats' in src, '右键菜单入口没了'
    assert 'UsageStatsDialog' in src, '未真正调用新窗口（只加菜单项等于没接）'


def test_chart_no_matplotlib():
    """⛔ 不引第三方绘图库（体积大 + 与 PySide6 混用易出字体问题）

    ⚠ 必须先剥注释与 docstring 再匹配 —— 本轮实测踩到：
      stats_ui.py 的注释里写着「为什么不引 matplotlib」，
      直接全文搜会把说明文字判成违规（假红）。
      这与 WX-109 §4.1 那条「护栏命中 docstring」是同一类错。
    """
    import re
    src = open(os.path.join(BASE, 'stats_ui.py'), encoding='utf-8').read()
    body = re.sub(r'"{3}.*?"{3}', '', src, flags=re.S)
    body = re.sub(r"'{3}.*?'{3}", '', body, flags=re.S)
    body = re.sub(r'#.*$', '', body, flags=re.M)
    assert 'matplotlib' not in body.lower(), '不许引 matplotlib（注释里提它没问题，代码里 import 才判红）'
    assert 'QPainter' in body, '应使用 Qt 自绘'
