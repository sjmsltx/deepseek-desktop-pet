# -*- coding: utf-8 -*-
"""记忆星图面板（3.0 主区 · 角色切换器 · 2026-11-06）

为什么需要它
------------
Owner 报：「主区只是一个 AI 的主区 …… 换了形象和 API 模型后，主区记忆没变。」

根因是**两套口径**：
  · 注入侧（`memory_engine.build_l0_block` 对 facts、`MemoryEvents.recent`
    对 events）都按角色过滤
  · 星图（`memory_starmap.load_stars`）完全不看角色，读全量
⇒ 星图上看得见的，AI 聊天时未必想得起来。

Owner 选的方案是「主区内可切换」：一个下拉框，能看当前角色、也能看全部。
比「每个形象建一套星图」好在不用改记忆写入契约，且能横向对比。

契约（panel_registry）
----------------------
· 不 import desktop_pet；只吃注入的 host（用 `.current` / `.theme`）和 roles 列表
· 提供 refresh()：容器切页 / 重开主区时调 → 跟随 host.current 换视角
· 只读：不写任何记忆文件

「全部」档为什么必须有
----------------------
实测（2026-11-06，真实数据）：
  role=None → 28 星点（21 facts + 7 events）
  flash     → 27（20 + 7）
  pro       → 20（20 + **0**）   ← 切换过去事件记忆全空
  kimi      → 19（19 + 0）
因为 `memories.json` 里 7 条事件**全部** role=flash，而注入侧对 events 是严格相等过滤。
若只给「当前角色」一档，切到 pro 时用户会以为记忆丢了 —— 所以默认给当前角色，
但始终留一个「全部角色」，并在副标题里标出「当前视角过滤掉了 N 条」。
"""
import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

import memory_starmap as sms

_log = logging.getLogger('pet.starmap_panel')


class StarmapPanel(QWidget):
    """记忆星图 + 角色切换器

    Args:
        host: 宿主，需要 `.current`（当前角色 key）与 `.theme`（颜色 token）。
        parent: 父控件。
    """

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self._host = host
        self._roles = []            # [(key, 显示名), ...]
        self._combos = []           # [(下拉项文字, role 值), ...]
        self._view = None
        self._scope_lbl = None
        self._user_picked_all = False   # 用户手动选了「全部」→ refresh 不再跟随角色
        self._n_total = None            # 全部角色的星点总数（副标题用，带缓存）
        self._build_ui()

    # ---------------- 角色清单 ----------------
    def _load_roles(self):
        """从宿主的 MODEL_REGISTRY 取角色清单；取不到就只用当前角色

        ⛔ 不硬编码 flash/pro：Owner 已加过 kimi，硬编码会在第 3 个角色时静默漏掉。
        """
        out = []
        try:
            reg = getattr(self._host, 'MODEL_REGISTRY', None)
            keys = list(reg.keys()) if reg is not None else []
            for k in keys:
                prof = reg.get(k)
                name = (getattr(prof, 'display_name', '') or '').strip() or k
                out.append((k, name))
        except Exception as exc:
            _log.warning('读取角色清单失败（只显示当前角色）：%s', exc)
        if not out:
            cur = getattr(self._host, 'current', '') or ''
            out = [(cur, cur)] if cur else []
        return out

    # ---------------- 界面 ----------------
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        bar = QHBoxLayout()
        bar.setContentsMargins(12, 8, 12, 2)
        bar.setSpacing(8)

        cap = QLabel('记忆范围')
        cap.setStyleSheet('font-size:12px;')
        bar.addWidget(cap)

        combo = QComboBox()
        combo.setMinimumWidth(180)
        combo.setStyleSheet('font-size:12px; padding:2px 6px;')
        self._roles = self._load_roles()
        cur = getattr(self._host, 'current', '') or ''
        for key, name in self._roles:
            combo.addItem('仅 %s · %s' % (key, name), key)
            self._combos.append(('仅 %s · %s' % (key, name), key))
        combo.addItem('全部角色', None)
        self._combos.append(('全部角色', None))
        # 默认：当前角色（有就选它，没有就选第一项）
        idx = next((i for i, (_t, r) in enumerate(self._combos) if r == cur), 0)
        combo.setCurrentIndex(idx)
        combo.currentIndexChanged.connect(self._on_combo)
        self._combo = combo
        bar.addWidget(combo)

        self._scope_lbl = QLabel('')
        self._scope_lbl.setStyleSheet('font-size:11px;')
        bar.addWidget(self._scope_lbl, 1)
        lay.addLayout(bar)

        role0 = combo.currentData()
        self._view = sms.MemoryStarMap(self, role=role0)
        lay.addWidget(self._view, 1)
        self._update_scope()

    def _on_combo(self, idx):
        """下拉框变了 → 换视角"""
        role = self._combo.itemData(idx)
        self._user_picked_all = (role is None)
        try:
            self._view.set_role(role)
        except Exception as exc:
            _log.warning('切换记忆视角失败（保持原视图）：%s', exc)
        self._update_scope()

    def _update_scope(self):
        """副标题：这次过滤掉了多少条（不让用户以为记忆丢了）

        ⚠ 数必须是「全部 - 当前」的真实差值。
        旧写法用 load_stars 的 _LAST_SKIPPED（只统计被过滤的 **facts**）⇒
        pro 视角实际少看到 2 facts + 7 events = 9 条，却只说「另有 2 条」，
        把事件被过滤掉的事完全藏了（实测发现，2026-11-06）。
        """
        try:
            role = self._view.role
            n_cur = len(self._view.stars)
            if role is None:
                txt = '全部角色 · %d 颗星' % n_cur
            else:
                n_all = self._total_count()
                gap = max(0, n_all - n_cur)
                if gap:
                    txt = ('仅该角色能想起来的 %d 颗 · 另有 %d 颗属于别的角色'
                           '（选「全部角色」可看）' % (n_cur, gap))
                else:
                    txt = '仅该角色能想起来的 %d 颗星' % n_cur
        except Exception as exc:
            _log.warning('更新范围提示失败：%s', exc)
            txt = ''
        self._scope_lbl.setText(txt)

    def _total_count(self, refresh=False):
        """全部角色的星点总数（带缓存；切换视角时才重算）"""
        if self._n_total is not None and not refresh:
            return self._n_total
        try:
            stars, _dead, _raw = sms.load_stars(self._view._facts_path,
                                                self._view._events_path, role=None)
            self._n_total = len(stars)
        except Exception as exc:
            _log.warning('统计全部角色星点失败（副标题可能不准）：%s', exc)
            self._n_total = 0
        return self._n_total

    # ---------------- 契约 ----------------
    def refresh(self):
        """容器切页/重开主区时调：跟随 host.current 换视角（除非用户手选了「全部」）

        这就是「换形象后主区记忆跟着变」的落点 —— 光靠星图自己的文件指纹不行，
        因为换角色时记忆文件根本没变。
        """
        cur = getattr(self._host, 'current', '') or ''
        if self._user_picked_all:
            return
        if self._view is None or self._view.role == cur:
            return
        idx = next((i for i, (_t, r) in enumerate(self._combos) if r == cur), -1)
        if idx < 0:
            # 当前角色不在下拉里（新加的角色还没刷新清单）→ 重建下拉
            self._rebuild_combo(cur)
            return
        self._combo.blockSignals(True)
        self._combo.setCurrentIndex(idx)
        self._combo.blockSignals(False)
        try:
            self._view.set_role(cur)
        except Exception as exc:
            _log.warning('跟随角色切换失败：%s', exc)
        self._update_scope()

    def _rebuild_combo(self, cur):
        """重扫角色清单并重建下拉（面板开着时新增了角色档案）"""
        try:
            self._roles = self._load_roles()
            self._combos = []
            self._combo.blockSignals(True)
            self._combo.clear()
            for key, name in self._roles:
                label = '仅 %s · %s' % (key, name)
                self._combo.addItem(label, key)
                self._combos.append((label, key))
            self._combo.addItem('全部角色', None)
            self._combos.append(('全部角色', None))
            idx = next((i for i, (_t, r) in enumerate(self._combos) if r == cur), 0)
            self._combo.setCurrentIndex(idx)
            self._combo.blockSignals(False)
            self._view.set_role(self._combo.itemData(idx))
            self._update_scope()
        except Exception as exc:
            _log.warning('重建角色下拉失败：%s', exc)
