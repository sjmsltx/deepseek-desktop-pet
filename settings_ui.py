# -*- coding: utf-8 -*-
"""
settings_ui.py — 统一设置窗口（Phase 5）
=========================================
入口：右键菜单 → ⚙️ 设置…

左侧六个分类、右侧内容区，把原先散在「⚙️ 设置」子菜单里的 40+ 项配置收拢到一处。

设计约定
--------
- **改动立即生效**：所有控件都调用宿主（PetWidget）**已有**的 setter 或
  ``_save_cfg_value``，从而沿用原有的热加载机制 —— 不新增一套暂存/提交逻辑，
  也不改动任何业务行为。因此底部只有「关闭」，没有「保存」。
- 打开窗口或任何一次改动后调 ``_refresh()`` 重读宿主状态，保证界面与实际一致。
- 只做「入口搬家」，不删功能：每个条目在设置里都能找到。
"""
import os
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

PAGES = ('通用', '对话', '外观', '模型与 API', '记忆与数据', '系统')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))   # 本模块就在桌宠项目目录下

STYLE_HINT = 'color:#7c8486;font-size:11.5px;'
STYLE_HEAD = 'font-weight:600;font-size:15px;'
TOKEN_PRESETS = [500, 1000, 2000, 4000, 16000, 32000, 64000, 128000]


class SettingsDialog(QDialog):
    """统一设置窗口。宿主 = PetWidget，借用它的 setter 与只读状态。"""

    def __init__(self, host, registry=None, parent=None):
        super().__init__(parent)
        self.host = host
        self.registry = registry     # 模型档案注册表（宿主里是模块级变量，显式传进来）
        self._building = False          # 构建/刷新期间屏蔽控件信号，避免回写
        self.setWindowTitle('⚙️ 设置')
        self.resize(800, 600)

        root = QHBoxLayout(self)
        self.nav = QListWidget()
        self.nav.setFixedWidth(166)
        for p in PAGES:
            self.nav.addItem(p)
        root.addWidget(self.nav)

        col = QVBoxLayout()
        self.stack = QStackedWidget()
        col.addWidget(self.stack, 1)
        bar = QHBoxLayout()
        bar.addStretch(1)
        self.btn_close = QPushButton('关闭')
        self.btn_close.clicked.connect(self.accept)
        bar.addWidget(self.btn_close)
        col.addLayout(bar)
        root.addLayout(col, 1)

        for fn in (self._page_general, self._page_chat, self._page_appearance,
                   self._page_model, self._page_memory, self._page_system):
            self.stack.addWidget(fn())
        self._apply_theme()
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        self._refresh()

    # ---------- 页面骨架 ----------
    def _page(self, title, hint=''):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(18, 16, 18, 16)
        head = QLabel(title)
        head.setStyleSheet(STYLE_HEAD)
        v.addWidget(head)
        if hint:
            h = QLabel(hint)
            h.setStyleSheet(STYLE_HINT)
            h.setWordWrap(True)
            v.addWidget(h)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(9)
        v.addLayout(form)
        v.addStretch(1)
        w.form = form
        return w

    def _buttons(self, form, label, pairs):
        """一行多个按钮：pairs = [(文案, 回调), ...]"""
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        for text, cb in pairs:
            b = QPushButton(text)
            b.clicked.connect(cb)
            h.addWidget(b)
        h.addStretch(1)
        form.addRow(label, box)
        return box

    # ---------- ① 通用 ----------
    def _page_general(self):
        p = self._page('通用', '界面语言、默认城市、窗口行为。')
        f = p.form
        self.cb_lang = QComboBox()
        self.cb_lang.addItem('中文', 'zh')
        self.cb_lang.addItem('English', 'en')
        self.cb_lang.currentIndexChanged.connect(
            lambda *_: not self._building and self.host._set_language(self.cb_lang.currentData()))
        f.addRow('界面语言', self.cb_lang)

        self.ed_city = QLineEdit()
        btn_city = QPushButton('应用')
        btn_city.clicked.connect(self._apply_city)
        rowc = QWidget()
        hc = QHBoxLayout(rowc)
        hc.setContentsMargins(0, 0, 0, 0)
        hc.setSpacing(8)
        hc.addWidget(self.ed_city, 1)
        hc.addWidget(btn_city)
        f.addRow('默认城市', rowc)

        self.ck_active = QCheckBox('未操作一段时间后让桌宠主动关心')
        self.ck_active.toggled.connect(self._toggle_active_chat)
        f.addRow('主动关心', self.ck_active)

        self._buttons(f, '贴边模式', [('切换「扒边 / 完全消失」', self.host.toggle_edge_mode)])
        return p

    def _apply_city(self):
        if self._building:
            return
        city = self.ed_city.text().strip()
        if city and self.host._save_cfg_value('city', city):
            self.host._append_chat('桌宠', '默认城市：%s' % city)

    def _toggle_active_chat(self, on):
        if self._building:
            return
        self.host.active_chat_enabled = bool(on)
        self.host._save_cfg_value('active_chat', bool(on))
        self.host._append_chat('桌宠', '主动关心已%s' % ('开启' if on else '关闭'))

    # ---------- ② 对话 ----------
    def _page_chat(self):
        p = self._page('对话', '性格、回复风格与回复长度。回复长度按当前角色的模型档案保存。')
        f = p.form
        self.cb_persona = QComboBox()
        for name in ('温柔', '傲娇', '吐槽', '元气', '高冷'):
            self.cb_persona.addItem(name, name)
        self.cb_persona.currentIndexChanged.connect(
            lambda *_: not self._building and self.host._set_personality(self.cb_persona.currentData()))
        f.addRow('性格', self.cb_persona)
        self._buttons(f, '', [('自定义性格…', self.host._set_personality_dialog)])

        self.cb_style = QComboBox()
        for label, val in (('极简', 'short'), ('标准', 'normal'), ('详细', 'detailed')):
            self.cb_style.addItem(label, val)
        self.cb_style.currentIndexChanged.connect(
            lambda *_: not self._building and self.host._set_reply_style(
                self.cb_style.currentData(), self.cb_style.currentText()))
        f.addRow('回复风格', self.cb_style)

        self.cb_tokens = QComboBox()
        for t in TOKEN_PRESETS:
            self.cb_tokens.addItem('%d' % t, t)
        self.cb_tokens.currentIndexChanged.connect(self._apply_tokens)
        f.addRow('回复长度', self.cb_tokens)
        self._buttons(f, '', [('自定义…', self.host._set_max_tokens_dialog)])
        return p

    def _apply_tokens(self, *_):
        if self._building:
            return
        val = self.cb_tokens.currentData()
        # 写进当前角色的模型档案（与「模型管理」一致），并热加载
        if self.host._save_profile_param('max_tokens', val):
            self.host._append_chat('桌宠', '回复长度上限：%d token' % val)

    # ---------- ③ 外观 ----------
    def _page_appearance(self):
        p = self._page('外观', '立绘显示模式与 Live2D 模型。')
        f = p.form
        self.cb_mode = QComboBox()
        self.cb_mode.addItem('静态立绘', 'static')
        self.cb_mode.addItem('Live2D 模式', 'live2d')
        self.cb_mode.currentIndexChanged.connect(
            lambda *_: not self._building and self.host._set_display_mode(self.cb_mode.currentData()))
        f.addRow('显示模式', self.cb_mode)

        self.cb_l2d = QComboBox()
        self.cb_l2d.currentIndexChanged.connect(
            lambda *_: not self._building and self.cb_l2d.currentData()
            and self.host._set_live2d_model(self.cb_l2d.currentData()))
        f.addRow('Live2D 模型', self.cb_l2d)
        self._buttons(f, '', [('打开 Live2D 调试窗口', self.host._open_live2d_preview)])
        tip = QLabel('把任意 .model3.json 模型文件夹放进 assets/live2d/，重启后即出现在上面的列表里。')
        tip.setStyleSheet(STYLE_HINT)
        tip.setWordWrap(True)
        f.addRow('', tip)
        return p

    # ---------- ④ 模型与 API ----------
    def _page_model(self):
        p = self._page('模型与 API',
                       '当前角色的模型、思考模式、采样温度与输出上限都按「模型档案」保存；'
                       '要改别的模型请进「模型管理」。')
        f = p.form
        self.cb_char = QComboBox()
        self.cb_char.currentIndexChanged.connect(
            lambda *_: not self._building and self.cb_char.currentData()
            and self.host.switch_char(self.cb_char.currentData()))
        f.addRow('当前角色', self.cb_char)

        self.lb_model = QLabel('—')
        self.lb_model.setStyleSheet('font-family:Consolas,monospace;font-size:12.5px;')
        f.addRow('实际请求模型', self.lb_model)

        self.ck_reason = QCheckBox('开启（推理模型会先输出思考过程）')
        self.ck_reason.toggled.connect(
            lambda *_: not self._building and self.host._toggle_reasoning())
        f.addRow('思考模式', self.ck_reason)

        self.sp_row = QWidget()
        hr = QHBoxLayout(self.sp_row)
        hr.setContentsMargins(0, 0, 0, 0)
        hr.setSpacing(8)
        self.cb_temp = QComboBox()
        for t in (0.3, 0.7, 1.0, 1.3):
            self.cb_temp.addItem(str(t), t)
        self.cb_temp.currentIndexChanged.connect(
            lambda *_: not self._building and self.cb_temp.currentData() is not None
            and self.host._set_temperature(self.cb_temp.currentData()))
        hr.addWidget(self.cb_temp)
        b = QPushButton('自定义…')
        b.clicked.connect(self.host._set_temperature_dialog)
        hr.addWidget(b)
        hr.addStretch(1)
        f.addRow('采样温度', self.sp_row)

        self._buttons(f, '模型档案', [('🎯 模型管理…', self.host._open_model_manager)])
        self._buttons(f, '密钥', [('🔑 修改 API Key…', self.host._set_api_key_dialog),
                                  ('🌐 修改联网搜索 Key…', self.host._set_search_key_dialog)])
        return p

    # ---------- ⑤ 记忆与数据 ----------
    def _page_memory(self):
        p = self._page('记忆与数据', '长期记忆、提醒待办与聊天记录的备份导出。带破坏性的操作都集中在这里。')
        f = p.form
        self._buttons(f, '长期记忆', [('🧠 管理窗口…', self.host._open_memory_manager),
                                      ('📋 查看记忆', self.host._show_memory),
                                      ('🗑 删除一条…', self.host._delete_memory_dialog)])
        self._buttons(f, '', [('💾 备份记忆', self.host._export_memory_backup),
                              ('📥 导入记忆', self.host._import_memory_backup)])
        self._buttons(f, '提醒与待办', [('⏰ 提醒管理', self.host._open_reminder_manager),
                                        ('📋 待办管理', self.host._open_todo_manager)])
        self._buttons(f, '聊天记录', [('📤 导出聊天记录', self.host._export_chat),
                                      ('📦 存档并清空对话', self.host._archive_and_clear)])
        tip = QLabel('「清空记忆」在记忆管理窗口里；「存档并清空对话」会先保存再清空聊天记录，不可撤销。')
        tip.setStyleSheet(STYLE_HINT)
        tip.setWordWrap(True)
        f.addRow('', tip)
        return p

    # ---------- ⑥ 系统 ----------
    def _page_system(self):
        p = self._page('系统', '开机自启与运行信息。')
        f = p.form
        self.ck_boot = QCheckBox('开机后自动启动桌宠')
        self.ck_boot.toggled.connect(
            lambda *_: not self._building and self.host.toggle_autostart())
        f.addRow('开机自启', self.ck_boot)
        self.lb_ver = QLabel('—')
        self.lb_ver.setStyleSheet('font-family:Consolas,monospace;font-size:12.5px;')
        f.addRow('程序目录', self.lb_ver)
        self._buttons(f, '窗口', [('🏠 最小化到托盘', self.host.hide_to_tray)])
        return p

    # ---------- 主题 ----------
    def _apply_theme(self):
        """跟随桌宠主题：新窗口默认吃系统调色板（浅色），这里按主题变量拼一份样式表，
        让设置窗口与聊天面板同一套观感（颜色全部取自宿主的 theme，不写死）。"""
        th = dict(getattr(self.host, 'theme', None) or {})
        fg = th.get('text', '#eee')
        acc = th.get('accent', '#7fb2ff')
        inp = th.get('input_bg', 'rgba(255,255,255,0.12)')
        self.setStyleSheet('''
            QDialog { background: #14161f; }
            QLabel { color: %s; }
            QListWidget { background: rgba(255,255,255,0.05); color: %s;
                          border: 1px solid rgba(255,255,255,0.10);
                          border-radius: 6px; padding: 6px; outline: none; }
            QListWidget::item { padding: 7px 10px; border-radius: 5px; }
            QListWidget::item:selected { background: rgba(127,178,255,0.20); color: #ffffff; }
            QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {
                background: %s; color: %s;
                border: 1px solid rgba(255,255,255,0.14);
                border-radius: 5px; padding: 4px 8px; }
            QComboBox QAbstractItemView { background: #1b1e2a; color: %s;
                selection-background-color: rgba(127,178,255,0.25); }
            QPushButton { background: rgba(255,255,255,0.08); color: %s;
                          border: 1px solid rgba(255,255,255,0.14);
                          border-radius: 5px; padding: 5px 12px; }
            QPushButton:hover { background: rgba(255,255,255,0.15); border-color: %s; }
            QCheckBox { color: %s; }
            QScrollArea { border: none; background: transparent; }
        ''' % (fg, fg, inp, fg, fg, fg, acc, fg))

    # ---------- 刷新 ----------
    def _refresh(self):
        """从宿主重读状态回填控件（屏蔽信号，避免把回填当成用户操作）"""
        h = self.host
        self._building = True
        try:
            # 通用
            idx = self.cb_lang.findData(getattr(h, 'language', 'zh'))
            self.cb_lang.setCurrentIndex(idx if idx >= 0 else 0)
            self.ed_city.setText(getattr(h, 'pet_city', '') or '')
            self.ck_active.setChecked(bool(getattr(h, 'active_chat_enabled', False)))
            # 对话
            idx = self.cb_persona.findData(getattr(h, 'personality', '温柔'))
            self.cb_persona.setCurrentIndex(idx if idx >= 0 else 0)
            idx = self.cb_style.findData(getattr(h, 'reply_style', 'normal'))
            self.cb_style.setCurrentIndex(idx if idx >= 0 else 1)
            tok = int(getattr(h, 'max_tokens', 1000) or 1000)
            idx = self.cb_tokens.findData(tok)
            self.cb_tokens.setCurrentIndex(idx if idx >= 0 else -1)
            if idx < 0:
                self.cb_tokens.setCurrentText(str(tok))   # 非预设值就直接显示
            # 外观
            idx = self.cb_mode.findData(getattr(h, 'display_mode', 'static'))
            self.cb_mode.setCurrentIndex(idx if idx >= 0 else 0)
            self.cb_l2d.clear()
            models = h._scan_live2d_models() or {}
            if models:
                for name in sorted(models):
                    self.cb_l2d.addItem(name, name)
                cur = getattr(h, 'live2d_model', '')
                i2 = self.cb_l2d.findData(cur)
                self.cb_l2d.setCurrentIndex(i2 if i2 >= 0 else 0)
            else:
                self.cb_l2d.addItem('（未找到模型）', None)
            # 模型与 API
            reg = self.registry
            self.cb_char.clear()
            if reg is not None:
                for k in reg.keys():
                    prof = reg.get(k)
                    self.cb_char.addItem('%s · %s' % (prof.display_name, prof.model_id), k)
                i3 = self.cb_char.findData(getattr(h, 'current', ''))
                self.cb_char.setCurrentIndex(i3 if i3 >= 0 else 0)
            self.lb_model.setText(getattr(h, '_current_model', lambda: '—')() or '—')
            self.ck_reason.setChecked(bool(getattr(h, 'reasoning_enabled', True)))
            t = float(getattr(h, 'temperature', 1.0) or 1.0)
            i4 = self.cb_temp.findData(t)
            self.cb_temp.setCurrentIndex(i4 if i4 >= 0 else -1)
            if i4 < 0:
                self.cb_temp.setCurrentText(str(t))
            # 系统
            try:
                self.ck_boot.setChecked(bool(h.is_autostart_enabled()))
            except Exception:
                self.ck_boot.setChecked(False)
            self.lb_ver.setText(BASE_DIR)
        finally:
            self._building = False

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh()
