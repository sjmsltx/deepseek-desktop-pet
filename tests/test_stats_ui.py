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

# ---------- v3.6d：用量分析窗的模态处理（WX-112 §5 提醒，同一个坑第二次）----------

def test_open_usage_stats_passes_parent_at_construction():
    """「用量分析」新窗必须**构造时**传 parent，否则会重演「看得见点不动」

    背景：WX-112 §5 扫了 `stats_ui.py` 没看到 `activeModalWidget`，
          判断「大概率重演老 A7 的模态阻塞」，让我自查。
    我核实：处理在**宿主侧** `_open_usage_stats`（不在 stats_ui.py 里）——
          `_modal = parent or QApplication.activeModalWidget()`
          `UsageStatsDialog(self, parent=_modal)`
    实测三种写法（收件箱/02-加工/实测-新窗口模态2.py）：
          构造时传 parent=activeModalWidget()  → 模态在祖先链 ✓ 可点
          无 parent                            → 不在祖先链   ✗ 被挡
    ⇒ 写法是对的，但**没人锁住它**。这条把它钉住：
      以后谁把 `parent=_modal` 改成无 parent，或改成事后 setParent，就会红。

    （v3.1d 的结论：运行时 setParent 对已显示的顶层窗无效 —— 必须构造时给。）
    """
    import io as _io
    import os as _os
    root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    src = _io.open(_os.path.join(root, 'desktop_pet.py'), encoding='utf-8').read()
    # ⚠ 切片长度必须够（v3.6e）：函数加了 toggle/非模态说明后变长，
    #   原来截 1200 字符会切掉 activeModalWidget 探测 → 假红。
    #   改用「到下一个同级 def 为止」的边界，不靠固定字符数。
    i = src.index('def _open_usage_stats')
    _j = src.find('\n    def ', i + 10)
    body = src[i:_j if _j > i else i + 4000]

    assert 'activeModalWidget()' in body, (
        '右键路径（不传 parent）丢失了 activeModalWidget 探测 '
        '⇒ 设置面板开着时新窗会点不动')
    assert 'UsageStatsDialog(self, parent=_modal)' in body, (
        'UsageStatsDialog 必须在**构造时**传 parent=_modal '
        '（事后 setParent 对已显示的顶层窗无效，v3.1d 实测）')


def test_usage_stats_modal_path_clickable_not_blocked():
    """结构判据：模态开着时，新窗必须落在模态的祖先链上

    按 Qt 的模态语义：模态只挡「既不是模态自身、也不是模态子孙」的窗口。
    （⚠ 不能用 `isEnabled()` 判 —— 模态不会 disable 其它窗，恒 True，没区分能力；
      也不能用 `activeModalWidget() is not dlg` 判 —— 会把正常判成被挡。
      这两版判据我都写错过，留在这里当反例。）
    """
    from PySide6.QtWidgets import QApplication, QDialog
    app = QApplication.instance()
    if app is None:
        import pytest
        pytest.skip('需要 QApplication')

    from stats_ui import UsageStatsDialog

    class _Modal(QDialog):
        pass

    modal = _Modal()
    modal.setModal(True)
    dlg = UsageStatsDialog(None, parent=modal)      # 复刻 _open_usage_stats 的做法
    try:
        chain, cur = [], dlg
        while cur is not None:
            chain.append(cur)
            cur = cur.parent()
        assert modal in chain, '新窗不在模态的祖先链上 ⇒ 会被模态挡住（点不动）'
    finally:
        dlg.deleteLater()
        modal.deleteLater()

# ---------- v3.6e：用量分析不得挡住设置面板（Owner 2026-10-24 报的真问题）----------

def test_usage_stats_is_not_modal():
    """用量分析必须是**非模态**（show），不能用 exec()

    Owner 原话：「打开用量分析窗口之后想要关闭设置面板，但点击设置面板的
                关闭按钮关不掉。」

    根因：`dlg.exec()` 是应用级模态，会 disable 它的 parent（设置面板）
        ⇒ 设置面板的「关闭」按钮点不到 ⇒ 用户想关整个设置却关不掉。

    这是我自己写出来的：v3.4 为了躲 v3.1d 那个「看得见点不动」用了 exec()，
    结果制造了反向问题「父窗关不掉」。

    ⚠ 判据说明（我这边出过两次错，写在测试里当反例）：
      第一次用 show() 代替 exec() 去测四条路径，全部「能关」——
      **测的不是真实路径**，等于没测。
      所以这条直接断言源码形态，不靠行为模拟。
    """
    import io as _io
    import os as _os
    import tokenize as _tk
    root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    src = _io.open(_os.path.join(root, 'desktop_pet.py'), encoding='utf-8-sig').read()

    # 剥注释与 docstring：上一版只剥行内 '#'，结果命中了函数 docstring 里
    # 那句「原实现 dlg.exec() 是应用级模态」⇒ 假红（自指的又一种形态）。
    toks = list(_tk.generate_tokens(_io.StringIO(src).readline))
    kept = []
    for tk in toks:
        if tk.type in (_tk.COMMENT, _tk.STRING):
            continue
        kept.append(tk.string if tk.type != _tk.NEWLINE else ' ')
    flat = ''.join(kept).replace(' ', '')

    i = flat.find('def_open_usage_stats(')
    assert i != -1, '_open_usage_stats 不见了'
    j = flat.find('def_', i + 30)
    body = flat[i:j if j > i else i + 2500]

    assert 'dlg.exec()' not in body, (
        '_open_usage_stats 又用 exec() 了 —— 它会 disable 设置面板，'
        '用户点不到「关闭」按钮（Owner 2026-10-24 报过的原问题）')
    assert 'dlg.show()' in body, '应改用非模态 show()'


def test_settings_close_also_closes_usage_stats():
    """设置面板关闭时必须**主动**关掉用量分析（否则留孤儿窗口）

    实测结论：QDialog 即使 parent 设成设置面板，parent.hide() 也**不会**
    连带隐藏它 —— 它是顶层窗口。所以必须显式关。
    """
    import io as _io
    import os as _os
    root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    src = _io.open(_os.path.join(root, 'desktop_pet.py'), encoding='utf-8-sig').read()

    assert 'def _close_usage_stats' in src, '缺少 _close_usage_stats'
    assert '_modal.finished.connect(self._close_usage_stats' in src, (
        '没有把设置面板的 finished 接到 _close_usage_stats '
        '⇒ 设置关掉后用量分析会留在桌面上')


def test_usage_stats_toggle_semantics():
    """再点一次入口应关掉已有窗口（toggle），不累积多个窗口

    与「📊 统计悬浮窗」保持同一交互口径。
    """
    import io as _io
    import os as _os
    root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    src = _io.open(_os.path.join(root, 'desktop_pet.py'), encoding='utf-8-sig').read()
    i = src.index('def _open_usage_stats')
    body = src[i:i + 3000]
    # 断言要精确到赋值本身：只查 "_usage_stats_dlg" 子串，
    # 会把 `= None` 那几处也算通过 → 删掉真正的强引用照样绿（证伪抓到的）。
    assert 'self._usage_stats_dlg=dlg' in body.replace(' ', ''), '缺少 self._usage_stats_dlg = dlg（无强引用，窗口会被 GC 收走）'
    assert 'toggle' in body or '_existing' in body, '缺少 toggle 语义（重复点击会开出多个窗）'
