# -*- coding: utf-8 -*-
"""
affection_ui.py — 好感度关系面板（Phase 1：展示；动效 Phase 2）

「❤️ 关系」面板：好感度进度条 + 关系阶段 + 等级/XP + 称号 + 统计。
LiveGalGame 式可视化（变化动效 +N↑ 在 Phase 2 与余额气泡一起做）。
"""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QProgressBar, QPushButton, QScrollArea, QWidget, QFrame,
                               QGraphicsOpacityEffect)
from PySide6.QtCore import Qt, QPropertyAnimation, QPoint, QEasingCurve

from affection_engine import AFFECTION_MAX, AFFECTION_INIT, xp_for_level, stage_from_affection


class CostBubble(QLabel):
    """费用/好感度动画气泡：上浮渐隐（dsh-pet 余额气泡 + LiveGalGame 动效）"""

    def __init__(self, parent, text: str, color: str = '#9fd0ff'):
        super().__init__(parent)
        self.setText(text)
        self.setStyleSheet(
            f'color:{color}; font-size:12px; font-weight:bold; background:rgba(20,27,44,0.75);'
            f'border:1px solid {color}; border-radius:8px; padding:2px 8px;')
        self.adjustSize()
        self._op = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._op)
        self._pos_anim = QPropertyAnimation(self, b'pos', self)
        self._op_anim = QPropertyAnimation(self._op, b'opacity', self)
        self._finished = False

    def show_bubble(self, x: int, y: int, dy: int = -46, duration: int = 1400):
        """从 (x,y) 上浮 dy 并渐隐，结束后销毁自己"""
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
        self.setStyleSheet(
            "QDialog { background:#1e2430; }"
            "QLabel { color:#dce3f0; font-size:13px; }"
            "QProgressBar { border:1px solid #3a4a66; border-radius:6px; background:#141b2c; height:16px; text-align:center; }"
            "QProgressBar::chunk { background:#e0527a; border-radius:6px; }"
            "QPushButton { background:#2a3a55; color:#dce3f0; border:none; border-radius:6px; padding:6px 14px; }"
            "QPushButton:hover { background:#35507a; }"
            "QFrame#card { background:#182136; border-radius:10px; }"
        )
        self._build()
        self.refresh()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        # 角色名 + 阶段徽章
        head = QHBoxLayout()
        self.lb_title = QLabel(f'{self.role_name} · 关系')
        self.lb_title.setStyleSheet('font-size:16px; font-weight:bold; color:#fff;')
        self.lb_stage = QLabel('')
        self.lb_stage.setStyleSheet(
            'background:#35507a; color:#fff; border-radius:9px; padding:2px 10px; font-size:12px;')
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
        self.lb_stats.setStyleSheet('color:#8aa; font-size:12px;')
        c3.addWidget(self.lb_titles)
        c3.addWidget(self.lb_stats)
        lay.addWidget(card3)

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
