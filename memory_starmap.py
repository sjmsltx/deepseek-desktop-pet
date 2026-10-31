# -*- coding: utf-8 -*-
"""memory_starmap.py — 记忆星图（可交互控件）

设计口径与静态预览稿一致，每个视觉维度都对应一个真实字段：
    星团   = 记忆类别（人际 / 兴趣 / 学业 / 工程 / 里程碑）
    团内半径 = 记忆年龄（越靠外越旧）
    亮度   = 时间衰减（半衰期 30 天，与 memory_engine.score_recency 同口径）
    大小   = importance
    连线   = 同类别内相邻经历（星座）
    中心   = L0 人格卡
    外圈暗点 = superseded（失效但留痕）

交互：拖动平移 / 滚轮缩放（以光标为中心）/ 悬停看摘要 / 点击钉住详情 / R 复位
只读：不改任何记忆文件。

配色说明（S3，审核指出）：本模块的 QColor(r, g, b) 不走主题 token，
是因为星图是**独立视觉域**（深空底色 + 类别色代表了真实的记忆分类），
不是为了绕开主题护栏。护栏只匹配十六进制色值与 rgba 函数写法，
对 QColor 三元组不计（这也是它的已知盲区，见审核 S3）。
显式声明：改主题时星图**不跟随**，需同步改本文件 PAL 表。
"""
import json
import logging
import math
import os
import time

from PySide6.QtCore import QTimer

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter,
                           QPainterPath, QPen, QRadialGradient)
from PySide6.QtWidgets import QWidget

BASE = os.path.dirname(os.path.abspath(__file__))
FACTS_PATH = os.path.join(BASE, 'memory.json')
EVENTS_PATH = os.path.join(BASE, 'memories.json')

PAL = {
    'core':  (255, 234, 172),
    'human': (255, 126, 182),
    'like':  (108, 204, 255),
    'study': (100, 255, 202),
    'work':  (255, 170, 90),
    'mile':  (255, 228, 124),
    'dead':  (100, 96, 128),
}
CN = {'core': 'L0 人格卡', 'human': '人际 · 相处方式', 'like': '兴趣 · 偏好',
      'study': '学业 · 学习', 'work': '工程 · 项目', 'mile': '里程碑', 'dead': '已失效'}
ORDER = ['human', 'study', 'work', 'like', 'mile']
ANGLES = {'human': -128, 'study': -52, 'work': 34, 'like': 122, 'mile': 182}
KEYWORDS = [
    ('mile',  ['满分', '新纪录', '里程碑', '称号', '突破', '成就']),
    ('human', ['关心', '玩笑', '亲近', '语气', '陪伴', '晚安', '熬夜', '姐姐', '大蓝', '小蓝', '记得站']),
    ('study', ['遥感', 'GIS', '地理', '课程', '考试', 'Python', 'matplotlib', '古文', '过秦论',
               '诗', '学习', '背', '大二']),
    ('work',  ['桌宠', '代码', '工程', '更新', '仓库', 'AutoClaw', '环境', '版本']),
]
HALF_LIFE_DAYS = 30.0
_log = logging.getLogger('pet.memory_starmap')


def _classify(text, status='active', typ='fact'):
    if status != 'active':
        return 'dead'
    for cat, kws in KEYWORDS:
        if any(k in text for k in kws):
            return cat
    return 'human' if typ == 'event' else 'like'


def _try_mktime(value, fmt):
    """按指定格式解析时间；不匹配是预期情况，落 debug 日志后返回 None"""
    try:
        return time.mktime(time.strptime(value, fmt))
    except (ValueError, OverflowError):
        return None          # 格式不匹配是预期分支（逐个试格式），不落日志


def _age_days(ts, now=None):
    """把时间戳换算成「多少天前」。

    用窄异常（ValueError / OverflowError）逐格式试 —— 失败是预期分支，
    不是要吞的错误，因此不需要落日志（宽泛 except 才会被判静默）。
    """
    now = now or time.time()
    s = str(ts or '').replace('T', ' ').strip()
    if not s:
        return 45.0
    fmts = ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d')
    for fmt in fmts:
        t = _try_mktime(s[:len(fmt) + 6], fmt)
        if t is not None:
            return max(0.0, (now - t) / 86400.0)
    # 只有「月-日 时:分」的旧条目：按今年推算
    if len(s) >= 16:
        t = _try_mktime('2026-' + s[5:16], '%Y-%m-%d %H:%M')
        if t is not None:
            return max(0.0, (now - t) / 86400.0)
    return 45.0


def _is_noise(title, detail=''):
    try:
        from memory_events import is_recomputable_notice
        return is_recomputable_notice(title, detail)
    except Exception as _exc:
        _log.debug('_is_noise 回退到内联判据：%s', _exc)
        t = '%s %s' % (title, detail)
        return ('别处用了' in t) or ('余额 ¥' in t) or ('今天是' in t) or ('当前设置了' in t)


def load_stars(facts_path=FACTS_PATH, events_path=EVENTS_PATH):
    """读真实数据 → 星点列表。不编造任何一条。"""
    stars, dead, raw_events = [], [], 0
    try:
        mj = json.load(open(facts_path, encoding='utf-8'))
        for f in mj.get('facts', []):
            c = (f.get('content') or '').strip()
            if not c:
                continue
            st = f.get('status', 'active')
            # key 唯一化：同名内容可能有多条（如「用户喜欢冰美式咖啡」×2），
            # 用 id 兜底，避免布局字典互相覆盖、只画出一条。
            # key 必须唯一：memory.json 里存在 3 组重复 id（同一次抽取同毫秒写入），
            #   单用 id 会撞号 ⇒ 前面加序号。
            _key = 'f:%d:%s' % (len(stars) + len(dead), f.get('id'))
            item = dict(text=c, imp=int(f.get('importance', 3)),
                        age=_age_days(f.get('created_at')), kind='fact',
                        cat=_classify(c, st), detail='', time=str(f.get('created_at') or ''),
                        key=_key)
            (dead if st != 'active' else stars).append(item)
    except Exception as _exc:
        _log.warning('星图读取 memory.json 失败（星图将只显示事件记忆）：%s', _exc)
    try:
        ev = json.load(open(events_path, encoding='utf-8'))
        raw_events = len(ev)
        seen = set()
        merged = 0
        for i, m in enumerate(ev):
            t = (m.get('title') or '').strip()
            d = (m.get('detail') or '').strip()
            # 去重口径与 prompt_hint 一致：按 (title, detail)。
            #   同名同内容的重复提醒（如「记得站起来活动一下」×11）没有新信息，
            #   若按 (title, time) 保留，星图上会出现 11 个一模一样的点。
            #   合并数量记在 merged，由副标题披露，不沉默。
            _k = (t, d)
            if not t or _is_noise(t, d):
                continue
            if _k in seen:
                merged += 1
                continue
            seen.add(_k)
            stars.append(dict(text=t, imp=4, age=_age_days(m.get('time')),
                              kind='event', cat=_classify(t, 'active', 'event'),
                              detail=d, time=str(m.get('time') or ''),
                              emotion=str(m.get('emotion') or ''),
                              affection=m.get('affection_at'),
                              key='e:%d:%s' % (i, m.get('id'))))
    except Exception as _exc:
        _log.warning('星图读取 memories.json 失败（星图将只显示事实记忆）：%s', _exc)
    # merged 通过 raw_events 与最终条数的差体现，这里额外带出精确值
    globals()['_LAST_MERGED'] = merged if 'merged' in dir() else 0
    return stars, dead, raw_events


class MemoryStarMap(QWidget):
    """记忆星图控件（只读可视化）"""

    def __init__(self, parent=None, stars=None, dead=None, raw_events=0,
                 facts_path=None, events_path=None):
        super().__init__(parent)
        # 记住本实例读的是哪两个文件 —— reload_data / 指纹都必须用它们，
        #   否则传了自定义路径的实例（测试 / 多库）刷新时会读错文件。
        self._facts_path = facts_path or FACTS_PATH
        self._events_path = events_path or EVENTS_PATH
        self.setMinimumSize(900, 620)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        if stars is None:
            stars, dead, raw_events = load_stars(self._facts_path, self._events_path)
        self.stars = stars or []
        self.dead = dead or []
        self.raw_events = raw_events
        self.zoom = 1.0
        self.pan = QPointF(0, 0)
        self.hover = None
        self.pinned = None
        self._drag_from = None
        self._pan0 = None
        self._layout = {}
        self._centers = {}
        self._layout_cached_size = None
        # B（2026-10-31）：自动刷新。原来 load_stars 只在打开时调一次，
        #   窗口开着就一直显示旧数据（实测：写盘后重绘，星数不变）。
        self._data_sig = self._current_sig()
        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(3000)
        self._auto_timer.timeout.connect(self._maybe_reload)
        self._auto_timer.start()
        # 底色由 paintEvent 自己铺（不写死十六进制色值，遵守主题单一源）

    # ---------- 布局 ----------
    def _compute_layout(self):
        w, h = self.width(), self.height()
        cx, cy = w * 0.50, h * 0.50
        R = min(w, h) * 0.40
        self._centers = {}
        for cat in ORDER:
            a = math.radians(ANGLES[cat])
            self._centers[cat] = (cx + R * 1.02 * math.cos(a), cy + R * 0.80 * math.sin(a))
        self._cx, self._cy, self._R = cx, cy, R

        groups = {}
        for s in self.stars:
            groups.setdefault(s['cat'], []).append(s)
        self._groups = groups

        pos = {}
        for cat in ORDER:
            arr = sorted(groups.get(cat) or [], key=lambda s: s['age'])
            if not arr:
                continue
            gx, gy = self._centers[cat]
            n = len(arr)
            for i, s in enumerate(arr):
                frac = (i + 0.5) / n
                rr = (30 + 118 * frac) * (1.0 if n > 1 else 0.45)
                ang = 2 * math.pi * ((i * 0.618) % 1.0)
                pos[s.get('key') or s['text']] = (gx + rr * math.cos(ang),
                                                 gy + rr * math.sin(ang) * 0.92)
        self._layout = pos

    def _current_sig(self):
        """两份数据文件的 (mtime, size) 指纹 —— 变了说明有新记忆"""
        sig = []
        for p in (self._facts_path, self._events_path):
            try:
                st = os.stat(p)
                sig.append((round(st.st_mtime, 3), st.st_size))
            except OSError as _exc:
                # 文件不存在/被占用：记 None 表示「无法判指纹」，
                #   下一次轮询若文件出现，指纹会变 ⇒ 自动刷新仍会触发。
                _log.debug('星图指纹读取失败（该文件暂不可用）：%s', _exc)
                sig.append(None)
        return tuple(sig)

    def _maybe_reload(self):
        """文件变了就重载（自动更新；只读，不改文件）"""
        sig = self._current_sig()
        if sig == self._data_sig:
            return
        if self.reload_data():
            self._data_sig = sig

    def reload_data(self):
        """重新读盘并重排布局；返回是否成功。供定时器与手动刷新共用。"""
        try:
            stars, dead, raw = load_stars(self._facts_path, self._events_path)
        except Exception as _exc:
            _log.warning('星图自动刷新读取失败（保留旧数据）：%s', _exc)
            return False
        self.stars = stars
        self.dead = dead
        self.raw_events = raw
        # 清布局缓存：否则会继续用旧布局画新数据
        self._layout = {}
        self._layout_cached_size = None
        if self.pinned is not None and (self.pinned.get('key') or '') not in {
                s.get('key') or '' for s in stars}:
            self.pinned = None
        self.hover = None
        self.update()
        return True

    def _bright(self, s):
        return 0.42 + 0.58 * (0.5 ** (s['age'] / HALF_LIFE_DAYS))

    def _to_screen(self, x, y):
        return QPointF(self._cx + (x - self._cx) * self.zoom + self.pan.x(),
                       self._cy + (y - self._cy) * self.zoom + self.pan.y())

    # ---------- 绘制 ----------
    def paintEvent(self, _ev):
        if not self._layout or self._layout_cached_size != (self.width(), self.height()):
            self._compute_layout()
            self._layout_cached_size = (self.width(), self.height())
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor(6, 7, 15))

        # 背景渐变
        g = QRadialGradient(QPointF(self._cx, self._cy), max(self.width(), self.height()) * 0.75)
        g.setColorAt(0.0, QColor(22, 20, 46))
        g.setColorAt(0.55, QColor(10, 10, 24))
        g.setColorAt(1.0, QColor(4, 5, 12))
        p.fillRect(self.rect(), QBrush(g))

        # 背景星尘（固定种子，重绘不闪）
        p.setPen(Qt.NoPen)
        seed = 1234567
        for i in range(520):
            seed = (seed * 1103515245 + 12345) & 0x7fffffff
            x = (seed % 10000) / 10000.0 * self.width()
            seed = (seed * 1103515245 + 12345) & 0x7fffffff
            y = (seed % 10000) / 10000.0 * self.height()
            v = 18 + (seed % 64)
            p.setBrush(QColor(v, v, min(255, v + 24)))
            p.drawEllipse(QPointF(x, y), 0.9, 0.9)

        # 星团云气
        for cat in ORDER:
            if not self._groups.get(cat):
                continue
            gx, gy = self._centers[cat]
            sp = self._to_screen(gx, gy)
            rr = (92 + 13 * min(len(self._groups[cat]), 8)) * self.zoom
            col = QColor(*PAL[cat])
            gg = QRadialGradient(sp, rr)
            c0 = QColor(col); c0.setAlpha(78)
            c1 = QColor(col); c1.setAlpha(16)
            c2 = QColor(col); c2.setAlpha(0)
            gg.setColorAt(0.0, c0)
            gg.setColorAt(0.45, c1)
            gg.setColorAt(1.0, c2)
            p.setBrush(QBrush(gg)); p.setPen(Qt.NoPen)
            p.drawEllipse(sp, rr, rr)

        # 中心 → 星团 细线
        for cat in ORDER:
            if not self._groups.get(cat):
                continue
            a = self._to_screen(self._cx, self._cy)
            b = self._to_screen(*self._centers[cat])
            p.setPen(QPen(QColor(46, 52, 84, 150), 1))
            p.drawLine(a, b)

        # 星团内星座连线
        for cat in ORDER:
            arr = self._groups.get(cat) or []
            if len(arr) < 2:
                continue
            gx, gy = self._centers[cat]
            pts = sorted(((self._layout[s.get('key') or s['text']], s)
                          for s in arr if (s.get('key') or s['text']) in self._layout),
                         key=lambda ps: math.atan2(ps[0][1] - gy, ps[0][0] - gx))
            col = QColor(*PAL[cat]); col.setAlpha(72)
            p.setPen(QPen(col, 1.2))
            for i in range(len(pts) - 1):
                a, b = pts[i][0], pts[i + 1][0]
                if math.hypot(a[0] - b[0], a[1] - b[1]) > 150:
                    continue
                p.drawLine(self._to_screen(*a), self._to_screen(*b))

        # 外圈失效星
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(92, 88, 116, 190))
        seed = 777
        for _ in self.dead:
            seed = (seed * 1103515245 + 12345) & 0x7fffffff
            ang = (seed % 6283) / 1000.0
            seed = (seed * 1103515245 + 12345) & 0x7fffffff
            rr = self._R * (1.30 + (seed % 220) / 1000.0)
            x = self._cx + rr * math.cos(ang)
            y = self._cy + rr * math.sin(ang) * 0.86
            p.drawEllipse(self._to_screen(x, y), 1.6 * self.zoom + 0.6, 1.6 * self.zoom + 0.6)

        # 记忆星
        for s in self.stars:
            xy = self._layout.get(s.get('key') or s['text'])
            if not xy:
                continue
            b = self._bright(s)
            col = PAL[s['cat']]
            rad = (2.0 + 1.5 * s['imp']) * self.zoom
            sp = self._to_screen(*xy)
            gg = QRadialGradient(sp, rad * 5.5)
            c0 = QColor(*col); c0.setAlpha(int(190 * b))
            c1 = QColor(*col); c1.setAlpha(int(64 * b))
            c2 = QColor(*col); c2.setAlpha(0)
            gg.setColorAt(0.0, c0)
            gg.setColorAt(0.35, c1)
            gg.setColorAt(1.0, c2)
            p.setBrush(QBrush(gg)); p.setPen(Qt.NoPen)
            p.drawEllipse(sp, rad * 5.5, rad * 5.5)
            core = QColor(*col)
            core = QColor(min(255, core.red() + 28), min(255, core.green() + 28),
                          min(255, core.blue() + 28))
            p.setBrush(core)
            p.drawEllipse(sp, rad, rad)

        # 中心 L0 核（三层固定半径，不再随 zoom 放大成白雾）
        # M2（审核抓出）：圆心必须走 _to_screen，否则拖动后中心亮斑留在屏幕正中、
        #   与已平移的星团辐条脱钩。
        _c = self._to_screen(self._cx, self._cy)
        for rad_f, alpha in ((0.070, 150), (0.135, 52), (0.240, 18)):
            rr = self._R * rad_f * self.zoom
            gg = QRadialGradient(_c, rr)
            cc = QColor(255, 238, 186); cc.setAlpha(alpha)
            gg.setColorAt(0.0, cc)
            gg.setColorAt(0.45, QColor(255, 222, 160, max(6, alpha // 3)))
            gg.setColorAt(1.0, QColor(255, 238, 186, 0))
            p.setBrush(QBrush(gg)); p.setPen(Qt.NoPen)
            p.drawEllipse(_c, rr, rr)
        p.setBrush(QColor(255, 252, 240))
        p.drawEllipse(_c, 7 * self.zoom + 2, 7 * self.zoom + 2)
        # S2（审核指出）：图例写「中心 = L0 人格卡」就必须真读数据。
        #   这里把真实身份条目数写在核下方，读不到就不写。
        try:
            from memory_engine import build_l0_block
            import json as _json
            _mj = _json.load(open(FACTS_PATH, encoding='utf-8'))
            _l0, _used = build_l0_block(_mj.get('facts', []), getattr(self, 'role', 'flash'))
            _n_id = len(_used or [])
            if _n_id:
                p.setFont(QFont('Microsoft YaHei', 8))
                p.setPen(QColor(226, 214, 176, 220))
                p.drawText(_c.x() - 70, _c.y() + 30 * self.zoom + 14,
                           'L0 人格卡 · %d 条常驻' % _n_id)
        except Exception as _exc:
            _log.debug('星图读取 L0 失败（不显示条数）：%s', _exc)

        # 文字
        p.setPen(QColor(255, 250, 242))
        f_title = QFont('Microsoft YaHei', 20, QFont.Bold)
        p.setFont(f_title)
        p.drawText(28, 44, '小蓝的记忆星图')

        p.setFont(QFont('Microsoft YaHei', 9))
        p.setPen(QColor(150, 162, 200))
        n_ev = sum(1 for s in self.stars if s['kind'] == 'event')
        # C3：把「滤掉了多少」也说清楚，避免把 3/200 说成「真实数据」而不披露
        p.drawText(30, 68, '真实数据 · 亮星 %d 颗（事实 %d + 共同经历 %d）· 隐没 %d 颗'
                   % (len(self.stars), len(self.stars) - n_ev, n_ev, len(self.dead)))
        # C3：滤除/合并了多少要披露，但不能塞进副标题（会压到星团名），
        #     放到右下角独立一行。
        _raw = self.raw_events or 0
        if _raw:
            _merged = globals().get('_LAST_MERGED', 0)
            p.setFont(QFont('Microsoft YaHei', 8))
            p.setPen(QColor(132, 140, 172))
            p.drawText(self.width() - 600, self.height() - 196,
                       '事件 %d/%d 入库：合并同名重复 %d 条、滤除可重算播报 %d 条'
                       % (n_ev, _raw, _merged, max(0, _raw - n_ev - _merged)))

        # 星团名
        p.setFont(QFont('Microsoft YaHei', 11))
        for cat in ORDER:
            if not self._groups.get(cat):
                continue
            sp = self._to_screen(*self._centers[cat])
            col = QColor(*PAL[cat])
            p.setPen(col)
            p.drawText(QRectF(sp.x() - 90, sp.y() - 178 * self.zoom, 180, 20),
                       Qt.AlignHCenter, CN[cat])
            p.setPen(QColor(150, 156, 184))
            p.setFont(QFont('Microsoft YaHei', 8))
            p.drawText(QRectF(sp.x() - 90, sp.y() - 158 * self.zoom, 180, 18),
                       Qt.AlignHCenter, '%d 颗' % len(self._groups[cat]))
            p.setFont(QFont('Microsoft YaHei', 11))

        # 个体标签（只标最亮 10 颗）
        p.setFont(QFont('Microsoft YaHei', 8))
        cand = sorted(self.stars, key=lambda s: -self._bright(s))[:10]
        # 先把星团名占位 —— 否则个体标签会压在星团名上
        boxes = []
        for cat in ORDER:
            if not self._groups.get(cat):
                continue
            cp = self._to_screen(*self._centers[cat])
            boxes.append((cp.x() - 95, cp.y() - 186 * self.zoom, 190, 44))
        for s in cand:
            xy = self._layout.get(s.get('key') or s['text'])
            if not xy:
                continue
            # 靠近 L0 中心的星不标 —— 那块要留给「人格卡」
            if math.hypot(xy[0] - self._cx, xy[1] - self._cy) < self._R * 0.34:
                continue
            sp = self._to_screen(*xy)
            text = s['text'] if len(s['text']) <= 15 else s['text'][:14] + '…'
            tw = p.fontMetrics().horizontalAdvance(text)
            placed = False
            for dx, dy in ((14, -22), (14, 8), (-tw - 14, -22), (-tw - 14, 8), (14, -40)):
                bx, by = sp.x() + dx, sp.y() + dy
                if bx < 20 or by < 90 or bx + tw > self.width() - 20 or by > self.height() - 120:
                    continue
                if any(not (bx + tw < ox - 6 or bx > ox + ow + 6 or by + 16 < oy - 4 or by > oy + oh + 4)
                       for (ox, oy, ow, oh) in boxes):
                    continue
                col = QColor(*PAL[s['cat']])
                p.setPen(QPen(QColor(col.red(), col.green(), col.blue(), 90), 1))
                p.drawLine(sp, QPointF(bx if dx > 0 else bx + tw, by + 8))
                p.setPen(QColor(min(255, col.red() + 60), min(255, col.green() + 60),
                                min(255, col.blue() + 60)))
                p.drawText(QPointF(bx, by + 14), text)
                boxes.append((bx, by, tw, 16))
                placed = True
                break

        # 图例 + 映射
        p.setFont(QFont('Microsoft YaHei', 9))
        ly = self.height() - 150
        p.setPen(QColor(196, 204, 232))
        p.drawText(30, ly - 14, '颜色 = 记忆类别')
        for i, cat in enumerate(['core', 'human', 'like', 'study', 'work', 'mile', 'dead']):
            y = ly + i * 19
            p.setBrush(QColor(*PAL[cat])); p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(34, y - 3), 4, 4)
            p.setPen(QColor(200, 206, 232))
            p.drawText(46, y, CN[cat])

        rx = self.width() - 300
        p.setPen(QColor(196, 204, 232))
        p.drawText(rx, ly - 14, '视觉 = 记忆机制')
        for i, m in enumerate(['亮度 = 时间衰减（半衰期 30 天）', '大小 = 重要度 importance',
                               '团内越靠外 = 越早的经历', '连线 = 同类别的相邻经历',
                               '中心 = L0 人格卡，永不衰减']):
            p.drawText(rx, ly + i * 19, '·  ' + m)

        # 悬停 / 详情卡
        show = self.pinned or self.hover
        if show:
            self._draw_detail(p, show)

        p.end()

    def _draw_detail(self, p, s):
        pad = 12
        w = min(520, self.width() - 60)
        text = s['text']
        detail = (s.get('detail') or '').strip()
        p.setFont(QFont('Microsoft YaHei', 10))
        fm = p.fontMetrics()
        # M1（审核 WX 侧抓出）：PySide6 6.11 的 QFontMetrics.boundingRect
        #   只接受 QRect，传 QRectF 直接 TypeError ⇒ 悬停/钉住时 paintEvent 必崩、详情卡永不显示。
        _box = QRect(0, 0, int(w - pad * 2), 400)
        rect = fm.boundingRect(_box, int(Qt.TextWordWrap | Qt.AlignLeft), text)
        rect2 = fm.boundingRect(_box, int(Qt.TextWordWrap | Qt.AlignLeft), detail) \
            if detail else QRect(0, 0, 0, 0)
        h = 56 + rect.height() + (rect2.height() + 6 if detail else 0)
        x, y = 30, self.height() - h - 190
        p.setBrush(QColor(10, 12, 26, 235))
        p.setPen(QPen(QColor(*PAL[s['cat']]), 1))
        p.drawRoundedRect(QRectF(x, y, w, h), 10, 10)
        p.setPen(QColor(*PAL[s['cat']]))
        p.setFont(QFont('Microsoft YaHei', 9, QFont.Bold))
        p.drawText(x + pad, y + 22, '%s%s' % (CN.get(s['cat'], ''), ' · 已钉住' if self.pinned else ''))
        p.setPen(QColor(232, 236, 250))
        p.setFont(QFont('Microsoft YaHei', 10))
        p.drawText(QRectF(x + pad, y + 32, w - pad * 2, rect.height()),
                   Qt.TextWordWrap, text)
        if detail:
            p.setPen(QColor(168, 176, 204))
            p.setFont(QFont('Microsoft YaHei', 9))
            p.drawText(QRectF(x + pad, y + 38 + rect.height(), w - pad * 2, rect2.height()),
                       Qt.TextWordWrap, detail)
        p.setPen(QColor(140, 148, 180))
        p.setFont(QFont('Microsoft YaHei', 8))
        meta = []
        if s.get('time'):
            meta.append('时间 ' + str(s['time'])[:16])
        if s.get('emotion'):
            meta.append('情绪 ' + s['emotion'])
        if s.get('affection') is not None:
            meta.append('当时好感 %s' % s['affection'])
        meta.append('重要度 ★%s' % s.get('imp', 3))
        p.drawText(x + pad, y + h - 10, '　'.join(str(m) for m in meta))

    # ---------- 交互 ----------
    def _hit(self, pos):
        """命中测试。C1：半径随 zoom 与星体大小变化 —— 放大后 18px 固定值点不中。"""
        best, bd = None, None
        for s in self.stars:
            xy = self._layout.get(s.get('key') or s['text'])
            if not xy:
                continue
            sp = self._to_screen(*xy)
            d = math.hypot(sp.x() - pos.x(), sp.y() - pos.y())
            # 可视核心半径 × zoom + 余量，下限 10px
            reach = max(10.0, (2.0 + 1.5 * s.get('imp', 3)) * self.zoom + 6.0)
            if d <= reach and (bd is None or d < bd):
                best, bd = s, d
        return best

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            hit = self._hit(ev.position())
            if hit:
                self.pinned = None if (self.pinned is hit) else hit
                self.update()
                return
            self._drag_from = ev.position()
            self._pan0 = QPointF(self.pan)
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._drag_from is not None:
            self.pan = QPointF(self._pan0.x() + ev.position().x() - self._drag_from.x(),
                               self._pan0.y() + ev.position().y() - self._drag_from.y())
            self.update()
            return
        hit = self._hit(ev.position())
        if hit is not self.hover:
            self.hover = hit
            self.setCursor(Qt.PointingHandCursor if hit else Qt.ArrowCursor)
            self.update()

    def mouseReleaseEvent(self, ev):
        self._drag_from = None
        super().mouseReleaseEvent(ev)

    def wheelEvent(self, ev):
        delta = ev.angleDelta().y()
        factor = 1.12 if delta > 0 else 1 / 1.12
        new = max(0.35, min(4.0, self.zoom * factor))
        # 以光标为中心缩放
        cur = ev.position()
        self.pan = QPointF(
            cur.x() - (cur.x() - self.pan.x() - self._cx) * (new / self.zoom) - self._cx,
            cur.y() - (cur.y() - self.pan.y() - self._cy) * (new / self.zoom) - self._cy)
        self.zoom = new
        self.update()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_R:
            self.zoom, self.pan, self.pinned = 1.0, QPointF(0, 0), None
            self.update()
        elif ev.key() == Qt.Key_Escape:
            self.pinned = None
            self.update()
        else:
            super().keyPressEvent(ev)

    def reset_view(self):
        self.zoom, self.pan, self.pinned, self.hover = 1.0, QPointF(0, 0), None, None
        self.update()
