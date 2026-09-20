# -*- coding: utf-8 -*-
"""
affection_ui.py — 好感度关系面板（Phase 1：展示；动效 Phase 2）

「❤️ 关系」面板：好感度进度条 + 关系阶段 + 等级/XP + 称号 + 统计。
LiveGalGame 式可视化（变化动效 +N↑ 在 Phase 2 与余额气泡一起做）。
"""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QProgressBar, QPushButton, QScrollArea, QWidget, QFrame,
                               QGraphicsOpacityEffect, QListWidget, QListWidgetItem,
                               QLineEdit)   # v6.63：回忆相册搜索框
from PySide6.QtCore import (Qt, QPropertyAnimation, QPoint, QEasingCurve,
                            QSequentialAnimationGroup, QParallelAnimationGroup)

from affection_engine import AFFECTION_MAX, AFFECTION_INIT, xp_for_level, stage_from_affection


from pet_theme import color as T      # v6.58 主题化
import pet_theme as _pt               # v6.58 A2-2：订阅主题变化

_OPEN_DIALOGS = []                    # 已打开的关系面板/回忆相册


def memories_qss():
    """回忆相册样式（颜色取自主题 token）"""
    return ("QDialog { background:%s; }" % T('ui_bg')
            + "QLabel { color:%s; font-size:13px; }" % T('ui_text')
            + "QListWidget { background:%s; color:%s; border:1px solid %s;" % (T('ui_input_bg'), T('ui_text'), T('ui_border'))
            + " border-radius:8px; font-size:13px; }"
            + "QListWidget::item { padding:8px; border-bottom:1px solid %s; }" % T('ui_btn_alt')
            + "QListWidget::item:selected { background:%s; }" % T('ui_btn_hover'))


def relation_qss():
    """关系面板样式（颜色取自主题 token）"""
    return ("QDialog { background:%s; }" % T('ui_bg')
            + "QLabel { color:%s; font-size:13px; }" % T('ui_text')
            + "QProgressBar { border:1px solid %s; border-radius:6px; background:%s; height:16px; text-align:center; }"
              % (T('ui_border'), T('ui_input_bg'))
            + "QProgressBar::chunk { background:%s; border-radius:6px; }" % T('ui_red')
            + "QPushButton { background:%s; color:%s; border:none; border-radius:6px; padding:6px 14px; }"
              % (T('ui_btn_bg'), T('ui_text'))
            + "QPushButton:hover { background:%s; }" % T('ui_btn_hover')
            + "QFrame#card { background:%s; border-radius:10px; }" % T('ui_board_bg'))


def _apply_relation_theme(dlg):
    """重刷关系面板（含内部几个内联样式的标签）"""
    try:
        dlg.setStyleSheet(relation_qss())
        dlg.lb_title.setStyleSheet('font-size:16px; font-weight:bold; color:%s;' % T('ui_text_strong'))
        dlg.lb_stage.setStyleSheet(
            'background:%s; color:%s; border-radius:9px; padding:2px 10px; font-size:12px;'
            % (T('ui_btn_hover'), T('ui_text_strong')))
        dlg.lb_stats.setStyleSheet('color:%s; font-size:12px;' % T('ui_text_dim'))
    except Exception:
        pass


def refresh_open():
    """v6.58：主题变化时重刷已打开的面板"""
    alive = []
    for w in list(_OPEN_DIALOGS):
        try:
            if not w.isVisible():
                continue
            fn = getattr(w, 'apply_theme', None)
            if callable(fn):
                fn()
            alive.append(w)
        except RuntimeError:
            continue
        except Exception:
            continue
    _OPEN_DIALOGS[:] = alive


_pt.subscribe(refresh_open)


class MemoriesDialog(QDialog):
    """回忆相册：按时间线浏览共同经历（v6.30 Phase3）"""

    _EMOJI = {'milestone': '🏆', 'event': '✨', 'user_mark': '📌', 'memory': '🧠'}

    def __init__(self, memories, role: str, role_name: str, parent=None, searcher=None):
        super().__init__(parent)
        self.memories = memories
        self.role = role
        self.searcher = searcher          # v6.63：传进来就能搜「共同经历 / 记住的事」
        self.setWindowTitle(f'📖 回忆相册 · {role_name}')
        self.resize(380, 480)
        self.setStyleSheet(memories_qss())                  # v6.58 主题化
        self.apply_theme = lambda: self.setStyleSheet(memories_qss())
        _OPEN_DIALOGS.append(self)
        lay = QVBoxLayout(self)
        self.lb_count = QLabel('')
        lay.addWidget(self.lb_count)
        # v6.63：搜索框（本地检索，即时；清空回到完整时间线）
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText('搜「共同经历 / 记住的事」…')
        self.ed_search.setClearButtonEnabled(True)
        self.ed_search.textChanged.connect(lambda *_: self._apply_search())
        self.ed_search.setEnabled(bool(searcher))
        if not searcher:
            self.ed_search.setPlaceholderText('（本版未接入检索）')
        lay.addWidget(self.ed_search)
        self.list = QListWidget()
        lay.addWidget(self.list)
        self._refresh()

    def _apply_search(self):
        """v6.63：有关键词就走检索（事实 + 共同经历分组展示），没有就回到时间线"""
        try:
            q = self.ed_search.text().strip()
        except Exception:
            q = ''
        if not q or not self.searcher:
            self._refresh()
            return
        try:
            res = self.searcher(q) or {}
        except Exception as e:
            self.lb_count.setText('检索失败：%s' % str(e)[:60])
            self.list.clear()
            return
        facts = res.get('facts') or []
        events = res.get('events') or []
        self.lb_count.setText('🔍 「%s」命中 %d 条（事实 %d · 经历 %d）'
                              % (q, len(facts) + len(events), len(facts), len(events)))
        self.list.clear()
        for f in facts:
            text = ('🧠 ★%s %s' % (f.get('importance', 3), f.get('text', '')))
            if f.get('time'):
                text += '\n    （%s）' % f['time']
            it = QListWidgetItem(text)
            it.setToolTip(text)
            self.list.addItem(it)
        for e in events:
            aff = ('  ·  当时好感 %s' % e['affection_at']) if e.get('affection_at') is not None else ''
            text = '%s [%s]%s\n%s' % (self._EMOJI.get(e.get('type', 'event'), '✨'),
                                      e.get('time', ''), aff, e.get('title', ''))
            if e.get('detail'):
                text += '\n    %s' % e['detail']
            it = QListWidgetItem(text)
            it.setToolTip(text)
            self.list.addItem(it)
        if not facts and not events:
            it = QListWidgetItem('（没找到相关回忆，换个关键词试试）')
            self.list.addItem(it)

    def _refresh(self):
        items = self.memories.all(self.role)
        self.lb_count.setText(f'共 {len(items)} 条回忆' + ('（还没回忆，多聊聊就会有了）' if not items else ''))
        self.list.clear()
        for m in items:
            emoji = self._EMOJI.get(m.get('type', 'event'), '✨')
            time_s = m.get('time', '')
            title = m.get('title', '')
            detail = m.get('detail', '')
            aff = m.get('affection_at')
            aff_s = f'  ·  当时好感 {aff}' if aff is not None else ''
            text = f'{emoji} [{time_s}]{aff_s}\n{title}'
            if detail:
                text += f'\n    {detail}'
            item = QListWidgetItem(text)
            item.setToolTip(text)
            self.list.addItem(item)


class CostBubble(QLabel):
    """费用/好感度动画气泡：上浮渐隐（dsh-pet 余额气泡 + LiveGalGame 动效）"""

    def __init__(self, parent, text: str, color: str = None):
        super().__init__(parent)
        self.setText(text)
        color = color or T('ui_accent_soft')          # v6.58 主题化：默认色也走 token
        self.setStyleSheet(
            f'color:{color}; font-size:12px; font-weight:bold; background:{T("ui_bubble_bg")};'
            f'border:1px solid {color}; border-radius:8px; padding:2px 8px;')
        self.adjustSize()
        self._op = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._op)
        self._pos_anim = QPropertyAnimation(self, b'pos', self)
        self._op_anim = QPropertyAnimation(self._op, b'opacity', self)
        self._finished = False

    def show_bubble(self, x: int, y: int, dy: int = -46, duration: int = 1400, hold_ms: int = 0):
        """从 (x,y) 上浮 dy 并渐隐，结束后销毁自己。

        hold_ms > 0 时先原地静止 hold_ms 毫秒再开始上浮渐隐 —— 费用/好感这类数字
        一闪而来看不清（v6.61：使用者反馈「一秒钟之内就没了」）。
        """
        self.move(x, y)
        self.show()
        self.raise_()
        self._pos_anim.stop()
        self._op_anim.stop()
        self._pos_anim.setDuration(duration)
        self._pos_anim.setStartValue(QPoint(x, y))
        self._pos_anim.setEndValue(QPoint(x, y + dy))
        self._pos_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._op_anim.setDuration(duration)
        self._op_anim.setStartValue(1.0)
        self._op_anim.setEndValue(0.0)
        self._pos_anim.finished.connect(self._on_done)
        if hold_ms > 0:
            # 静止段：文字保持满不透明度，读完再上浮渐隐
            fade = QParallelAnimationGroup(self)
            fade.addAnimation(self._pos_anim)
            fade.addAnimation(self._op_anim)
            self._group = QSequentialAnimationGroup(self)
            self._group.addPause(int(hold_ms))
            self._group.addAnimation(fade)
            self._group.start()
        else:
            self._pos_anim.start()
            self._op_anim.start()

    def _on_done(self):
        if not self._finished:
            self._finished = True
            self.deleteLater()


class RelationDialog(QDialog):
    """好感度关系面板"""

    def __init__(self, engine, role: str, role_name: str, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.role = role
        self.role_name = role_name
        self.setWindowTitle(f'❤️ 关系 · {role_name}')
        self.setMinimumWidth(340)
        self.setStyleSheet(relation_qss())                  # v6.58 主题化
        self._build()
        self.refresh()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        # 角色名 + 阶段徽章
        head = QHBoxLayout()
        self.lb_title = QLabel(f'{self.role_name} · 关系')
        self.lb_title.setStyleSheet(
            'font-size:16px; font-weight:bold; color:%s;' % T('ui_text_strong'))   # v6.58 主题化
        self.lb_stage = QLabel('')
        self.lb_stage.setStyleSheet(
            'background:%s; color:%s; border-radius:9px; padding:2px 10px; font-size:12px;'
            % (T('ui_btn_hover'), T('ui_text_strong')))                          # v6.58 主题化
        head.addWidget(self.lb_title)
        head.addStretch(1)
        head.addWidget(self.lb_stage)
        lay.addLayout(head)

        # 好感度卡片
        card1 = QFrame()
        card1.setObjectName('card')
        c1 = QVBoxLayout(card1)
        c1.setContentsMargins(12, 10, 12, 10)
        self.lb_aff = QLabel('好感度')
        self.pb_aff = QProgressBar()
        self.pb_aff.setRange(0, AFFECTION_MAX)
        self.pb_aff.setValue(AFFECTION_INIT)
        self.pb_aff.setFormat('%v / %m')
        c1.addWidget(self.lb_aff)
        c1.addWidget(self.pb_aff)
        lay.addWidget(card1)

        # 等级卡片
        card2 = QFrame()
        card2.setObjectName('card')
        c2 = QVBoxLayout(card2)
        c2.setContentsMargins(12, 10, 12, 10)
        self.lb_level = QLabel('等级')
        self.pb_xp = QProgressBar()
        self.pb_xp.setFormat('')
        c2.addWidget(self.lb_level)
        c2.addWidget(self.pb_xp)
        lay.addWidget(card2)

        # 称号 + 统计
        card3 = QFrame()
        card3.setObjectName('card')
        c3 = QVBoxLayout(card3)
        c3.setContentsMargins(12, 10, 12, 10)
        self.lb_titles = QLabel('称号：无')
        self.lb_titles.setWordWrap(True)
        self.lb_stats = QLabel('')
        self.lb_stats.setStyleSheet('color:%s; font-size:12px;' % T('ui_text_dim'))   # v6.58 主题化
        c3.addWidget(self.lb_titles)
        c3.addWidget(self.lb_stats)
        lay.addWidget(card3)

        # v6.58 主题化：登记本窗口，切主题时重刷
        self.apply_theme = lambda: _apply_relation_theme(self)
        _OPEN_DIALOGS.append(self)

        # 刷新按钮
        btn_refresh = QPushButton('🔄 刷新')
        btn_refresh.clicked.connect(self.refresh)
        lay.addWidget(btn_refresh, alignment=Qt.AlignHCenter)

    # ---------- 数据刷新 ----------
    def refresh(self):
        snap = self.engine.snapshot(self.role)
        stage_name = snap['stage']
        self.lb_stage.setText(stage_name)
        self.lb_stage.setToolTip(f"关系定位：{snap['stage_role']}")

        aff = snap['affection']
        self.pb_aff.setValue(aff)
        self.lb_aff.setText(f'好感度 {aff} / {AFFECTION_MAX}')

        lv = snap['level']
        need = snap['next_level_xp']
        self.lb_level.setText(f'等级 Lv.{lv} · 距下一级还需 {need} XP')
        # 当前级内进度：已过部分 / 本级跨度
        cur_start = xp_for_level(lv)
        next_start = xp_for_level(lv + 1)
        span = max(1, next_start - cur_start)
        done = max(0, min(span, snap['xp'] - cur_start))
        self.pb_xp.setRange(0, span)
        self.pb_xp.setValue(done)
        self.pb_xp.setFormat(f'XP {snap["xp"]}')

        titles = snap['titles']
        self.lb_titles.setText('称号：' + (' / '.join(titles) if titles else '暂无'))

        st = snap['stats']
        self.lb_stats.setText(
            f'任务完成 {st.get("tasks", 0)} · 小游戏 {st.get("games", 0)} 局'
            f' · 陪伴 {st.get("companion_min", 0) // 60} 小时')
