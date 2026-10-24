# -*- coding: utf-8 -*-
"""stats_ui.py — 用量分析窗口（v3.4，2026-10-24）

Owner 2026-10-24 需求：「统计的那个东西更加丰富一点，样式也可以更加丰富一点。
比如说统计花到哪儿呢花到哪个模块，时间啊等等等等」

与既有「📊 统计悬浮窗」的分工
------------------------------
- 统计悬浮窗（desktop_pet._toggle_api_stats_window）：320px 置顶小窗，**实时**看
  今日/累计/缓存命中/余额。窄、常驻、不占地方。
- 本窗口（UsageStatsDialog）：**大窗看历史**。按天表格 + 柱状趋势 + 用途占比。
  两者职责不同，本窗口不改动小窗（小窗已通过微信 A7 验收）。

数据来源（⛔ 不另立一套计价）
------------------------------
全部来自 `ApiStats.day_breakdown()` / `purpose_breakdown()` / `model_breakdown()`，
与闸门判定读的 `today.cost` 同源。本项目吃过「第二套计价」的苦（D11-3 三个数对不上），
所以这里**只做展示，不做计算**。

历史缺失怎么显示（★ 重要）
------------------------------
`by_day` 是 2026-10-24 才加的，更早的天数**确实没存**（旧版只有 today + total +
最近 200 条 calls，实测只覆盖 10 天）。
⇒ 旧档打开时显示「历史未留存，从 2026-10-24 开始记录」，
⛔ **绝不拿总花费摊到日期上画假曲线** —— 那正是 D11-3 的老毛病。
"""
import datetime
import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QHBoxLayout,
                               QHeaderView, QLabel, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from pet_theme import DEFAULT_THEME, color as theme_color

_log = logging.getLogger('pet.stats')

# 用途键 → 中文（与 api_stats.PURPOSE_LABELS 同源；这里只做兜底取不到时的回退）
_PURPOSE_FALLBACK = {'chat': '对话', 'care': '主动关心', 'tools': '工具',
                     'games': '小游戏', 'other': '其它', 'legacy': '历史未分类'}

RANGE_CHOICES = ((7, '近 7 天'), (14, '近 14 天'), (30, '近 30 天'), (0, '全部'))


class _BarChart(QWidget):
    """柱状趋势图（Qt 自绘，⛔ 不引第三方绘图库）

    为什么不引 matplotlib：体积大、和 PySide6 混用容易出字体/高 DPI 问题，
    而这里只需要「一排柱子 + 日期 + 金额」，QPainter 几十行够用，且完全跟随主题配色。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []          # [(label, value)]
        self.setMinimumHeight(120)
        # 空态文案：没有数据时明确说「没有」，不画一条假平的线
        self._empty_text = '暂无按天数据'

    def set_rows(self, rows, empty_text=None):
        self._rows = list(rows or [])
        if empty_text:
            self._empty_text = empty_text
        self.update()

    def paintEvent(self, event):
        try:
            self._paint()
        except Exception as exc:
            # 自绘失败不该让整个窗口崩；留痕（静默护栏要求 except 必须落 reason）
            _log.warning('柱状图绘制失败：%s', exc)

    def _paint(self):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing, True)
            w, h = self.width(), self.height()
            bg = QColor(theme_color('ui_stats_bg'))
            fg = QColor(theme_color('ui_text'))
            dim = QColor(theme_color('ui_text_dim'))
            bar = QColor(theme_color('ui_green'))

            # ⚠ 字体必须从控件自身派生，**不要**写 QFont('', 9)：
            #   实测真平台下 QFont('', 9) 会解析成 MS Sans Serif（老式英文字体），
            #   中文「峰值」等字符可能缺字形。从 self.font() 派生则跟随系统 UI 字体。
            def _f(sz):
                fnt = QFont(self.font())
                fnt.setPointSize(sz)
                return fnt

            p.fillRect(self.rect(), bg)
            p.setPen(QPen(QColor(theme_color('ui_border_soft')), 1))
            p.drawRect(0, 0, w - 1, h - 1)

            if not self._rows:
                p.setPen(dim)
                p.setFont(_f(9))
                p.drawText(self.rect(), Qt.AlignCenter, self._empty_text)
                return

            pad_l, pad_r, pad_t, pad_b = 8, 8, 14, 22
            inner_w = max(1, w - pad_l - pad_r)
            inner_h = max(1, h - pad_t - pad_b)
            vmax = max((v for _, v in self._rows), default=0) or 1.0
            n = len(self._rows)
            slot = inner_w / float(n)
            bw = max(2.0, min(28.0, slot * 0.62))

            p.setFont(_f(7))
            for i, (label, val) in enumerate(self._rows):
                bh = inner_h * (val / vmax) if vmax else 0
                x = pad_l + slot * i + (slot - bw) / 2.0
                y = pad_t + inner_h - bh
                p.fillRect(int(x), int(y), int(bw), int(max(1, bh)), bar)
                # 底部日期：只显示「日」两位，避免 30 天时挤成一团
                p.setPen(dim)
                txt = label[-2:] if len(label) >= 2 else label
                p.drawText(int(pad_l + slot * i), h - pad_b + 2, int(slot), 14,
                           Qt.AlignCenter, txt)
            # 顶部最高值
            p.setPen(fg)
            p.setFont(_f(8))
            p.drawText(pad_l, 2, inner_w, 12, Qt.AlignLeft,
                       '峰值 ¥%.4f' % vmax)
        finally:
            p.end()


class UsageStatsDialog(QDialog):
    """用量分析：按天表格 + 柱状趋势 + 用途占比

    ⚠ 只读：本窗口不写任何文件、不改任何统计值。
    """

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host
        self.setWindowTitle('📈 用量分析')
        self.resize(760, 620)
        self._build()
        self._apply_theme()
        self.reload()

    # ---------- 界面 ----------
    def _build(self):
        root = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel('范围'))
        self.cb_range = QComboBox()
        for days, label in RANGE_CHOICES:
            self.cb_range.addItem(label, days)
        self.cb_range.currentIndexChanged.connect(lambda *_: self.reload())
        top.addWidget(self.cb_range)
        top.addStretch(1)
        self.lb_note = QLabel('')
        self.lb_note.setWordWrap(True)
        top.addWidget(self.lb_note, 2)
        root.addLayout(top)

        # 汇总行：一句话说清「这段时间一共花了多少、日均多少」
        self.lb_sum = QLabel('—')
        self.lb_sum.setWordWrap(True)
        root.addWidget(self.lb_sum)

        # 按天表格
        self.tbl = QTableWidget(0, 5)
        self.tbl.setHorizontalHeaderLabels(['日期', '次数', 'token', '花费（元）', '用途'])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        root.addWidget(self.tbl, 3)

        # 柱状趋势
        root.addWidget(QLabel('按天花费趋势'))
        self.chart = _BarChart()
        root.addWidget(self.chart, 2)

        # 用途占比（今日）
        self.lb_purpose = QLabel('用途：—')
        self.lb_purpose.setWordWrap(True)
        root.addWidget(self.lb_purpose)

        # v3.5：效率与省钱（缓存 / 峰谷 / 时段）
        self.lb_cache = QLabel('缓存：—')
        self.lb_cache.setWordWrap(True)
        root.addWidget(self.lb_cache)
        self.lb_peak = QLabel('峰谷：—')
        self.lb_peak.setWordWrap(True)
        root.addWidget(self.lb_peak)
        self.lb_hour = QLabel('时段：—')
        self.lb_hour.setWordWrap(True)
        root.addWidget(self.lb_hour)

        # 按模型（终身口径）
        self.lb_model = QLabel('模型：—')
        self.lb_model.setWordWrap(True)
        root.addWidget(self.lb_model)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        btn_refresh = QPushButton('🔄 刷新')
        btn_refresh.clicked.connect(self.reload)
        bottom.addWidget(btn_refresh)
        btn_close = QPushButton('关闭')
        btn_close.clicked.connect(self.accept)
        bottom.addWidget(btn_close)
        root.addLayout(bottom)

    def _apply_theme(self):
        """颜色全部来自唯一 token 源 pet_theme.py（宿主 theme 优先）"""
        th = dict(getattr(self.host, 'theme', None) or {})
        v = {k: (th.get(k) or DEFAULT_THEME[k]) for k in DEFAULT_THEME}
        try:
            self.setStyleSheet('''
                QDialog { background: %(dialog_bg)s; }
                QLabel { color: %(text)s; }
                QTableWidget { background: %(list_bg)s; color: %(text)s;
                               gridline-color: %(item_border)s;
                               border: 1px solid %(list_border)s; border-radius: 6px; }
                QHeaderView::section { background: %(item_bg)s; color: %(text)s;
                                       border: none; padding: 4px 6px; }
                QComboBox { background: %(input_bg)s; color: %(text)s;
                            border: 1px solid %(item_border)s;
                            border-radius: 5px; padding: 3px 8px; }
                QComboBox QAbstractItemView { background: %(popup_bg)s; color: %(text)s;
                            selection-background-color: %(popup_sel_bg)s; }
                QPushButton { background: %(item_bg)s; color: %(text)s;
                              border: 1px solid %(item_border)s;
                              border-radius: 5px; padding: 5px 12px; }
                QPushButton:hover { background: %(item_hover_bg)s; border-color: %(accent)s; }
            ''' % v)
        except Exception as exc:
            # 主题键缺失不该让窗口打不开；留痕即可
            _log.warning('用量分析窗口主题化失败（用系统默认配色）：%s', exc)

    # ---------- 数据 ----------
    def _purpose_label(self, key):
        try:
            labels = getattr(self.host.api_stats, 'PURPOSE_LABELS', None) or {}
            return labels.get(key) or _PURPOSE_FALLBACK.get(key, key)
        except Exception as exc:
            _log.warning('取用途标签失败（%r），用回退表：%s', key, exc)
            return _PURPOSE_FALLBACK.get(key, key)

    def reload(self):
        """重读统计并刷新三个区块（只读，⛔ 不改任何数据）"""
        try:
            self._reload_impl()
        except Exception as exc:
            _log.warning('用量分析刷新失败：%s', exc)
            self.lb_sum.setText('刷新失败：%s' % exc)
            self.lb_note.setText('')

    def _reload_impl(self):
        st = self.host.api_stats
        days = self.cb_range.currentData()
        try:
            days = int(days or 0)
        except (TypeError, ValueError) as exc:
            _log.warning('范围值非法（%r），按全部处理：%s', days, exc)
            days = 0

        rows = st.day_breakdown() or []
        legacy = bool(getattr(st, 'day_legacy', False))

        if legacy or not rows:
            # ★ 不编数字：旧档确实没存按天数据，就明说
            self.lb_note.setText(
                '⚠ 历史未留存 —— 按天数据自 2026-10-24 起记录，更早的天数无法补回'
                '（旧版只存当日合计 + 最近 200 条明细）')
            self.tbl.setRowCount(0)
            self.chart.set_rows([], '历史未留存（从 2026-10-24 起才有按天数据）')
            self.lb_sum.setText('按天合计：暂无')
            self._fill_purpose()              # v3.4：无按天数据 -> 退回今日分项
        else:
            self.lb_note.setText('来源：api_stats.json 的 by_day（与闸门判定同一份数据）')
            sel = rows[:days] if days else rows
            self._fill_table(sel)
            self._fill_summary(sel)
            self._fill_purpose_range(sel)     # v3.4：按**所选范围**汇总用途

        self._fill_insights(sel if (rows and not legacy) else [])
        self._fill_model()

    def _fill_insights(self, rows):
        """效率与省钱三项（v3.5）：缓存命中 / 峰谷分布 / 时段分布

        Owner 2026-10-24「用量分析还有其他可以分析的吗」——
        我只加**算得出真价值**的三项，并且每条都标数据口径。

        ⚠ 数据边界（写死在这里，别改成"看起来都准"）：
        - 缓存命中率：按 **by_day 所选范围**累加 → 与表格同源，准确
        - 峰谷 / 时段：只能用 **calls（最近 200 条）** → 是**样本**不是全域
          （by_day 没有小时粒度，这是数据结构硬限制，不是偷懒）
        - 省钱金额：按当前主力模型单价估，不是逐模型精算
          （by_model 里没有 cache 字段）
        """
        try:
            self._fill_cache_insight(rows)
            self._fill_peak_insight()
        except Exception as exc:
            _log.warning('效率指标刷新失败：%s', exc)
            self.lb_cache.setText('缓存：读取失败')
            self.lb_peak.setText('峰谷：读取失败')
            self.lb_hour.setText('时段：读取失败')

    def _fill_cache_insight(self, rows):
        """缓存命中率 + 省下多少钱

        为什么值得看：缓存价 0.02 元/百万 vs 正常 input 1.0 元/百万 —— **相差 50 倍**。
        实测本机命中率 58.7% 时，省下的钱比错峰还多。
        """
        hit = miss = 0
        for item in rows or []:
            hit += int(item.get('cache_hit') or 0)
            miss += int(item.get('cache_miss') or 0)
        if not (hit or miss):
            self.lb_cache.setText('缓存：所选范围内无缓存数据（旧档未记录）')
            return
        rate = 100.0 * hit / (hit + miss) if (hit + miss) else 0.0
        saved = ''
        try:
            prices = getattr(self.host.api_stats, 'PRICES', None) or {}
            cur = getattr(self.host, 'current', 'flash')
            pr = prices.get(cur) or prices.get('deepseek-flash') or {}
            p_in = float(pr.get('input') or 0)
            p_ci = float(pr.get('cache') or 0)
            if p_in > p_ci > 0:
                # 单位：元/百万 token。命中部分本该按 input 价，实际按 cache 价
                saved = '｜省下约 ¥%.4f（缓存价 ¥%.2f vs 正常 ¥%.2f/百万）' % (
                    hit * (p_in - p_ci) / 1_000_000.0, p_ci, p_in)
        except Exception as exc:
            _log.warning('缓存省钱估算失败：%s', exc)
        # ⚠ 必须标清统计范围：缓存在 by_day（=所选天数），峰谷在 calls（最近 200 条），
        #   两者范围不同。不标的话用户会拿两个金额直接比，误以为口径一致。
        _nd = len(rows or [])
        self.lb_cache.setText('缓存：命中 %d / 未命中 %d tok ⇒ 命中率 %.1f%%%s'
                              '　〔按所选范围 %d 天〕'
                              % (hit, miss, rate, saved, _nd))

    def _fill_peak_insight(self):
        """峰谷分布 + 错峰潜在节省（只基于 calls 样本）

        为什么值得看：官方峰谷价**正好 2 倍**（input 1.0→2.0 / output 4.0→8.0）。
        高峰时段花的钱里，有一半是峰谷溢价 —— 那部分挪到空闲时段就能省下。
        """
        try:
            calls = list(getattr(self.host.api_stats, 'calls', None) or [])
        except Exception as exc:
            _log.warning('读取调用明细失败：%s', exc)
            self.lb_peak.setText('峰谷：读取失败')
            self.lb_hour.setText('时段：读取失败')
            return
        if not calls:
            self.lb_peak.setText('峰谷：暂无调用明细')
            self.lb_hour.setText('时段：暂无调用明细')
            return

        try:
            from server_clock import PEAK_HOURS
        except Exception as exc:
            _log.warning('取峰谷规则失败（按 9-12/14-18 兜底）：%s', exc)
            PEAK_HOURS = ((9, 12), (14, 18))

        def _hour(c):
            try:
                return int(str(c.get('time') or '')[11:13])
            except (TypeError, ValueError):
                return None

        def _is_peak(h):
            return h is not None and any(a <= h < b for a, b in PEAK_HOURS)

        peak_c = peak_n = off_c = off_n = 0.0
        by_hour = {}
        for c in calls:
            h = _hour(c)
            cost = float(c.get('cost') or 0)
            if h is not None:
                cur = by_hour.setdefault(h, [0, 0.0])
                cur[0] += 1
                cur[1] += cost
            if _is_peak(h):
                peak_n += 1
                peak_c += cost
            else:
                off_n += 1
                off_c += cost

        total = peak_c + off_c
        pct = 100.0 * peak_c / total if total else 0.0
        # 峰谷正好 2 倍 ⇒ 高峰花费的一半是溢价
        save = peak_c / 2.0
        span = ('%s ~ %s' % (str(calls[0].get('time') or '')[:16],
                             str(calls[-1].get('time') or '')[:16]))
        self.lb_peak.setText(
            '峰谷：高峰 %d 次 ¥%.4f（占 %.0f%%）｜空闲 %d 次 ¥%.4f'
            '　⇒ 错峰可省约 ¥%.4f'
            '　⚠ 仅统计最近 %d 条调用明细（%s），非全域'
            % (int(peak_n), peak_c, pct, int(off_n), off_c, save, len(calls), span))

        # 时段：按花费排前 3（哪几个钟点最费钱）
        try:
            top = sorted(by_hour.items(), key=lambda kv: -kv[1][1])[:3]
            parts = ['%02d 点 %d 次 ¥%.4f' % (h, int(v[0]), v[1]) for h, v in top if v[0]]
            self.lb_hour.setText('时段：花费最高 ' + ' ｜ '.join(parts) if parts
                                 else '时段：暂无')
        except Exception as exc:
            _log.warning('时段统计失败：%s', exc)
            self.lb_hour.setText('时段：统计失败')

    def _fill_table(self, rows):
        self.tbl.setRowCount(len(rows))
        for r, item in enumerate(rows):
            date = str(item.get('date') or '')
            count = int(item.get('count') or 0)
            tok = int(item.get('prompt') or 0) + int(item.get('completion') or 0)
            cost = float(item.get('cost') or 0.0)
            bp = item.get('by_purpose') or {}
            try:
                parts = ['%s ¥%.4f' % (self._purpose_label(k), float((v or {}).get('cost') or 0))
                         for k, v in sorted(bp.items(), key=lambda kv: -float((kv[1] or {}).get('cost') or 0))]
            except Exception as exc:
                _log.warning('第 %d 行用途拆解失败：%s', r, exc)
                parts = ['—']
            cells = [date, str(count), self._fmt_num(tok), '%.4f' % cost, ' ｜ '.join(parts) or '—']
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if c in (1, 2, 3):
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl.setItem(r, c, it)

    def _fill_summary(self, rows):
        try:
            total = sum(float(x.get('cost') or 0) for x in rows)
            cnt = sum(int(x.get('count') or 0) for x in rows)
            n = max(1, len(rows))
            span = '%s ~ %s' % (rows[-1].get('date'), rows[0].get('date')) if rows else '—'
            self.lb_sum.setText('共 %d 天（%s）｜调用 %d 次｜合计 ¥%.4f｜日均 ¥%.4f'
                                % (len(rows), span, cnt, total, total / n))
            self.chart.set_rows([(str(x.get('date') or ''), float(x.get('cost') or 0))
                                 for x in reversed(rows)])
        except Exception as exc:
            _log.warning('汇总计算失败：%s', exc)
            self.lb_sum.setText('汇总计算失败：%s' % exc)

    def _fill_purpose_range(self, rows):
        """按**所选范围**汇总用途（Owner 要的是「花到哪个模块」，不只是今天）

        数据全部来自 by_day 里每天的 by_purpose 累加 —— 与表格同源，
        ⛔ 不另算一套；加总不上的（旧档某天没记用途）就明说「未分类」。
        """
        agg = {}
        unknown_days = 0
        for item in rows or []:
            bp = item.get('by_purpose') or {}
            if not bp:
                unknown_days += 1
                continue
            for k, v in bp.items():
                cur = agg.setdefault(k, {'count': 0, 'cost': 0.0})
                cur['count'] += int((v or {}).get('count') or 0)
                cur['cost'] += float((v or {}).get('cost') or 0.0)
        if not agg:
            self.lb_purpose.setText('用途：所选范围内无用途分项（by_purpose 未记录）')
            return
        total = sum(v['cost'] for v in agg.values()) or 1.0
        parts = ['%s ¥%.4f（%d 次 · %.0f%%）'
                 % (self._purpose_label(k), v['cost'], v['count'], 100.0 * v['cost'] / total)
                 for k, v in sorted(agg.items(), key=lambda kv: -kv[1]['cost'])]
        tail = ('　｜　另有 %d 天未记用途' % unknown_days) if unknown_days else ''
        self.lb_purpose.setText('范围内用途：' + ' ｜ '.join(parts) + tail)

    def _fill_purpose(self):
        try:
            rows = self.host.api_stats.purpose_breakdown() or []
        except Exception as exc:
            _log.warning('用途分项读取失败：%s', exc)
            self.lb_purpose.setText('用途：读取失败')
            return
        if not rows:
            self.lb_purpose.setText('用途：今日暂无分项（旧档未记录用途维度）')
            return
        parts = ['%s ¥%.4f（%d 次 · %.0f%%）'
                 % (r.get('label') or self._purpose_label(r.get('purpose')),
                    float(r.get('cost') or 0), int(r.get('count') or 0),
                    100.0 * float(r.get('share') or 0))
                 for r in rows]
        self.lb_purpose.setText('今日用途：' + ' ｜ '.join(parts))

    def _fill_model(self):
        try:
            rows = self.host.api_stats.model_breakdown() or []
        except Exception as exc:
            _log.warning('按模型统计读取失败：%s', exc)
            self.lb_model.setText('模型：读取失败')
            return
        if not rows:
            self.lb_model.setText('模型：暂无')
            return
        parts = ['%s %d 次 ¥%.4f' % (r.get('model') or '?', int(r.get('count') or 0),
                                     float(r.get('cost') or 0))
                 for r in rows[:4]]
        more = '…' if len(rows) > 4 else ''
        # ⚠ 标「终身口径」：model_breakdown 是终身累计，**不随范围选择变化**。
        #   不标的话用户选了「近 7 天」会以为这行也是 7 天的数。
        self.lb_model.setText('累计按模型（终身，不随范围变化）：' + ' ｜ '.join(parts) + more)

    @staticmethod
    def _fmt_num(n):
        try:
            n = float(n or 0)
        except (TypeError, ValueError):
            return '0'
        if n >= 1e8:
            return '%.1f亿' % (n / 1e8)
        if n >= 1e4:
            return '%.1f万' % (n / 1e4)
        return '%d' % int(n)
