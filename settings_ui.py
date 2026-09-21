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
import time
from PySide6.QtCore import Qt
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)
import pet_foreground as fgwin  # v6.59 前台程序感知（只读进程名，隐私边界见模块头部）
import platform_layer as pl  # v6.73 批次3：平台能力统一门面
from pet_theme import DEFAULT_THEME  # v6.57 主题 token 唯一源（消除本模块里的"第二套配色"）

PAGES = ('通用', '对话', '外观', '模型', '语音', '用量与计费', '记忆与数据', '技能', 'MCP', '系统')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))   # 本模块就在桌宠项目目录下

STYLE_HINT = 'color:%s;font-size:11.5px;' % DEFAULT_THEME['hint_text']  # v6.57 取自唯一源
STYLE_HEAD = 'font-weight:600;font-size:15px;'
TOKEN_PRESETS = [500, 1000, 2000, 4000, 16000, 32000, 64000, 128000]


def _mcp_catalog():
    """MCP 推荐清单（单一来源：mcp_bridge.CATALOG，避免两边各写一份）"""
    try:
        import mcp_bridge
        return list(mcp_bridge.CATALOG)
    except Exception:
        return []


class SettingsDialog(QDialog):
    """统一设置窗口。宿主 = PetWidget，借用它的 setter 与只读状态。"""

    def __init__(self, host, registry=None, parent=None):
        super().__init__(parent)
        self.host = host
        self.registry = registry     # 模型档案注册表（宿主里是模块级变量，显式传进来）
        self._building = False          # 构建/刷新期间屏蔽控件信号，避免回写
        self.setWindowTitle('⚙️ 设置')
        # v6.59：前台程序感知的实时状态行（让开关的效果"看得见"）
        self._fg_timer = QTimer(self)
        self._fg_timer.setInterval(1000)
        self._fg_timer.timeout.connect(self._update_fg_now)
        self._fg_timer.start()
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
                   self._page_model, self._page_voice, self._page_usage,
                   self._page_memory, self._page_skills, self._page_mcp, self._page_system):
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

        # v6.61：扒边探头 —— 与「主动关心」配套。默认关：扒边时只冒气泡，不把整个人弹出来。
        self.ck_probe = QCheckBox('开启（说关心时整个人弹出来，说完缩回）')
        self.ck_probe.toggled.connect(self._toggle_dock_probe)
        f.addRow('扒边时弹出来说', self.ck_probe)

        # v6.59：前台程序感知 —— 用户要求的「单独的、明确的勾选选项」，默认关闭。
        # 与「主动关心」平级但独立：不勾选则完全不读取前台程序。
        self.ck_fg = QCheckBox('开启（默认关闭）')
        self.ck_fg.toggled.connect(self._toggle_foreground)
        f.addRow('前台程序感知', self.ck_fg)
        self.lb_fg_note = QLabel(pl.foreground_privacy_note())
        self.lb_fg_note.setWordWrap(True)
        self.lb_fg_note.setStyleSheet(STYLE_HINT)
        f.addRow('', self.lb_fg_note)
        self.lb_fg_now = QLabel('当前检测：—（未开启）')
        self.lb_fg_now.setStyleSheet(STYLE_HINT)
        f.addRow('', self.lb_fg_now)

        # v6.53：工具梯级暴露 —— 默认只给陪伴/日常高频工具，省 ≈4K token/请求且人设更稳
        self.ck_adv = QCheckBox('放开全部工具（进阶模式）')
        self.ck_adv.toggled.connect(self._toggle_advanced_tools)
        f.addRow('工具范围', self.ck_adv)

        # v6.51：原先只有一个「切换」动作按钮——用户看不到当前是哪种模式。
        # 改成两项下拉 + _refresh 回填（与窗口内其他控件一致）
        self.cb_edge = QComboBox()
        self.cb_edge.addItem('扒边（露一点，可点开）', 'peek')
        self.cb_edge.addItem('完全消失（彻底离屏）', 'hidden')
        self.cb_edge.currentIndexChanged.connect(self._apply_edge_mode)
        f.addRow('贴边模式', self.cb_edge)
        return p

    def _toggle_foreground(self, on):
        """v6.59：前台程序感知开关（落盘与提示由宿主负责）"""
        if self._building:
            return
        self.host.set_foreground_aware(bool(on))
        self._update_fg_now()

    def _update_fg_now(self):
        """实时显示「现在检测到什么」——让使用者能当场看到这个开关的效果"""
        try:
            if not self.isVisible():
                return
            if not bool(getattr(self.host, 'foreground_aware', False)):
                self.lb_fg_now.setText('当前检测：—（未开启）')
                return
            name = pl.foreground_process() or '—'
            cat = pl.foreground_categorize(name)
            level = pl.foreground_busy_level(name)
            zh = {'high': '高度专注、建议不打扰',
                  'mid': '专注但可打断',
                  'none': '不表态，按原规则'}.get(level, '不表态')
            label = pl.foreground_label(cat) if cat and cat != 'other' else '其他'
            self.lb_fg_now.setText('当前检测：%s（%s · %s）' % (name, label, zh))
        except Exception:
            pass

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

    def _toggle_dock_probe(self, on):
        """v6.61：扒边探头开关（落盘与提示由宿主负责）"""
        if self._building:
            return
        self.host.set_dock_probe(bool(on))

    def _apply_balance_low(self):
        """v6.61：低余额提醒阈值（0 = 关闭提醒）"""
        if self._building:
            return
        self.host.set_balance_low(self.sp_bal.value())

    def _apply_cost_limit(self):
        """v6.78 · 治理增强③：日成本上限（超限暂停模型调用；0 = 不限）"""
        if self._building:
            return
        try:
            self.host._save_cfg_value('cost_limit_enabled', bool(self.ck_cost.isChecked()))
            self.host._save_cfg_value('cost_limit_daily', round(float(self.sp_cost.value()), 2))
        except Exception as e:
            self._notify('成本上限设置失败：%s' % e)

    # ---------- ② 对话 ----------
    def _toggle_advanced_tools(self, on):
        """v6.53：进阶工具模式开关（默认关 → 只放开 core 工具）"""
        if self._building:
            return
        self.host._set_advanced_tools(bool(on))

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

    # ---------- ④ 模型（v6.64：从原「模型与 API」拆出，26 行 → 三页各 ≤12 行） ----------
    def _page_model(self):
        p = self._page('模型',
                       '当前角色的模型、思考方式、采样参数与 API 细节开关。'
                       '要改别的模型/价格/接口地址请进「🎯 模型管理」。')
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

        # v6.62：思考强度（官方 reasoning_effort）—— 只有这项真正进了请求体
        self.cb_effort = QComboBox()
        for _lv, _lb in (('none', 'none · 不思考'), ('low', 'low · 快'),
                         ('high', 'high · 默认'), ('max', 'max · 最深入')):
            self.cb_effort.addItem(_lb, _lv)
        self.cb_effort.currentIndexChanged.connect(
            lambda *_: not self._building and self.cb_effort.currentData()
            and self.host._set_reasoning_effort(self.cb_effort.currentData()))
        self.cb_effort.setToolTip('思考越深 → 越慢、越费 token；选 none 等价于关闭思考')
        f.addRow('思考强度', self.cb_effort)

        self.ck_vision = QCheckBox('图片直接交给模型看（不先做文字识别）')
        self.ck_vision.toggled.connect(
            lambda *_: not self._building and self.host._toggle_vision())
        self.ck_vision.setToolTip('开启后：拖入/粘贴的图片、全屏截图按官方多模态格式直送模型，'
                                  '图表、界面布局这类非文字信息也能看懂；关闭则回退本地 OCR')
        f.addRow('图片直送', self.ck_vision)

        # v6.62：三项 API 细节开关（都是官方可选项，默认值已按官方建议设）
        self.ck_pass_rsn = QCheckBox('多轮对话回传上一轮思考内容（官方推荐，略增 token）')
        self.ck_pass_rsn.toggled.connect(
            lambda *_: not self._building and self.host._toggle_pass_reasoning())
        f.addRow('思考回传', self.ck_pass_rsn)

        self.ck_strict = QCheckBox('严格工具参数校验（请求改走 /beta，参数写错更少）')
        self.ck_strict.toggled.connect(
            lambda *_: not self._building and self.host._toggle_strict_tools())
        self.ck_strict.setToolTip('只对「所有参数都必填」的工具启用（如 write_file / search_code / '
                                  'run_powershell）；有可选参数的工具（edit_own_code 等）保持原样')
        f.addRow('严格工具', self.ck_strict)

        self.ck_vfiles = QCheckBox('图片走文件接口复用（同一张图只上传一次）')
        self.ck_vfiles.toggled.connect(
            lambda *_: not self._building and self.host._toggle_vision_files())
        self.ck_vfiles.setToolTip('官方 Files API：上传后拿 file_id 复用，同一张图反复提问不必重发 base64')
        f.addRow('图片复用', self.ck_vfiles)

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
        # v6.62：官方声明 —— 思考模式下 temperature 不生效，这里如实标出，避免误以为调了没用
        lb_tip = QLabel('提示：官方在多模态/思考开启时不支持采样温度，此项仅关闭思考后生效')
        lb_tip.setStyleSheet(STYLE_HINT)
        lb_tip.setWordWrap(True)
        f.addRow('', lb_tip)

        self._buttons(f, '模型档案', [('🎯 模型管理…', self.host._open_model_manager)])
        self._buttons(f, '密钥', [('🔑 修改 API Key…', self.host._set_api_key_dialog),
                                  ('🌐 修改联网搜索 Key…', self.host._set_search_key_dialog)])

        # v6.64：接入自己的模型 / 声音的说明（其他使用者最容易卡在这里）
        self._buttons(f, '接入说明', [('❓ 怎么填自己的模型 / 自己的声音', self.host._show_model_help)])
        return p

    # ---------- ④b 语音（v6.64 新拆分） ----------
    def _page_voice(self):
        p = self._page('语音',
                       'AI 回复可自动念出来：默认走在线神经声线（音质最好、不需 Key 且不计费，需联网），'
                       '不可用时自动降级到系统内置离线声线；也可接入你自己的模型服务。')
        f = p.form
        self.ck_voice = QCheckBox('朗读 AI 回复')
        self.ck_voice.toggled.connect(
            lambda *_: not self._building and self.host._toggle_voice())
        f.addRow('语音朗读', self.ck_voice)

        self.cb_voice_name = QComboBox()
        # 声线清单含在线神经声线（默认）与离线系统声线；值形如 'edge:zh-CN-XiaoxiaoNeural'
        for _v, _lab, _eng in getattr(self.host, '_voice_choices', lambda: ())():
            self.cb_voice_name.addItem(_lab, _v)
        self.cb_voice_name.currentIndexChanged.connect(
            lambda *_: not self._building and self.cb_voice_name.currentData()
            and self.host._set_voice_name(self.cb_voice_name.currentData()))
        self.cb_voice_name.setToolTip('在线声线音质最好（需联网，失败会自动转离线）；'
                                      '离线声线不联网但偏机械')
        f.addRow('朗读声线', self.cb_voice_name)

        # v6.76：语速控制（使用者：念得太慢了）
        self.cb_voice_rate = QComboBox()
        for _lab, _val in (('默认语速', ''), ('稍慢 -10%', '-10%'), ('慢 -20%', '-20%'),
                           ('稍快 +15%', '+15%'), ('快 +30%', '+30%'), ('很快 +50%', '+50%'),
                           ('极快 +80%', '+80%')):
            self.cb_voice_rate.addItem(_lab, _val)
        self.cb_voice_rate.currentIndexChanged.connect(
            lambda *_: not self._building and self.host._set_voice_rate(self.cb_voice_rate.currentData()))
        self.cb_voice_rate.setToolTip('在线声线用百分比调速；离线声线（系统声线）会换算成 -10..10 的档位；\n'
                                      '本地自建服务若支持 speed 字段也会一并传过去')
        f.addRow('语速', self.cb_voice_rate)

        # v6.76：朗读内容策略（使用者反馈“会直接念完整篇”）
        self.cb_voice_content = QComboBox()
        for _lab, _val in (('要点优先（长回复只念要点）', 'summary'),
                           ('全文（念完整篇）', 'full'),
                           ('只念我选中的（不自动念）', 'manual')):
            self.cb_voice_content.addItem(_lab, _val)
        self.cb_voice_content.currentIndexChanged.connect(
            lambda *_: not self._building and self.host._set_voice_content_mode(self.cb_voice_content.currentData()))
        self.cb_voice_content.setToolTip('「要点优先」：模型长回复时会额外给一句朗读摘要；没给就念“首段+末段”，\n'
                                         '跳过代码块/表格/长列表。「只念我选中的」则完全靠你在气泡里选中后右键朗读。')
        f.addRow('朗读内容', self.cb_voice_content)
        # v6.77：语音输入后端 + 插口（whisper/http）—— 共 5 个控件，
        # 为了不让语音页涨到 18 行（撞“单页 ≤14 行”护栏），收进一个子对话框
        self._buttons(f, '语音输入', [
            ('🎙 语音输入设置…', self._open_asr_dialog),
        ])
        self._buttons(f, '试听', [
            ('🔊 试听当前声线与语速', lambda: self.host._voice_test('这句用来试听当前的声线和语速，'
                                                              '如果太快或太慢，就调上面的滑条。')),
        ])

        self.ed_voice_custom = QLineEdit()
        self.ed_voice_custom.setPlaceholderText('如 edge:zh-CN-XiaoyiNeural 或 offline:Huihui')
        self.ed_voice_custom.setToolTip('填自己的语音包名字也行（需先在 Windows 里装好该语音包）：\n'
                                        '· 离线：offline:<声线名>（可用下方按钮列出系统已装声线）\n'
                                        '· 在线：edge:<微软声线名>（可用下方按钮列出，含其他语言）')
        f.addRow('自定义声线', self.ed_voice_custom)
        self._buttons(f, '声线', [
            ('✔ 应用自定义声线', lambda: self.host._voice_edit_apply(self.ed_voice_custom.text())),
            ('📃 列出系统声线', lambda: self.host._list_voices_dialog('system', self)),
            ('🌐 列出在线声线', lambda: self.host._list_voices_dialog('edge', self)),
        ])

        self.ed_voice_local = QLineEdit()
        self.ed_voice_local.setPlaceholderText('http://127.0.0.1:9880')
        self.ed_voice_local.setToolTip('本地 TTS 服务的地址；服务需提供 POST {地址}/tts（返回音频）——\n'
                                       'GPT-SoVITS 的 api_v2.py / CosyVoice / ChatTTS 都符合这个约定。\n'
                                       '填好后把声线设为 local:<这个地址> 即用它朗读')
        self.ed_voice_local.editingFinished.connect(
            lambda: not self._building and self.host._set_voice_local(url=self.ed_voice_local.text()))
        f.addRow('本地服务地址', self.ed_voice_local)

        self.ed_voice_ref = QLineEdit()
        self.ed_voice_ref.setPlaceholderText('（可选）参考音频路径，如 D:\\voice\\my.wav')
        self.ed_voice_ref.setToolTip('零样本克隆用：给 3～10 秒你的录音，很多模型不用训练就能用你的声音')
        self.ed_voice_ref.editingFinished.connect(
            lambda: not self._building and self.host._set_voice_local(ref=self.ed_voice_ref.text()))
        f.addRow('参考音频', self.ed_voice_ref)

        self.ed_voice_prompt = QLineEdit()
        self.ed_voice_prompt.setPlaceholderText('（可选）参考音频里说的话')
        self.ed_voice_prompt.editingFinished.connect(
            lambda: not self._building
            and self.host._set_voice_local(prompt=self.ed_voice_prompt.text()))
        f.addRow('参考文本', self.ed_voice_prompt)

        self.ck_voice_night = QCheckBox('夜间静音（23:00–08:00 不出声）')
        self.ck_voice_night.toggled.connect(
            lambda *_: not self._building and self.host._toggle_voice_night())
        self.ck_voice_night.setToolTip('按**本机本地时间**判断夜里（与计价用北京时间无关）')
        f.addRow('夜间静音', self.ck_voice_night)
        self._buttons(f, '语音', [('🔊 试听一句', self.host._test_voice),
                                  ('🔌 测试本地服务', self.host._test_local_tts)])
        self._buttons(f, '文档', [('❓ 怎么填自己的模型 / 自己的声音', self.host._show_model_help)])
        return p

    # ---------- ④c 用量与计费（v6.64 新拆分） ----------
    def _page_usage(self):
        p = self._page('用量与计费',
                       '余额查询、低余额提醒与峰谷计价。官方峰谷按北京时间判定，不受本机时区/时间影响。')
        f = p.form
        self.sp_bal = QDoubleSpinBox()
        self.sp_bal.setRange(0.0, 10000.0)
        self.sp_bal.setDecimals(2)
        self.sp_bal.setSingleStep(1.0)
        self.sp_bal.setSuffix(' 元')
        self.sp_bal.setSpecialValueText('关闭提醒')
        self.sp_bal.setToolTip('余额低于此值时提醒一次（每天最多一次）；设为 0 关闭提醒')
        self.sp_bal.editingFinished.connect(self._apply_balance_low)
        f.addRow('低余额提醒', self.sp_bal)
        self.ck_cost = QCheckBox('启用日成本上限（超过就暂停模型调用，防手滑烧钱）')
        self.ck_cost.toggled.connect(self._apply_cost_limit)
        f.addRow('成本上限', self.ck_cost)
        self.sp_cost = QDoubleSpinBox()
        self.sp_cost.setRange(0.0, 10000.0)
        self.sp_cost.setDecimals(2)
        self.sp_cost.setSingleStep(1.0)
        self.sp_cost.setSuffix(' 元/天')
        self.sp_cost.setSpecialValueText('不限')
        self.sp_cost.setToolTip('当日累计模型费用超过此值就不再发起请求（设为 0 = 不限）')
        self.sp_cost.editingFinished.connect(self._apply_cost_limit)
        f.addRow('', self.sp_cost)
        self._buttons(f, '余额 / 用量', [('💰 立即查询余额', lambda: self.host._query_balance_async(True)),
                                        ('📊 统计悬浮窗', self.host._toggle_api_stats_window)])

        try:
            import server_clock as _sc
            _local_peak = _sc.peak_ranges_in_local_text()
            _skew = _sc.skew_text()
        except Exception:
            _local_peak, _skew = '', ''
        _hd_tip = QLabel('高峰：北京时间 9:00–12:00 / 14:00–18:00（不含法定节假日；'
                         '周末与节假日全天按空闲）'
                         + ('；换算到你本机是 %s' % _local_peak if _local_peak else '')
                         + ('。本机时钟：%s。' % _skew if _skew else '。'))
        _hd_tip.setStyleSheet(STYLE_HINT)
        _hd_tip.setWordWrap(True)
        f.addRow('', _hd_tip)
        self._buttons(f, '峰谷计价', [('📅 更新节假日表（免费，不占搜索额度）',
                                       self.host._update_holidays_now)])
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

    # ---------- ⑧ 技能（v6.67 / Batch 3-1）----------
    def _page_skills(self):
        p = self._page('技能', '技能包 = 一个清单（plugin.json）+ 一个实现（plugin.py）。'
                              '申请了权限的包，你确认后才启用；危险操作（os.system / eval / winreg…）'
                              '写任何权限都不放行。装完即时生效，不用重启。')
        f = p.form
        self.lst_skills = QListWidget()
        self.lst_skills.setMinimumHeight(150)
        f.addRow('已装技能包', self.lst_skills)
        self._buttons(f, '操作', [
            ('🔄 刷新', self._refresh_skills),
            ('📂 从目录安装', lambda: self._skills_install(True)),
            ('🗜 从 zip 安装', lambda: self._skills_install(False)),
            ('✅ 启用 / ⛔ 禁用', self._skills_toggle),
            ('🔑 权限', self._skills_perms),
            ('🧾 审计日志', self._show_audit),
            ('🗑 卸载', self._skills_uninstall),
        ])
        self.lb_skills_msg = QLabel('')
        self.lb_skills_msg.setStyleSheet(STYLE_HINT)
        self.lb_skills_msg.setWordWrap(True)
        f.addRow('', self.lb_skills_msg)
        return p

    # ---------- 技能页动作 ----------
    def _skills_mgr(self):
        return getattr(self.host, 'plugin_mgr', None)

    def _skills_selected(self):
        it = self.lst_skills.currentItem()
        return ((it.data(Qt.UserRole) if it else '') or '')

    def _refresh_skills(self):
        m = self._skills_mgr()
        if m is None:
            self.lb_skills_msg.setText('宿主没有插件管理器（开发模式下可能未接线）')
            return
        self.lst_skills.clear()
        try:
            packs = m.packs()
        except Exception as e:
            self.lb_skills_msg.setText('读取技能包失败：%s' % e)
            return
        for pk in packs:
            it = QListWidgetItem('%s  v%s  ·  %s  ·  %s'
                                 % (pk['title'], pk['version'], pk['source'],
                                    pk.get('state') or ('启用' if pk['enabled'] else '已禁用')))
            it.setData(Qt.UserRole, pk['name'])
            lines = ['%s（%s）' % (pk['title'], pk['name']), '权限：%s' % pk['permissions_text']]
            if pk['pending']:
                lines.append('待你确认：%s' % '、'.join(pk['pending']))
            it.setToolTip('\n'.join(lines))
            self.lst_skills.addItem(it)
        for name, why in (getattr(m, 'rejected', {}) or {}).items():
            it = QListWidgetItem('⚠ %s —— 被安全策略拦下未载入：%s' % (name, why))
            it.setData(Qt.UserRole, name)
            self.lst_skills.addItem(it)
        self.lb_skills_msg.setText('共 %d 个技能包。流程：安装 → 看权限 → 确认 → 启用。'
                                   % len(packs))
        try:
            import governance as gov
            if not gov.audit_enabled():
                self.lb_skills_msg.setText(self.lb_skills_msg.text() + '（审计日志已关闭）')
            else:
                st = gov.audit_stats()
                self.lb_skills_msg.setText(self.lb_skills_msg.text() +
                                           '｜今日审计 %d 条，拒 %d 条'
                                           % (st['total'], st['denied']))
        except Exception:
            pass

    def _skills_install(self, from_dir=True):
        m = self._skills_mgr()
        if m is None:
            return
        if from_dir:
            path = QFileDialog.getExistingDirectory(self, '选技能包目录（里面要有 plugin.json）')
        else:
            path, _f = QFileDialog.getOpenFileName(self, '选技能包 zip', '', '技能包 (*.zip)')
        if not path:
            return
        _ok, msg = m.install_pack(path)
        QMessageBox.information(self, '安装技能包', msg)
        self._refresh_skills()

    def _skills_toggle(self):
        m, name = self._skills_mgr(), self._skills_selected()
        if not (m and name):
            return
        reg = {p['name']: p for p in m.packs()}.get(name)
        if not reg:
            QMessageBox.information(self, '启用/禁用', '这一个不是技能包（可能是被拦下的项）')
            return
        if reg['pending']:
            QMessageBox.information(self, '启用/禁用',
                                    '这个包还等你确认权限：%s。先点「🔑 权限」确认。'
                                    % '、'.join(reg['pending']))
            return
        _ok, msg = m.set_enabled(name, not reg['enabled'])
        QMessageBox.information(self, '启用/禁用', msg)
        self._refresh_skills()

    def _skills_perms(self):
        m, name = self._skills_mgr(), self._skills_selected()
        if not (m and name):
            return
        import skill_pack
        QMessageBox.information(self, '权限', skill_pack.permissions_card(m.dir, name) or '没有该技能包')
        reg = {p['name']: p for p in m.packs()}.get(name)
        if reg and reg['pending']:
            ans = QMessageBox.question(self, '确认权限',
                                       '确认授权这些权限吗？\n%s' % '、'.join(reg['pending']))
            if ans == QMessageBox.Yes:
                _ok, msg = m.grant(name, reg['pending'])
                QMessageBox.information(self, '结果', msg)
            self._refresh_skills()

    def _skills_uninstall(self):
        m, name = self._skills_mgr(), self._skills_selected()
        if not (m and name):
            return
        if QMessageBox.question(self, '卸载', '卸载技能包 %s？\n（会移进 plugins\\_uninstalled，可手动找回）' % name) != QMessageBox.Yes:
            return
        _ok, msg = m.uninstall(name)
        QMessageBox.information(self, '卸载', msg)
        self._refresh_skills()

    # ---------- ⑨ MCP（v6.68 / Batch 3-3）----------
    def _page_mcp(self):
        p = self._page('MCP', '接外部工具服务（MCP 是跨工具的行业标准协议，社区有几千个 server）。'
                              '写类工具默认**调用前会问你**；连接失败会在下面写明原因。')
        f = p.form
        self.lst_mcp = QListWidget()
        self.lst_mcp.setMinimumHeight(130)
        f.addRow('已配置', self.lst_mcp)
        self.ck_mcp_confirm = QCheckBox('写类工具调用前先问我（推荐开）')
        self.ck_mcp_confirm.toggled.connect(self._mcp_toggle_confirm)
        f.addRow('权限', self.ck_mcp_confirm)
        self.cb_mcp_catalog = QComboBox()
        for item in _mcp_catalog():
            self.cb_mcp_catalog.addItem('%s —— %s' % (item['title'], item['note']), item)
        f.addRow('推荐清单', self.cb_mcp_catalog)
        self._buttons(f, '操作', [
            ('🔄 刷新', self._refresh_mcp),
            ('🧩 添加推荐', self._mcp_add_catalog),
            ('➕ 加 stdio…', self._mcp_add_stdio),
            ('➕ 加 HTTP…', self._mcp_add_http),
            ('✅ 启用 / ⛔ 禁用', self._mcp_toggle),
            ('🧪 测试连接', self._mcp_test),
            ('📋 工具与权限', self._mcp_tools),
            ('🌐 出网白名单', self._open_net_dialog),
            ('🧾 审计日志', self._show_audit),
            ('🗑 删除', self._mcp_remove),
        ])
        self.lb_mcp_msg = QLabel('')
        self.lb_mcp_msg.setStyleSheet(STYLE_HINT)
        self.lb_mcp_msg.setWordWrap(True)
        f.addRow('', self.lb_mcp_msg)
        return p

    # ---------- MCP 页动作 ----------
    def _mcp(self):
        return getattr(self.host, 'mcp', None)

    def _mcp_selected(self):
        it = self.lst_mcp.currentItem()
        return ((it.data(Qt.UserRole) if it else '') or '')

    def _refresh_mcp(self):
        m = self._mcp()
        if m is None:
            self.lb_mcp_msg.setText('宿主没有 MCP 桥接器')
            return
        self.lst_mcp.clear()
        try:
            servers = m.servers()
        except Exception as e:
            self.lb_mcp_msg.setText('读取 MCP 状态失败：%s' % e)
            return
        for s in servers:
            text = '%s  ·  %s  ·  %s  ·  %d 个工具'
            it = QListWidgetItem(text % (s['title'], s['transport'], s['state'], s['tool_count']))
            it.setData(Qt.UserRole, s['name'])
            lines = [s['target'] or '（未填目标）']
            if s['error']:
                lines.append('错误：%s' % s['error'])
            if s['need_confirm']:
                lines.append('调用前会先问：%s' % '、'.join(s['need_confirm'][:6]))
            it.setToolTip('\n'.join(lines))
            self.lst_mcp.addItem(it)
        self._building = True
        try:
            self.ck_mcp_confirm.setChecked(bool(m.auto_confirm_writes()))
        finally:
            self._building = False
        if not servers:
            self.lb_mcp_msg.setText('还没配置 MCP server。可以从「推荐清单」一键添加，或自己填命令/地址。')
        else:
            conn = sum(1 for s in servers if s['state'] == '已连接')
            self.lb_mcp_msg.setText('共 %d 个，已连接 %d 个。' % (len(servers), conn))

    def _mcp_toggle_confirm(self, flag):
        if self._building:
            return
        m = self._mcp()
        if m is None:
            return
        _ok, msg = m.set_auto_confirm_writes(flag)
        self.lb_mcp_msg.setText(msg)

    def _mcp_add_catalog(self):
        m = self._mcp()
        item = self.cb_mcp_catalog.currentData()
        if m is None or not item:
            return
        args = list(item['args'])
        if any('路径' in a for a in args):
            val, ok = QInputDialog.getText(self, '填一下路径',
                                           '%s 需要你给一个本地路径（目录或文件）：' % item['title'])
            if not ok or not val.strip():
                return
            args = [val.strip() if '路径' in a else a for a in args]
        _ok, msg = m.add_server({'name': item['key'], 'title': item['title'],
                                 'command': item['command'], 'args': args})
        QMessageBox.information(self, '添加 MCP server', msg)
        self._refresh_mcp()

    def _mcp_add_stdio(self):
        m = self._mcp()
        if m is None:
            return
        name, ok = QInputDialog.getText(self, '加 stdio MCP', '名字（字母/数字）：')
        if not ok or not name.strip():
            return
        cmd, ok = QInputDialog.getText(self, '加 stdio MCP',
                                       '命令（如 npx 或 uvx，也可写完整路径）：', text='npx')
        if not ok or not cmd.strip():
            return
        args, ok = QInputDialog.getText(self, '加 stdio MCP',
                                        '参数（空格分隔，可留空）：',
                                        text='-y @modelcontextprotocol/server-filesystem')
        if not ok:
            return
        _ok, msg = m.add_server({'name': name.strip(), 'command': cmd.strip(),
                                 'args': [a for a in args.split() if a]})
        QMessageBox.information(self, '添加 MCP server', msg)
        self._refresh_mcp()

    def _mcp_add_http(self):
        m = self._mcp()
        if m is None:
            return
        name, ok = QInputDialog.getText(self, '加 HTTP MCP', '名字：')
        if not ok or not name.strip():
            return
        url, ok = QInputDialog.getText(self, '加 HTTP MCP', '服务地址（http(s)://…/mcp）：')
        if not ok or not url.strip():
            return
        _ok, msg = m.add_server({'name': name.strip(), 'url': url.strip()})
        QMessageBox.information(self, '添加 MCP server', msg)
        self._refresh_mcp()

    def _mcp_toggle(self):
        m, name = self._mcp(), self._mcp_selected()
        if not (m and name):
            return
        cur = next((s for s in m.servers() if s['name'] == name), None)
        if not cur:
            return
        _ok, msg = m.set_enabled(name, not cur['enabled'])
        QMessageBox.information(self, 'MCP', msg)
        self._refresh_mcp()

    def _mcp_test(self):
        m, name = self._mcp(), self._mcp_selected()
        if not (m and name):
            return
        _ok, msg = m.restart(name)
        QMessageBox.information(self, 'MCP', msg + '\n（连接结果 1～2 秒后反映在列表里，点刷新看）')
        QTimer.singleShot(2500, self._refresh_mcp)

    def _mcp_tools(self):
        m, name = self._mcp(), self._mcp_selected()
        if not (m and name):
            return
        cur = next((s for s in m.servers() if s['name'] == name), None)
        if not cur:
            return
        lines = ['%s（%s）状态：%s' % (cur['title'], cur['transport'], cur['state']), cur['target']]
        if cur['error']:
            lines.append('错误：%s' % cur['error'])
        if not cur['tools']:
            lines.append('（没拿到工具 —— 没连上或该 server 没暴露工具）')
        for t in cur['tools']:
            lines.append('· %s%s —— %s'
                         % ('（只读）' if t['read_only'] else '（调用前会问）', t['name'],
                            (t['description'] or '')[:40]))
        QMessageBox.information(self, 'MCP 工具与权限', '\n'.join(lines)[:1800])

    def _mcp_remove(self):
        m, name = self._mcp(), self._mcp_selected()
        if not (m and name):
            return
        if QMessageBox.question(self, '删除', '删除 MCP server %s？（只删配置，不动你电脑上的东西）' % name) != QMessageBox.Yes:
            return
        _ok, msg = m.remove_server(name)
        QMessageBox.information(self, 'MCP', msg)
        self._refresh_mcp()

    def _show_audit(self):
        """审计日志窗口（v6.78）：今日统计 + 对象/类型筛选 + 只看被拒 + 导出 + 清空当日"""
        try:
            import governance as gov
            if not gov.audit_enabled():
                QMessageBox.information(self, '审计日志',
                                        '审计日志当前是关闭的（config.json 的 audit_log = false）。')
                return
        except Exception as e:
            QMessageBox.information(self, '审计日志', '治理模块不可用：%s' % e)
            return
        _AuditDialog(self).exec()

    def _open_net_dialog(self):
        """出网白名单可视化（v6.78）：增删规则 + 试算"""
        _NetDialog(self.host, self).exec()

    def _open_asr_dialog(self):
        """语音输入设置对话框（v6.77）：后端 + whisper 路径 + 联网接口"""
        dlg = _AsrDialog(self.host, self)
        self._asr_sub = dlg
        try:
            dlg.exec()
        finally:
            self._asr_sub = None

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
        # ---- 平台能力（只读诊断块，v6.74 批次5：直接渲染 platform_layer.report()）----
        box = QWidget()
        vb = QVBoxLayout(box)
        vb.setContentsMargins(0, 0, 0, 0)
        vb.setSpacing(4)
        self.lb_platform = QLabel('—')
        self.lb_platform.setStyleSheet('font-family:Consolas,monospace;font-size:12.5px;')
        self.lb_platform.setWordWrap(True)
        self.lb_platform.setTextInteractionFlags(Qt.TextSelectableByMouse)
        vb.addWidget(self.lb_platform)
        row = QWidget()
        hb = QHBoxLayout(row)
        hb.setContentsMargins(0, 0, 0, 0)
        hb.setSpacing(8)
        bt = QPushButton('🔄 重新检测')
        bt.clicked.connect(lambda *_: self._refresh_platform())
        hb.addWidget(bt)
        hb.addStretch(1)
        vb.addWidget(row)
        f.addRow('平台能力', box)
        return p

    def _refresh_platform(self):
        """只读平台能力报告（platform_layer 的 13 项能力：经谁实现 / 是否可用）"""
        try:
            self.lb_platform.setText(pl.report())
        except Exception as e:
            self.lb_platform.setText('能力检测失败：%s' % e)

    # ---------- 主题 ----------
    def _apply_theme(self):
        """跟随桌宠主题：颜色**全部**来自唯一 token 源 pet_theme.py（v6.57）。

        宿主 theme 里的同名键（含 theme 插件覆盖）优先，其余取默认值；取值与原硬编码
        颜色逐项等价，因此默认主题下渲染结果不变。"""
        th = dict(getattr(self.host, 'theme', None) or {})
        v = {k: (th.get(k) or DEFAULT_THEME[k]) for k in DEFAULT_THEME}
        self.setStyleSheet('''
            QDialog { background: %(dialog_bg)s; }
            QLabel { color: %(text)s; }
            QListWidget { background: %(list_bg)s; color: %(text)s;
                          border: 1px solid %(list_border)s;
                          border-radius: 6px; padding: 6px; outline: none; }
            QListWidget::item { padding: 7px 10px; border-radius: 5px; }
            QListWidget::item:selected { background: %(list_sel_bg)s; color: %(list_sel_text)s; }
            QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {
                background: %(input_bg)s; color: %(text)s;
                border: 1px solid %(item_border)s;
                border-radius: 5px; padding: 4px 8px; }
            QComboBox QAbstractItemView { background: %(popup_bg)s; color: %(text)s;
                selection-background-color: %(popup_sel_bg)s; }
            QPushButton { background: %(item_bg)s; color: %(text)s;
                          border: 1px solid %(item_border)s;
                          border-radius: 5px; padding: 5px 12px; }
            QPushButton:hover { background: %(item_hover_bg)s; border-color: %(accent)s; }
            QCheckBox { color: %(text)s; }
            QScrollArea { border: none; background: transparent; }
        ''' % v)

    def _apply_edge_mode(self, *_):
        """切换贴边模式（v6.51：下拉入口；_building 期间的回填不触发）"""
        if getattr(self, '_building', False):
            return
        want = self.cb_edge.currentData()
        h = self.host
        if getattr(h, '_edge_mode', 'peek') == want:
            return
        try:
            h.toggle_edge_mode()      # 宿主只提供 toggle，所以先在"不同"时才调用
        except Exception:
            pass

    # ---------- 刷新 ----------
    def _refresh(self):
        """从宿主重读状态回填控件（屏蔽信号，避免把回填当成用户操作）"""
        if hasattr(self, "lb_platform"):
            self._refresh_platform()
        h = self.host
        self._building = True
        try:
            # 通用
            idx = self.cb_lang.findData(getattr(h, 'language', 'zh'))
            self.cb_lang.setCurrentIndex(idx if idx >= 0 else 0)
            self.ed_city.setText(getattr(h, 'pet_city', '') or '')
            self.ck_active.setChecked(bool(getattr(h, 'active_chat_enabled', False)))
            self.ck_probe.setChecked(bool(getattr(h, 'dock_probe', False)))
            try:
                self.sp_bal.setValue(float(getattr(h, 'balance_low_threshold', 5.0) or 0))
            except Exception:
                self.sp_bal.setValue(5.0)
            try:
                import governance as _gov_r
                self.ck_cost.setChecked(bool(_gov_r.cost_limit_enabled()))
                self.sp_cost.setValue(float(_gov_r.cost_limit_daily() or 0))
            except Exception:
                pass
            self.ck_adv.setChecked(bool(getattr(h, 'advanced_tools', False)))
            self.ck_fg.setChecked(bool(getattr(h, 'foreground_aware', False)))
            self._update_fg_now()
            # 对话
            idx = self.cb_persona.findData(getattr(h, 'personality', '温柔'))
            self.cb_persona.setCurrentIndex(idx if idx >= 0 else 0)
            idx = self.cb_style.findData(getattr(h, 'reply_style', 'normal'))
            self.cb_style.setCurrentIndex(idx if idx >= 0 else 1)
            # v6.51：非预设值原先走 setCurrentText —— 对不可编辑的 QComboBox 无效，
            # 下拉会显示空白，用户看不到当前真实值。改为临时插一项再选中。
            for _i in range(self.cb_tokens.count() - 1, -1, -1):
                if self.cb_tokens.itemText(_i).endswith('（当前）'):
                    self.cb_tokens.removeItem(_i)
            tok = int(getattr(h, 'max_tokens', 1000) or 1000)
            idx = self.cb_tokens.findData(tok)
            if idx < 0:
                self.cb_tokens.addItem('%d（当前）' % tok, tok)
                idx = self.cb_tokens.findData(tok)
            self.cb_tokens.setCurrentIndex(idx if idx >= 0 else 0)
            # 外观
            idx = self.cb_mode.findData(getattr(h, 'display_mode', 'static'))
            self.cb_mode.setCurrentIndex(idx if idx >= 0 else 0)
            idx = self.cb_edge.findData(getattr(h, '_edge_mode', 'peek'))
            self.cb_edge.setCurrentIndex(idx if idx >= 0 else 0)
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
            # v6.62：思考强度与图片直送
            _e = str(getattr(h, 'reasoning_effort', 'high') or 'high')
            _ie = self.cb_effort.findData(_e)
            self.cb_effort.setCurrentIndex(_ie if _ie >= 0 else 2)   # 认不出回默认 high
            self.ck_vision.setChecked(bool(getattr(h, 'vision_enabled', False)))
            # v6.62：三项 API 细节开关
            self.ck_pass_rsn.setChecked(bool(getattr(h, 'pass_reasoning_history', True)))
            self.ck_strict.setChecked(bool(getattr(h, 'strict_tools', False)))
            self.ck_vfiles.setChecked(bool(getattr(h, 'vision_files_api', False)))
            # v6.63/6.64：语音朗读
            self.ck_voice.setChecked(bool(getattr(h, 'voice_enabled', False)))
            from voice_io import DEFAULT_VOICE, parse_voice_spec
            _spec = str(getattr(h, 'voice_name', '') or '') or DEFAULT_VOICE
            _eng, _vn = parse_voice_spec(_spec)
            _i = self.cb_voice_name.findData('%s:%s' % (_eng, _vn))
            self.cb_voice_name.setCurrentIndex(_i if _i >= 0 else 0)
            self.ck_voice_night.setChecked(bool(getattr(h, 'voice_night_quiet', True)))
            # v6.76：语速回填
            from voice_io import normalize_rate as _nr
            _rv = _nr(getattr(h, 'voice_rate', '') or '')
            _ri = self.cb_voice_rate.findData(_rv)
            self.cb_voice_rate.setCurrentIndex(_ri if _ri >= 0 else 0)
            # v6.76：朗读内容回填
            _cm = str(getattr(h, 'voice_content_mode', 'summary') or 'summary')
            _ci = self.cb_voice_content.findData(_cm)
            self.cb_voice_content.setCurrentIndex(_ci if _ci >= 0 else 0)
            # v6.77：语音输入后端与插口回填
            # v6.77：语音输入后端在子对话框里 —— 开着就刷一下它的值
            if getattr(self, '_asr_sub', None) is not None:
                try:
                    self._asr_sub.reload()
                except Exception:
                    pass
            self.ed_voice_local.setText(str(getattr(h, 'voice_local_url', '') or ''))
            self.ed_voice_ref.setText(str(getattr(h, 'voice_local_ref', '') or ''))
            self.ed_voice_prompt.setText(str(getattr(h, 'voice_local_prompt', '') or ''))
            # v6.51：同「回复长度」——温度非预设值时也要能看见当前值
            for _i in range(self.cb_temp.count() - 1, -1, -1):
                if self.cb_temp.itemText(_i).endswith('（当前）'):
                    self.cb_temp.removeItem(_i)
            t = float(getattr(h, 'temperature', 1.0) or 1.0)
            i4 = self.cb_temp.findData(t)
            if i4 < 0:
                self.cb_temp.addItem('%s（当前）' % t, t)
                i4 = self.cb_temp.findData(t)
            self.cb_temp.setCurrentIndex(i4 if i4 >= 0 else 0)
            # 系统
            try:
                self.ck_boot.setChecked(bool(h.is_autostart_enabled()))
            except Exception:
                self.ck_boot.setChecked(False)
            self.lb_ver.setText(BASE_DIR)
            # 技能（v6.67）/ MCP（v6.68）
            self._refresh_skills()
            self._refresh_mcp()
        finally:
            self._building = False

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh()


class _AsrDialog(QDialog):
    """语音输入后端设置（v6.77）—— 从语音页拆出来，避免该页行数超限

    · auto：系统（WinRT→SAPI）
    · winh：闱起系统 Win+H（质量好、零依赖，结果由系统直接打进输入框）
    · whisper：本地 whisper.cpp（插口，需配 exe 与模型）
    · http：联网 ASR 接口（插口，需配 URL/Key）
    """

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host
        self._building = True
        self.setWindowTitle('🎙 语音输入设置')
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)
        f = QFormLayout()
        v.addLayout(f)
        self.form = f

        self.cb_backend = QComboBox()
        for lab, val in (('系统（WinRT→SAPI，默认）', 'auto'),
                         ('系统 Win+H 应急（质量好、零依赖）', 'winh'),
                         ('本地 whisper.cpp（需配路径）', 'whisper'),
                         ('联网 ASR 接口（需配 URL）', 'http')):
            self.cb_backend.addItem(lab, val)
        self.cb_backend.currentIndexChanged.connect(
            lambda *_: not self._building and host._set_asr_backend(self.cb_backend.currentData()))
        f.addRow('识别后端', self.cb_backend)

        self.ed_exe = QLineEdit()
        self.ed_exe.setPlaceholderText('whisper.cpp 的 main.exe 路径')
        self.ed_exe.editingFinished.connect(
            lambda: not self._building and host._set_asr_extra(whisper_exe=self.ed_exe.text()))
        f.addRow('whisper 程序', self.ed_exe)

        self.ed_model = QLineEdit()
        self.ed_model.setPlaceholderText('模型文件，如 D:\\models\\ggml-small.bin')
        self.ed_model.editingFinished.connect(
            lambda: not self._building and host._set_asr_extra(whisper_model=self.ed_model.text()))
        f.addRow('whisper 模型', self.ed_model)

        self.ed_url = QLineEdit()
        self.ed_url.setPlaceholderText('https://你的接口/asr（POST JSON: audio_b64 + lang）')
        self.ed_url.editingFinished.connect(
            lambda: not self._building and host._set_asr_extra(asr_http_url=self.ed_url.text()))
        f.addRow('ASR 接口', self.ed_url)

        self.ed_key = QLineEdit()
        self.ed_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_key.setPlaceholderText('（可选）接口 Key，只存本地')
        self.ed_key.editingFinished.connect(
            lambda: not self._building and host._set_asr_extra(asr_http_key=self.ed_key.text()))
        f.addRow('ASR Key', self.ed_key)

        self.ed_hotkey = QLineEdit()
        self.ed_hotkey.setPlaceholderText('win+h（默认）')
        self.ed_hotkey.setToolTip('唤起系统语音输入的热键。Win10/11 上系统固定就是 Win+H；\n'
                                  '若被其他软件抢占/旧系统不支持，可改成 win+alt+h 或 ctrl+shift+space 等。\n'
                                  '填完点一下别处即可生效。')
        self.ed_hotkey.editingFinished.connect(
            lambda: not self._building and host._set_asr_extra(winh_hotkey=self.ed_hotkey.text()))
        f.addRow('Win+H 热键', self.ed_hotkey)

        tip = QLabel('系统那套（WinRT/SAPI）中文质量一般；Win+H 会把识别结果直接打进输入框；\n'
                     'whisper / 联网接口需自己填路径或地址，填完在设置里选对应后端即生效。')
        tip.setStyleSheet(STYLE_HINT)
        tip.setWordWrap(True)
        v.addWidget(tip)

        bar = QHBoxLayout()
        bar.addStretch(1)
        btn = QPushButton('关闭')
        btn.clicked.connect(self.accept)
        bar.addWidget(btn)
        v.addLayout(bar)
        self.reload()
        self._building = False

    def reload(self):
        h = self.host
        self._building = True
        try:
            i = self.cb_backend.findData(str(getattr(h, 'asr_backend', 'auto') or 'auto'))
            self.cb_backend.setCurrentIndex(i if i >= 0 else 0)
            self.ed_exe.setText(str(getattr(h, 'asr_whisper_exe', '') or ''))
            self.ed_model.setText(str(getattr(h, 'asr_whisper_model', '') or ''))
            self.ed_url.setText(str(getattr(h, 'asr_http_url', '') or ''))
            self.ed_key.setText(str(getattr(h, 'asr_http_key', '') or ''))
            self.ed_hotkey.setText(str(getattr(h, 'asr_winh_hotkey', 'win+h') or 'win+h'))
        finally:
            self._building = False


class _AuditDialog(QDialog):
    """审计查看窗口（v6.78 · 治理增强①）—— **只读**

    入口：设置 → 技能页 / MCP 页的「🧾 审计日志」
    能力：今日统计 + 对象/类型筛选 + 只看被拒 + 刷新 + 导出 CSV + 清空当日（二次确认，先备份）
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        import governance as gov
        self.gov = gov
        self.setWindowTitle('🧾 审计日志')
        self.resize(900, 540)
        v = QVBoxLayout(self)

        self.lb_stat = QLabel('')
        self.lb_stat.setStyleSheet(STYLE_HEAD)
        v.addWidget(self.lb_stat)

        bar = QHBoxLayout()
        bar.addWidget(QLabel('对象'))
        self.cb_actor = QComboBox()
        self.cb_actor.setMinimumWidth(160)
        self.cb_actor.currentIndexChanged.connect(lambda *_: self.reload())
        bar.addWidget(self.cb_actor)
        bar.addWidget(QLabel('类型'))
        self.cb_kind = QComboBox()
        self.cb_kind.setMinimumWidth(110)
        self.cb_kind.currentIndexChanged.connect(lambda *_: self.reload())
        bar.addWidget(self.cb_kind)
        self.ck_denied = QCheckBox('只看被拒')
        self.ck_denied.toggled.connect(lambda *_: self.reload())
        bar.addWidget(self.ck_denied)
        bar.addStretch(1)
        _b = QPushButton('🔄 刷新')
        _b.clicked.connect(self.reload)
        bar.addWidget(_b)
        v.addLayout(bar)

        self.tb = QTableWidget(0, 5)
        self.tb.setHorizontalHeaderLabels(['时间', '类型', '对象', '动作', '结果 / 详情'])
        self.tb.verticalHeader().setVisible(False)
        self.tb.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tb.setSelectionBehavior(QTableWidget.SelectRows)
        self.tb.setColumnWidth(0, 90)
        self.tb.setColumnWidth(1, 70)
        self.tb.setColumnWidth(2, 130)
        self.tb.setColumnWidth(3, 140)
        self.tb.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.tb)

        self.lb_hint = QLabel('')
        self.lb_hint.setStyleSheet(STYLE_HINT)
        self.lb_hint.setWordWrap(True)
        v.addWidget(self.lb_hint)

        foot = QHBoxLayout()
        self.lb_path = QLabel('')
        self.lb_path.setStyleSheet(STYLE_HINT)
        foot.addWidget(self.lb_path)
        foot.addStretch(1)
        _b2 = QPushButton('📤 导出 CSV')
        _b2.clicked.connect(self._export)
        foot.addWidget(_b2)
        _b3 = QPushButton('🗑 清空当日')
        _b3.clicked.connect(self._clear)
        foot.addWidget(_b3)
        _b4 = QPushButton('关闭')
        _b4.clicked.connect(self.accept)
        foot.addWidget(_b4)
        v.addLayout(foot)
        self.reload()

    def _fill_choices(self, st):
        ka, kk = self.cb_actor.currentText(), self.cb_kind.currentText()
        self.cb_actor.blockSignals(True)
        self.cb_kind.blockSignals(True)
        self.cb_actor.clear()
        self.cb_actor.addItem('全部')
        for a in st.get('actors', []):
            self.cb_actor.addItem(a)
        self.cb_kind.clear()
        self.cb_kind.addItem('全部')
        for k in st.get('kinds', []):
            self.cb_kind.addItem(k)
        i = self.cb_actor.findText(ka)
        self.cb_actor.setCurrentIndex(i if i >= 0 else 0)
        i = self.cb_kind.findText(kk)
        self.cb_kind.setCurrentIndex(i if i >= 0 else 0)
        self.cb_actor.blockSignals(False)
        self.cb_kind.blockSignals(False)

    def reload(self):
        gov = self.gov
        st = gov.audit_stats()
        self._fill_choices(st)
        kind = self.cb_kind.currentText() or '全部'
        actor = self.cb_actor.currentText() or '全部'
        items = gov.read_filtered(kind=kind, actor=actor,
                                  only_denied=self.ck_denied.isChecked(), limit=500)
        self.lb_stat.setText('今日 %d 条 · 被拒 %d 条 · 涉及对象 %d 个　——　当前筛选出 %d 条'
                             % (st['total'], st['denied'], len(st['actors']), len(items)))
        denied_color = QColor(DEFAULT_THEME['ui_red_soft'])
        self.tb.setRowCount(0)
        for e in items:
            r = self.tb.rowCount()
            self.tb.insertRow(r)
            ok = e.get('allowed', True)
            cells = [str(e.get('ts', ''))[11:], str(e.get('kind', '')), str(e.get('actor', '')),
                     str(e.get('action', '')),
                     ('✓ ' if ok else '✗ 被拒 · ') + str(e.get('detail', ''))]
            for c, txt in enumerate(cells):
                it = QTableWidgetItem(txt)
                if not ok:
                    it.setForeground(denied_color)
                self.tb.setItem(r, c, it)
        if items:
            self.lb_hint.setText('最多显示 500 条（新→旧）。日志按天落在 logs/audit_YYYY-MM-DD.jsonl。')
        else:
            self.lb_hint.setText('当前条件下没有记录。每次技能/MCP 调用、安装、授权、拒绝都会写一条。')
        self.lb_path.setText('文件：%s' % st.get('path', ''))

    def _export(self):
        path, _f = QFileDialog.getSaveFileName(
            self, '导出当日审计', 'audit_%s.csv' % time.strftime('%Y-%m-%d'), 'CSV (*.csv)')
        if not path:
            return
        ok, n = self.gov.export_csv(path)
        QMessageBox.information(self, '导出审计',
                                ('已导出 %d 条 →\n%s' % (n, path)) if ok else ('导出失败：%s' % n))

    def _clear(self):
        if QMessageBox.question(self, '清空当日',
                                '清空今天的审计日志？\n会先改名备份成 .bak-<时间>，不会直接删。') != QMessageBox.Yes:
            return
        ok, msg = self.gov.clear_day()
        QMessageBox.information(self, '清空当日', msg if ok else '没清成：%s' % msg)
        self.reload()


class _NetDialog(QDialog):
    """出网白名单（v6.78 · 治理增强②）—— 可视化增删 + 试算

    安全底线：**白名单为空 = 技能一律禁止出网**（默认如此，本窗口不改变这个语义）。
    """

    def __init__(self, host=None, parent=None):
        super().__init__(parent)
        import governance as gov
        self.gov = gov
        self.host = host
        self.setWindowTitle('🌐 出网白名单')
        self.resize(780, 480)
        v = QVBoxLayout(self)
        tip = QLabel('白名单为空 = 技能一律禁止出网（安全底线）。规则支持 *.example.com 这种通配；'
                     '「试算」用的是与真实拦截同一套判定，结果一定一致。')
        tip.setStyleSheet(STYLE_HINT)
        tip.setWordWrap(True)
        v.addWidget(tip)

        self.tb = QTableWidget(0, 2)
        self.tb.setHorizontalHeaderLabels(['规则', '来源'])
        self.tb.verticalHeader().setVisible(False)
        self.tb.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tb.setSelectionBehavior(QTableWidget.SelectRows)
        self.tb.horizontalHeader().setStretchLastSection(True)
        self.tb.setColumnWidth(0, 320)
        v.addWidget(self.tb)

        self.lb_msg = QLabel('')
        self.lb_msg.setStyleSheet(STYLE_HINT)
        self.lb_msg.setWordWrap(True)
        v.addWidget(self.lb_msg)

        bar = QHBoxLayout()
        for text, fn in (('➕ 添加规则…', self._add), ('🗑 删除选中', self._remove),
                        ('🧪 试算一个地址…', self._explain), ('🔄 刷新', self.reload)):
            _b = QPushButton(text)
            _b.clicked.connect(fn)
            bar.addWidget(_b)
        bar.addStretch(1)
        _b = QPushButton('关闭')
        _b.clicked.connect(self.accept)
        bar.addWidget(_b)
        v.addLayout(bar)
        self.reload()

    def _mcp_hosts(self):
        """从已配置的 MCP server 里抽出域名，用来标注规则的来源（不臆造，能对上才标）"""
        hosts = set()
        try:
            for s in (self.host.mcp.servers() if self.host is not None and getattr(self.host, 'mcp', None) else []):
                for key in ('url', 'endpoint', 'command'):
                    val = str(s.get(key, '') or '')
                    if val.startswith('http'):
                        h = self.gov.host_of(val)
                        if h:
                            hosts.add(h)
        except Exception:
            pass
        return hosts

    def reload(self):
        rules = self.gov.net_allowlist()
        mcp_hosts = self._mcp_hosts()
        self.tb.setRowCount(0)
        for r in rules:
            row = self.tb.rowCount()
            self.tb.insertRow(row)
            src = '手动添加'
            if any(self.gov.host_of('http://' + h) and (h == r.lower() or h.endswith(r.lower().lstrip('*.'))) for h in mcp_hosts):
                src = '来自 MCP 配置'
            self.tb.setItem(row, 0, QTableWidgetItem(r))
            self.tb.setItem(row, 1, QTableWidgetItem(src))
        if rules:
            self.lb_msg.setText('当前 %d 条规则。规则只影响**第三方技能包**的出网；桌宠自身的 API 调用不受它管。'
                                % len(rules))
        else:
            self.lb_msg.setText('当前是空的 —— 技能一律不能出网（这是安全默认）。需要时再加域名。')

    def _add(self):
        text, ok = QInputDialog.getText(self, '添加规则', '域名或通配模式（如 api.deepseek.com / *.github.com）：')
        p = (text or '').strip()
        if not (ok and p):
            return
        if ' ' in p or '/' in p or ('.' not in p and p not in ('*', '*.*')):
            QMessageBox.information(self, '格式不对', '填域名就行，不要带协议/路径，例如 api.deepseek.com')
            return
        self.gov.add_net_rule(p)
        self.reload()

    def _remove(self):
        r = self.tb.currentRow()
        if r < 0:
            return
        item = self.tb.item(r, 0)
        rule = item.text() if item else ''
        if not rule:
            return
        if QMessageBox.question(self, '删除规则', '删除规则 %s？' % rule) != QMessageBox.Yes:
            return
        left = [x for x in self.gov.net_allowlist() if x != rule]
        self.gov.set_net_allowlist(left)
        self.reload()

    def _explain(self):
        text, ok = QInputDialog.getText(self, '试算', '输入一个完整地址（含 http(s)://）：', text='https://')
        if not (ok and text):
            return
        good, why, rule, host = self.gov.net_explain(text)
        QMessageBox.information(
            self, '试算结果',
            '地址：%s\n域名：%s\n\n结果：%s\n原因：%s%s'
            % (text, host or '（解析不出）', '✅ 能过' if good else '⛔ 不能过', why,
               ('\n命中规则：%s' % rule) if rule else ''))
