# -*- coding: utf-8 -*-
"""
DeepSeek 桌宠助手 v5
====================
动画系统 v2（自然版）：
- 呼吸：整图缩放 1%（轻微起伏）
- 呆毛摆动：头顶头发层独立 ±8° 旋转
- 眨眼：blink 立绘局部替换眼睛区域（整图切换，150ms）
- 尾巴动感：整图 ±1.5° 低频摇摆（幅度小，不显全身晃动）
- 保留：双角色、位置记忆、打字机、托盘、连击等全部功能

运行：python desktop_pet.py
"""
import sys
import os
import json
import random
import math
import time
import ctypes
import threading  # v6.18 ApiStats 需要
import datetime  # v6.18 ApiStats 需要（record/调试日志）
import winsound

# P1 模块化：系统工具层 / 存储层（拆自本文件，纯函数无 UI 依赖）
from pet_sysutils import (
    check_dangerous as _check_dangerous,
    read_clipboard_text as _read_clipboard_text,
    write_clipboard_text as _write_clipboard_text,
    run_ps as _run_ps,
    volume_ps as _volume_ps,
    hotkey_filter_factory as _hotkey_filter_factory,
    quote_ps_single as _ps_quote,
    open_shell_target as _open_shell_target,
    open_url as _open_url,
    open_search_url as _open_search_url,
    is_safe_process_name as _is_safe_process_name,
)
from pet_storage import atomic_write_json as _atomic_write_json_impl
from pet_log import get_logger
from pet_docs import (read_docx_text, read_pdf_text, read_xlsx_text, read_pptx_text,
                        ocr_image, read_own_file, TEXT_BY_KIND)
from pet_selfcode import search_code, write_file_tool, edit_own_code

log = get_logger('ui')
from api_stats import ApiStats
from deepseek_client import chat_completions, stream_chat_completions
from memory_store import load_memory, save_memory, remember_fact
from memory_engine import search_memory, extract_memories
from chat_render import split_rich_blocks, split_md_blocks, md_to_html, md_table, looks_like_table
from chat_cards import CodeCard as _CodeCard, TableCard as _TableCard
from prompt_builder import guess_status, build_memory_block, build_todo_block, build_system_prompt
from code_checker import check_python_blocks
import pet_bubble as pb  # 气泡/Markdown 渲染装配层（批 3）
import pet_anim as anim  # 状态机与动画（低耦合段，批 4）
from pet_anim import SCENE_ACTIONS  # 场景动作表（批 4）
from care_engine import user_idle_minutes, judge_wakeup, followup_message
from model_registry import (ModelRegistry, clamp_tokens, DEFAULT_ENDPOINT,
                            MAX_OUTPUT_TOKENS, MIN_OUTPUT_TOKENS)
from model_manager_ui import ModelManagerDialog  # Phase 2 模型管理对话框
from settings_ui import SettingsDialog  # Phase 5 统一设置窗口
from tools_registry import AI_TOOLS, TOOL_STATUS
from tools_executor import get_time_str, calculate_expr, lock_screen_now, query_weather, parse_choices
from PySide6.QtCore import Qt, QTimer, QPoint, QRect, QRectF, Signal, Slot as QtSlot
from PySide6.QtGui import QPixmap, QPainter, QColor, QAction, QPainterPath, QFont, QIcon, QImage, QTransform, QCursor
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QMenu, QGraphicsOpacityEffect,
    QVBoxLayout, QHBoxLayout, QPushButton, QFrame, QSizePolicy,
    QSystemTrayIcon, QTextBrowser, QTextEdit, QLineEdit, QInputDialog, QScrollArea,
    QListWidget, QListWidgetItem, QAbstractItemView
)
from mcp_bridge import McpBridge  # v6.20 MCP 桥接（外部 MCP server 工具接入）
from plugin_manager import PluginManager  # v6.21 插件系统（tool/menu/rules/theme/skill）
from affection_engine import AffectionEngine  # v6.30 好感度引擎
from memory_events import MemoryEvents  # v6.30 回忆日志
from affection_ui import RelationDialog, CostBubble, MemoriesDialog  # v6.30 关系面板/费用气泡/回忆相册
from pet_minigames import GameWindow  # v6.30 小游戏

# Windows DWM 常量（保留 DWMWA_NCRENDERING_POLICY 备用于未来阴影处理）
DWMWA_NCRENDERING_POLICY = 2
DWMNCRP_DISABLED = 1
WS_EX_TOOLWINDOW = 0x80

if getattr(sys, 'frozen', False):
    # PyInstaller 打包：资源在 exe 同目录（用户放 assets/config.json 在旁边）
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OCR_PS1 = os.path.join(BASE_DIR, 'ocr_helper.ps1')
LIVE2D_MODEL = os.path.join(BASE_DIR, 'assets', 'live2d', 'mao', 'Mao.model3.json')
ASSETS = os.path.join(BASE_DIR, 'assets')
CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')
MODELS_PATH = os.path.join(BASE_DIR, 'models.json')   # 模型档案（模型身份的唯一来源）
MEMORY_PATH = os.path.join(BASE_DIR, 'memory.json')
TODO_PATH = os.path.join(BASE_DIR, 'todos.json')
AFFECTION_PATH = os.path.join(BASE_DIR, 'affection.json')   # v6.30 好感度
MEMORIES_PATH = os.path.join(BASE_DIR, 'memories.json')     # v6.30 回忆日志

def asset(role, state):
    p = os.path.join(ASSETS, role, f'{role}_{state}.png')
    if os.path.exists(p):
        return p
    # v6.30 兜底：新状态素材缺失时降级到已有状态
    fallback = {'hungry': 'eating', 'victory': 'happy', 'defeat': 'sad',
                'kiss': 'hug_whale', 'shy_hug': 'hug_whale'}
    fb = fallback.get(state)
    if fb:
        p2 = os.path.join(ASSETS, role, f'{role}_{fb}.png')
        if os.path.exists(p2):
            return p2
    return os.path.join(ASSETS, role, f'{role}_idle.png')

# ============ 国际化（v6.20，右键菜单/提示/AI 回复语言） ============
UI_ZH = {
    'menu_role': '🎭 角色', 'menu_chat': '🤖 和 AI 聊天', 'menu_interact': '💬 互动',
    'say': '💬 说句话', 'think': '🤔 思考一下', 'random': '🎲 随机动作', 'sleep': '💤 睡觉/唤醒',
    'toggle_chat': '💬 隐藏/显示聊天窗口', 'active_care': '💗 主动关心',
    'edge_mode': '📌 贴边模式：', 'edge_hidden': '完全消失', 'edge_peek': '扒边',
    'menu_actions': '🎬 动作', 'menu_personality': '🎭 性格切换', 'menu_settings': '⚙️ 设置',
    'api_setting': '🔑 API 设置…', 'search_setting': '🌐 联网搜索', 'dlg_search': '联网搜索设置', 'attach_tip': '附加文件', 'model_menu': '🎯 角色模型', 'current': '当前', 'thinking': '思考模式', 'temperature': '采样温度', 'model_mgr': '🎯 模型管理…',
    'style_menu': '💬 回复风格', 'token_menu': '📝 回复长度', 'custom': '🎯 自定义…',
    'city': '🌆 默认城市…', 'custom_personality': '🎭 自定义性格…',
    'memory_menu': '🧠 记忆管理', 'view_memory': '📋 查看记忆', 'delete_memory': '🗑 删除一条…', 'clear_memory': '🧹 清空全部…',
    'export_chat': '📤 导出聊天记录', 'mem_time': '时间', 'mem_who': '谁', 'mem_select_all': '全选', 'mem_select_none': '全不选', 'mem_select_me': '只选我', 'mem_select_pet': '只选桌宠', 'mem_export': '导出', 'autostart': '🚀 开机自启', 'on': '（已开）', 'off': '（已关）',
    'hide_tray': '🏠 最小化到托盘', 'exit': '✕ 退出',
    'language_menu': '🌐 语言', 'language_zh': '中文', 'language_en': 'English',
    'chat_placeholder': '和桌宠聊天…（Enter 发送，Shift+Enter 换行，/clear 清空）',
    'person_gentle': '温柔', 'person_tsundere': '傲娇', 'person_sarcastic': '吐槽', 'person_energetic': '元气', 'person_cold': '高冷',
    'style_short': '极简', 'style_normal': '标准', 'style_detailed': '详细',
    'tok_short': '短（500）', 'tok_normal': '标准（1000）', 'tok_long': '长（2000）', 'tok_xlong': '超长（4000）', 'tok_max': '极长（16000）', 'tok_big': '超长2（32000）', 'tok_huge': '超长3（64000）', 'tok_xhuge': '极限（128000）',
    'lang_hint': '请用中文回复。', 'lang_switched': '语言已切换为中文',
    'dlg_api': '🔑 API 设置', 'dlg_model': '模型设置', 'dlg_city': '默认城市',
    'dlg_personality': '自定义性格', 'dlg_tokens': '回复长度',
    'dlg_delete_mem': '删除记忆', 'dlg_clear_mem': '清空记忆', 'dlg_confirm': '⚠️ 危险操作确认',
    'allow': '允许执行', 'deny': '拒绝', 'show_pet': '🏠 显示桌宠',
    'archive': '📦 存档并清空对话', 'mem_mgr': '🖥️ 管理窗口…', 'mem_add': '➕ 添加记忆', 'mem_delete': '🗑 删除选中', 'mem_all': '全部',
    'mem_search': '🔍 搜索记忆…', 'mem_imp': '重要度', 'mem_content': '内容', 'mem_role': '角色', 'mem_time': '时间', 'mem_edit': '编辑',
    'reminder_menu': '⏰ 提醒管理', 'rem_left': '剩余', 'rem_type': '类型', 'rem_cancel': '🗑 取消选中',
    'rem_clear': '🧹 清空全部', 'rem_none': '暂无提醒', 'rem_followup': '回访', 'rem_normal': '提醒',
    'mem_backup': '💾 备份记忆', 'mem_import': '📥 导入记忆',
    'l2d_preview': '🔧 Live2D 调试窗口', 'mode_menu': '🎭 显示模式', 'mode_static': '🖼️ 静态立绘', 'mode_live2d': '🎬 Live2D 模式',
    'l2d_model_menu': '🤖 Live2D 模型', 'l2d_no_model': '未找到模型',
    'todo_menu': '📋 待办管理', 'todo_status': '状态', 'todo_time': '时间', 'todo_add': '➕ 添加',
    'todo_done': '✅ 完成选中', 'todo_del': '🗑 删除选中', 'todo_clear_done': '🧹 清空已完成',
    'todo_placeholder': '输入待办事项，回车添加…', 'todo_empty': '暂无待办',
}
UI_EN = {
    'menu_role': '🎭 Characters', 'menu_chat': '🤖 Chat with AI', 'menu_interact': '💬 Interact',
    'say': '💬 Say something', 'think': '🤔 Think', 'random': '🎲 Random action', 'sleep': '💤 Sleep/Wake',
    'toggle_chat': '💬 Show/Hide chat', 'active_care': '💗 Proactive care',
    'edge_mode': '📌 Edge mode: ', 'edge_hidden': 'Hidden', 'edge_peek': 'Peek',
    'menu_actions': '🎬 Actions', 'menu_personality': '🎭 Personality', 'menu_settings': '⚙️ Settings',
    'api_setting': '🔑 API Settings…', 'search_setting': '🌐 Web Search', 'dlg_search': 'Web Search Settings', 'attach_tip': 'Attach files', 'model_menu': '🎯 Models', 'current': 'Current', 'thinking': 'Thinking', 'temperature': 'Temperature', 'model_mgr': '🎯 Model Manager…',
    'style_menu': '💬 Reply style', 'token_menu': '📝 Reply length', 'custom': '🎯 Custom…',
    'city': '🌆 Default city…', 'custom_personality': '🎭 Custom personality…',
    'memory_menu': '🧠 Memory', 'view_memory': '📋 View memory', 'delete_memory': '🗑 Delete one…', 'clear_memory': '🧹 Clear all…',
    'export_chat': '📤 Export chat', 'mem_time': 'Time', 'mem_who': 'Who', 'mem_select_all': 'All', 'mem_select_none': 'None', 'mem_select_me': 'Me only', 'mem_select_pet': 'Pet only', 'mem_export': 'Export', 'autostart': '🚀 Auto-start', 'on': ' (ON)', 'off': ' (OFF)',
    'hide_tray': '🏠 Minimize to tray', 'exit': '✕ Exit',
    'language_menu': '🌐 Language', 'language_zh': '中文', 'language_en': 'English',
    'chat_placeholder': 'Chat with pet… (Enter send, Shift+Enter newline, /clear reset)',
    'person_gentle': 'Gentle', 'person_tsundere': 'Tsundere', 'person_sarcastic': 'Sarcastic', 'person_energetic': 'Energetic', 'person_cold': 'Cold',
    'style_short': 'Minimal', 'style_normal': 'Normal', 'style_detailed': 'Detailed',
    'tok_short': 'Short (500)', 'tok_normal': 'Normal (1000)', 'tok_long': 'Long (2000)', 'tok_xlong': 'Extra (4000)', 'tok_max': 'Very long (16000)', 'tok_big': 'XXLong (32000)', 'tok_huge': 'XXXLong (64000)', 'tok_xhuge': 'Max (128000)',
    'lang_hint': 'Please reply in English.', 'lang_switched': 'Language switched to English',
    'dlg_api': '🔑 API Settings', 'dlg_model': 'Model Settings', 'dlg_city': 'Default City',
    'dlg_personality': 'Custom Personality', 'dlg_tokens': 'Reply Length',
    'dlg_delete_mem': 'Delete Memory', 'dlg_clear_mem': 'Clear Memory', 'dlg_confirm': '⚠️ Confirm Dangerous Operation',
    'allow': 'Allow', 'deny': 'Deny', 'show_pet': '🏠 Show pet',
    'archive': '📦 Archive & Clear Chat', 'mem_mgr': '🖥️ Manager Window…', 'mem_add': '➕ Add Memory', 'mem_delete': '🗑 Delete Selected', 'mem_all': 'All',
    'mem_search': '🔍 Search memory…', 'mem_imp': 'Importance', 'mem_content': 'Content', 'mem_role': 'Role', 'mem_time': 'Time', 'mem_edit': 'Edit',
    'reminder_menu': '⏰ Reminders', 'rem_left': 'Left', 'rem_type': 'Type', 'rem_cancel': '🗑 Cancel Selected',
    'rem_clear': '🧹 Clear All', 'rem_none': 'No reminders', 'rem_followup': 'Follow-up', 'rem_normal': 'Reminder',
    'mem_backup': '💾 Backup Memory', 'mem_import': '📥 Import Memory',
    'l2d_preview': '🔧 Live2D Debug Window', 'mode_menu': '🎭 Display Mode', 'mode_static': '🖼️ Static Art', 'mode_live2d': '🎬 Live2D Mode',
    'l2d_model_menu': '🤖 Live2D Model', 'l2d_no_model': 'No models found',
    'todo_menu': '📋 Todo Manager', 'todo_status': 'Status', 'todo_time': 'Time', 'todo_add': '➕ Add',
    'todo_done': '✅ Done', 'todo_del': '🗑 Delete', 'todo_clear_done': '🧹 Clear Done',
    'todo_placeholder': 'Enter todo, press Enter to add…', 'todo_empty': 'No todos',
}

# ============ 模型档案（模型身份配置化）============
# models.json 是模型身份的唯一来源：显示名 / 模型 ID / 接口地址 / 参数 / 价格 / 外观 / 人设。
# 原先写死在这里的 CHARACTERS 字典已整体迁入档案（见 model_registry.BUILTIN_PROFILES），
# 本处改为运行时从档案构建，结构与旧字典完全兼容（下游用法无需改动）。
MODEL_REGISTRY = ModelRegistry(MODELS_PATH, CONFIG_PATH)


def build_characters(registry=None):
    """由模型档案构建角色表（color 由档案里的 hex 转 QColor）"""
    reg = registry or MODEL_REGISTRY
    out = {}
    for ckey, conf in reg.characters().items():
        conf = dict(conf)
        try:
            conf['color'] = QColor(conf.get('color') or '#B0C4DE')
        except Exception:
            conf['color'] = QColor(176, 196, 222)
        out[ckey] = conf
    return out


CHARACTERS = build_characters()

GREET_INTERVAL = (20 * 60 * 1000, 40 * 60 * 1000)

# 场景动作立绘
# SCENE_ACTIONS 已搬至 pet_anim（批 4），由下方 import 引入

# ============ AI 工具定义（function calling） ============


# ============ PowerShell 安全执行（v6） ============
import re as _re
import subprocess as _subprocess

# blink 图相对 idle 的平移偏移（相位相关测得）：用于对齐整图切换眨眼
# 切换时其他部位完全重合，只有眼睛变化，不闪
BLINK_OFFSETS = {
    'flash': (0, 0),
    'pro': (0, 0),
}


def _hotkey_filter_factory(callbacks):
    """创建全局热键过滤器（WM_HOTKEY）。callbacks: {hotkey_id: callback}"""
    import ctypes.wintypes  # 必须显式导入（Python 3.14 中 ctypes.wintypes 不随 ctypes 自动加载）
    from PySide6.QtCore import QAbstractNativeEventFilter
    class _HotkeyFilter(QAbstractNativeEventFilter):
        def nativeEventFilter(self, eventType, message):
            try:
                # PySide6 的 eventType 是 QByteArray（不是 str/bytes），message 是 VoidPtr
                et = bytes(eventType) if hasattr(eventType, '__bytes__') else str(eventType).encode('utf-8', 'ignore')
                if b'windows_generic_MSG' in et:
                    msg = ctypes.wintypes.MSG.from_address(int(message))
                    if msg.message == 0x0312:  # WM_HOTKEY
                        cb = callbacks.get(msg.wParam)
                        if cb:
                            cb()
                            return True, 0
            except Exception:
                pass
            return False, 0
    return _HotkeyFilter()


# ---------- API 统计（v6.18 自监控：解析 usage，无代理无断链） ----------
# 主题变量（v6.23 主题系统）：默认深蓝黑风格，theme 插件可覆盖
DEFAULT_THEME = {
    'panel_bg': 'rgba(20,20,30,0.85)',
    'text': '#eee',
    'input_bg': 'rgba(255,255,255,0.12)',
    'input_focus': 'rgba(255,255,255,0.18)',
    'user_bubble': 'rgba(30,88,70,0.80)',
    'ai_bubble': 'rgba(46,54,76,0.80)',
    'name_user': '#6fe3a1',
    'name_ai': '#7fb2ff',
    'accent': '#7fb2ff',
    'scroll_bg': 'rgba(255,255,255,0.08)',
    'scroll_handle': '#ffffff',
    'scroll_handle_hover': 'rgba(255,255,255,0.65)',
    'bubble_text': '#eee',  # v6.44 气泡内文字颜色（主题化：白底气泡需配深色文字）
    # v6.51 顶部说话气泡（say_plain）的配色——此前写死在控件里，换深色主题后仍是刺眼白底
    'say_bg': 'rgba(255,255,255,0.92)',
    'say_text': '#333',
    'say_border': '#ccc',
}


class _DropChatEdit(QTextEdit):
    """支持文件拖放的聊天输入框（QTextEdit 默认不接受 uri-list 拖放，需子类化）"""
    def __init__(self, on_files, parent=None):
        super().__init__(parent)
        self._on_files = on_files
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)  # 关键：拖放事件实际到达 viewport

    def viewportEvent(self, e):
        """viewport 级拖放：接受文件拖入，drop 后把路径插入输入框"""
        from PySide6.QtCore import QEvent as _QE
        t = e.type()
        if t in (_QE.Type.DragEnter, _QE.Type.DragMove):
            if e.mimeData().hasUrls():
                e.acceptProposedAction()
                return True
        elif t == _QE.Type.Drop:
            if e.mimeData().hasUrls():
                self._on_files(e.mimeData().urls())
                e.accept()
                return True
        return super().viewportEvent(e)


class PetWidget(QWidget):
    # 类级信号：AI 回复（跨线程安全）
    ai_reply_signal = Signal(str)
    ai_status_signal = Signal(str)  # AI 处理状态（思考中/正在执行xx）
    stream_signal = Signal(str)     # v6.40 流式正文 chunk
    reasoning_signal = Signal(str)  # v6.40 流式思考 chunk
    stream_done_signal = Signal()   # v6.40 流式结束
    wakeup_signal = Signal(str)    # 主动消息（心跳/回访触发）
    confirm_signal = Signal(object)  # 危险操作确认请求（跨线程回调）
    weather_signal = Signal(str)   # 早安日报天气结果（跨线程安全）
    ocr_signal = Signal(str)       # OCR 识别结果（截图粘贴，跨线程安全）
    cost_bubble_signal = Signal(float)  # v6.30 API 费用气泡（跨线程）

    def __init__(self):
        super().__init__()
        self.current = 'flash'
        self.pet_size = 260
        self.dragging = False
        self.drag_offset = QPoint()
        self.sleeping = False
        self.state = 'idle'          # idle / thinking / happy
        self.phase = 0
        self.base_x = None
        self.base_y = None
        self.type_timer = QTimer(self)
        self.type_timer.timeout.connect(self._type_next)
        self.type_buffer = ''
        self.type_index = 0
        self.chat_type_timer = QTimer(self)  # 聊天面板打字机（AI 回复流式显示）
        self.chat_type_timer.timeout.connect(self._chat_type_tick)
        self.chat_type_buffer = ''
        self.chat_type_index = 0
        self.click_times = []
        self.thinking_timer = None
        self._emotion_restore_timer = None  # 情绪立绘恢复定时器（10 秒）
        self.bubble_hide_timer = QTimer(self)
        self.bubble_hide_timer.setSingleShot(True)
        self.bubble_hide_timer.timeout.connect(self._hide_bubble)
        self.ai_enabled = False
        self.display_mode = 'static'  # static/live2d（_load_ai_config 会覆盖）
        self.live2d_model = 'mao'
        self._load_ai_config()
        self.app_aliases = self._load_aliases()
        # v6.30 好感度与成长系统（引擎 + 回忆日志）
        self.affection = AffectionEngine(AFFECTION_PATH)
        self.memories = MemoryEvents(MEMORIES_PATH)
        self._relation_dialog = None
        self._game_window = None
        self._pending_choices = None   # v6.30 情感选项
        self._choices_requested = False
        # v6.30 饱食度巡检（每 5 分钟，低饱食提示）
        self._satiety_timer = QTimer(self)
        self._satiety_timer.timeout.connect(self._check_satiety)
        self._satiety_timer.start(5 * 60 * 1000)
        self.cost_bubble_signal.connect(self._on_cost_bubble)
        self._last_satiety_warn = 0.0
        # v6.40 真流式：信号连接
        self.stream_signal.connect(self._on_stream)
        self.reasoning_signal.connect(self._on_reasoning)
        self.stream_done_signal.connect(self._on_stream_done)
        self._stream_active = False
        self._stream_rendered = False
        self._stream_text = ''
        self._stream_label = None
        self._thinking_label = None
        # AI 回复信号（类级定义，connect 跨线程槽）
        self.ai_reply_signal.connect(self._display_ai_reply)
        self.ai_status_signal.connect(self._update_ai_status)
        self.wakeup_signal.connect(self._display_wakeup)
        self.confirm_signal.connect(lambda fn: fn())  # 确认回调在主线程执行
        # 全局快捷键 Ctrl+Alt+P 呼出 / Ctrl+Alt+S 截图 OCR
        self._hotkey_installed = False
        try:
            app = QApplication.instance()
            if app is not None:
                self._hotkey_filter = _hotkey_filter_factory({1: self._on_global_hotkey, 2: self._on_screenshot_hotkey})
                app.installNativeEventFilter(self._hotkey_filter)
                if ctypes.windll.user32.RegisterHotKey(None, 1, 0x0002 | 0x0001, 0x50):  # MOD_CONTROL|MOD_ALT, 'P'
                    self._hotkey_installed = True
                try:
                    ctypes.windll.user32.RegisterHotKey(None, 2, 0x0002 | 0x0001, 0x44)  # Ctrl+Alt+D 截图 OCR
                except Exception:
                    pass
        except Exception:
            self._hotkey_installed = False
        # 对话记忆 + 定时提醒 + 贴边
        self.chat_history_msgs = []
        self.display_msgs = []
        self.api_stats = ApiStats(os.path.join(BASE_DIR, 'api_stats.json'), config_path=CONFIG_PATH,
                                  registry=MODEL_REGISTRY)  # v6.18 API 自监控（价格表改读模型档案）
        self._api_stats_win = None
        self.mcp = McpBridge(CONFIG_PATH)  # v6.20 MCP 桥接：后台连接配置的 MCP server
        self.mcp.connect_all()
        self.plugin_mgr = PluginManager(os.path.join(BASE_DIR, 'plugins'))  # v6.21 插件管理器
        self.current_theme = 'default'  # v6.23 主题系统：default / theme 插件名
        self.theme = dict(DEFAULT_THEME)
        self._pending_attachments = []  # 统一附件暂存（除 Ctrl+Alt+D 全局截图外，文件/图片先暂存）      # 聊天面板显示历史（含系统提示/提醒/唤醒，供回显与导出）
        self.personality = '温柔'
        self.memory_facts = []      # 长期事实记忆
        self.memory_summaries = []  # 会话摘要
        self._load_memory()
        self.todos = []             # 待办清单
        self._load_todos()
        self._load_chat_memory()
        self._display_offset = 0   # 显示历史已加载起点（显示更多用）
        self.reminders = []
        self._load_reminders()      # 加载持久化提醒（含关机期间错过的补发）
        self.reminder_timer = QTimer(self)
        self.reminder_timer.timeout.connect(self._check_reminders)
        self.reminder_timer.start(1000)
        self._edge_docked = False
        self._edge_side = None
        self._edge_popped = False
        # 主动说话（v6.17）：随机间隔 8-20 分钟冒泡一句
        self.active_chat_enabled = False
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as _f:
                self.active_chat_enabled = bool(json.load(_f).get('active_chat', False))
        except Exception:
            self.active_chat_enabled = False
        self._active_chat_next = time.time() + random.uniform(480, 1200)
        self.active_chat_timer = QTimer(self)
        self.active_chat_timer.timeout.connect(self._check_active_chat)
        self.active_chat_timer.start(30000)  # 每 30 秒检查一次
        self._popup_y = 0
        self._popup_x = 0
        self._chat_hidden_for_dock = False
        self._edge_mode = 'peek'   # 'peek'=扒边模式(默认) / 'hidden'=完全消失模式

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(440, 560)
        # 窗口透明由 DPI awareness + WA_TranslucentBackground 保证（不再需要手工清边框）

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        self.bubble = QLabel(self)
        self.bubble.setWordWrap(True)
        self.bubble.setAlignment(Qt.AlignCenter)
        self.bubble.setStyleSheet("""
            QLabel {
                background-color: rgba(255,255,255,0.92);
                color: #333; border: 2px solid #ccc;
                border-radius: 10px; padding: 8px 12px; font-size: 13px;
            }
        """)
        self.bubble.setMaximumWidth(400)
        self.bubble.setMaximumHeight(220)
        # 气泡不参与布局排版（悬浮定位，避免挤压控制栏导致上下跳动）
        self.bubble.setParent(self)
        self.bubble.hide()

        self.pet_label = QLabel(self)
        self.pet_label.setAlignment(Qt.AlignCenter)
        self.pet_label.setFixedSize(self.pet_size, self.pet_size)
        # 显示模式容器：静态立绘 / Live2D 可切换
        from PySide6.QtWidgets import QStackedWidget
        self.pet_stack = QStackedWidget(self)
        self.pet_stack.addWidget(self.pet_label)
        self.layout.addWidget(self.pet_stack, 0, Qt.AlignHCenter)

        # 聊天窗口（替代原功能按钮栏）
        self.chat_panel = QFrame(self)
        self.chat_panel.setStyleSheet(self._panel_qss())  # v6.23 主题变量化样式
        chat_layout = QVBoxLayout(self.chat_panel)
        chat_layout.setContentsMargins(8, 4, 8, 8)
        chat_layout.setSpacing(6)

        # 聊天历史（只读）
        self.chat_more_btn = QLabel('📜 显示更多历史', self.chat_panel)
        self.chat_more_btn.setStyleSheet("color:#7fb2ff; font-size:11px; padding:2px; cursor:pointer;")
        self.chat_more_btn.setAlignment(Qt.AlignCenter)
        self.chat_more_btn.setCursor(Qt.PointingHandCursor)
        self.chat_more_btn.mousePressEvent = lambda e: self._load_more_history()
        self.chat_more_btn.hide()
        chat_layout.addWidget(self.chat_more_btn)
        self.chat_history_scroll = QScrollArea(self.chat_panel)
        self.chat_history_scroll.setWidgetResizable(True)
        self.chat_history_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.chat_history_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chat_history_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.chat_history_container = QWidget()
        self.chat_history_layout = QVBoxLayout(self.chat_history_container)
        self.chat_history_layout.setContentsMargins(2, 2, 4, 2)
        self.chat_history_layout.setSpacing(8)
        self.chat_history_layout.addStretch(1)  # 底部弹簧：消息从顶部排、滚动贴底
        self.chat_history_scroll.setWidget(self.chat_history_container)
        self._status_widget = None  # 当前状态行（⏳/思考中）

        # ===== v6.43b 任务侧栏：FCFS 队列 + 可收缩 + 拖拽调优先级 =====
        self._task_queue = []
        self._cur_task_text = None
        self.chat_task_sidebar = QFrame(self.chat_panel)
        self.chat_task_sidebar.setStyleSheet(
            'QFrame{background:rgba(18,26,44,.5);border-radius:8px;}'
            'QLabel{color:#8aa;font-size:10px;} QListWidget{background:rgba(12,18,32,.6);'
            'color:#dce3f0;border:none;font-size:11px;}')
        _tsv = QVBoxLayout(self.chat_task_sidebar)
        _tsv.setContentsMargins(6, 6, 6, 6)
        _tsv.setSpacing(4)
        _tsh = QHBoxLayout()
        _tsh.setSpacing(4)
        _tsh.addWidget(QLabel('📋 任务', self.chat_task_sidebar))
        _tsh.addStretch(1)
        self.task_collapse_btn = QPushButton('◀', self.chat_task_sidebar)
        self.task_collapse_btn.setFixedSize(18, 18)
        self.task_collapse_btn.setCursor(Qt.PointingHandCursor)
        self.task_collapse_btn.setToolTip('收缩/展开任务侧栏')
        self.task_collapse_btn.clicked.connect(self._toggle_task_sidebar)
        _tsh.addWidget(self.task_collapse_btn)
        _tsv.addLayout(_tsh)
        self.task_list = QListWidget(self.chat_task_sidebar)
        self.task_list.setFixedWidth(178)
        self.task_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.task_list.setDefaultDropAction(Qt.MoveAction)
        self.task_list.itemDoubleClicked.connect(self._cancel_queued_task)
        try:
            self.task_list.model().rowsMoved.connect(self._on_task_reorder)
        except Exception:
            pass
        _tsv.addWidget(self.task_list, 1)
        _tip = QLabel('拖拽排序 · 双击取消排队\n/stop 紧急停止当前', self.chat_task_sidebar)
        _tsv.addWidget(_tip)
        # v6.43b fix：常驻任务把手（侧栏收缩后仍可见，点击展开；收缩按钮◀在侧栏内，侧栏藏了它也会藏）
        self.task_toggle_tab = QPushButton('📋', self.chat_panel)
        self.task_toggle_tab.setFixedSize(22, 40)
        self.task_toggle_tab.setCursor(Qt.PointingHandCursor)
        self.task_toggle_tab.setToolTip('展开/收缩任务队列')
        self.task_toggle_tab.setStyleSheet(
            'QPushButton{background:rgba(18,26,44,.4);color:#9ec;border:none;border-radius:6px;font-size:11px;}'
            'QPushButton:hover{background:rgba(40,60,90,.7);}')
        self.task_toggle_tab.clicked.connect(self._toggle_task_sidebar)
        chat_body = QHBoxLayout()
        chat_body.setSpacing(6)
        chat_body.addWidget(self.chat_history_scroll, 1)
        chat_body.addWidget(self.task_toggle_tab, 0)
        chat_body.addWidget(self.chat_task_sidebar, 0)
        chat_layout.addLayout(chat_body, 1)

        # 输入框（多行自适应：内容多自动增高，超上限内部滚动）
        self.chat_input = _DropChatEdit(self._insert_dropped_paths, self.chat_panel)
        self.setAcceptDrops(True)  # 主窗口级拖放兜底（文件路径插入输入框）
        self.chat_input.setPlaceholderText(self._t('chat_placeholder'))
        self.chat_input.setAcceptRichText(False)  # 粘贴/拖入自动转纯文本，避免富文本格式污染背景
        self.chat_input.setFixedHeight(34)
        self.chat_input.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.chat_input.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chat_input.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.chat_input.document().contentsChanged.connect(self._auto_resize_input)
        self.chat_input.installEventFilter(self)
        self.chat_attach_btn = QPushButton('📎', self.chat_panel)
        self.chat_attach_btn.setFixedSize(30, 34)
        self.chat_attach_btn.setToolTip(self._t('attach_tip') if hasattr(self, '_t') else '附加文件')
        self.chat_attach_btn.setCursor(Qt.PointingHandCursor)
        self.chat_attach_btn.clicked.connect(self._pick_attach_files)
        # 附件暂存栏（输入框上方，卡片形式）
        self.attach_bar = QWidget(self.chat_panel)
        self.attach_bar_layout = QHBoxLayout(self.attach_bar)
        self.attach_bar_layout.setContentsMargins(0, 2, 0, 2)
        self.attach_bar_layout.setSpacing(6)
        self.attach_bar_layout.addStretch(1)
        self.attach_bar.hide()
        chat_layout.addWidget(self.attach_bar)

        input_row = QHBoxLayout()
        input_row.setSpacing(4)
        input_row.addWidget(self.chat_input, 1)
        input_row.addWidget(self.chat_attach_btn)
        chat_layout.addLayout(input_row)

        self.layout.addWidget(self.chat_panel, 0, Qt.AlignHCenter)
        self.chat_panel.setFixedWidth(420)
        self.chat_panel.setFixedHeight(240)
        self._chat_dragging = False
        self._chat_drag_mode = None   # None / 'h'（左/右边）/ 'v_bottom'（下边）/ 'corner_bl'/'corner_br'（下两角）
        self._chat_drag_side = None   # 'left' / 'right'（水平拖拽方向）
        self._chat_drag_start_y = 0
        self._chat_drag_start_h = 0
        self._chat_drag_start_x = 0
        self._chat_drag_start_w = 0
        # 边缘/下角拖拽（把手已全部移除 v6.19c：顶部 v6.19b 移除，底部 v6.19c 移除，改用边缘+下角）
        self.chat_panel.setMouseTracking(True)
        self.chat_panel.mousePressEvent = self._chat_panel_press
        self.chat_panel.mouseMoveEvent = self._chat_panel_move
        self.chat_panel.mouseReleaseEvent = self._chat_panel_release

        # 动画定时器 ~30fps
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.animate)
        self.timer.start(33)

        self.greet_timer = QTimer(self)
        self.greet_timer.timeout.connect(self.say_random)
        QTimer.singleShot(90000, self._schedule_greet)

        self.load_character('flash')
        self._restore_position()

        # 眨眼调度
        self.blink_timer = QTimer(self)
        self.blink_timer.timeout.connect(self._do_blink)
        self.blink_timer.start(random.randint(8000, 15000))
        self._blinking = False

        # 输入感知（打盹/久坐/光标跟随）+ 早安日报
        self._start_idle_system()
        self._start_morning_report()
        self._echo_display_history()  # 面板已就绪，回显上次会话历史
        self.weather_signal.connect(self._on_weather_result)
        self.ocr_signal.connect(self._on_ocr_result)
        # 应用显示模式（config 为 live2d 时直接启用，不弹提示）
        if getattr(self, 'display_mode', 'static') == 'live2d':
            w = self._create_l2d_embedded()
            if w is not None:
                self.pet_stack.addWidget(w)
                self._l2d_widget = w
                self.pet_stack.setCurrentWidget(w)
                self.bubble.raise_()
            else:
                self.display_mode = 'static'

    # ---------- 窗口 ----------
    def _restore_position(self):
        try:
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                x, y = cfg.get('x'), cfg.get('y')
                if x is not None and y is not None:
                    # v6.51 多显示器修正：原先只拿 primaryScreen 判界、且把 x<0 一律当越界，
                    # 副屏在主屏左侧时（x 恒为负）每次启动都被强行拉回主屏。
                    # 现在先问"这个坐标落在哪块屏幕"，再在该屏工作区内钳制窗口。
                    scr = None
                    try:
                        scr = QApplication.screenAt(QPoint(int(x), int(y)))
                    except Exception:
                        scr = None
                    if scr is not None:
                        avail = scr.availableGeometry()
                        x = max(avail.left() - 4, min(int(x), avail.right() - self.width() + 8))
                        y = max(avail.top() - 4, min(int(y), avail.bottom() - self.height() + 8))
                        self.move(x, y)
                        self.base_x, self.base_y = x, y
                        return
        except Exception:
            pass
        screen = QApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()   # v6.51：改用工作区，避免压到任务栏
            self.move(avail.right() - self.width() - 40, avail.bottom() - self.height() - 60)
            self.base_x, self.base_y = self.x(), self.y()

    @staticmethod
    def _atomic_write_json(path, data, pretty=True):
        """原子写 JSON（委托 pet_storage.atomic_write_json，P1 模块化）"""
        _atomic_write_json_impl(path, data, pretty)

    def _save_position(self):
        """保存位置，同时保留已有配置（api key 等不被覆盖）"""
        try:
            cfg = {}
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    try:
                        cfg = json.load(f)
                    except Exception:
                        cfg = {}
            cfg['x'] = self.x()
            cfg['y'] = self.y()
            self._atomic_write_json(CONFIG_PATH, cfg)
        except Exception:
            pass

    def _schedule_greet(self):
        self.greet_timer.start(random.randint(*GREET_INTERVAL))

    # ---------- AI 对话 ----------
    def _t(self, key):
        """取当前语言的 UI 文本"""
        d = UI_EN if getattr(self, 'language', 'zh') == 'en' else UI_ZH
        return d.get(key, UI_ZH.get(key, key))

    def _load_ai_config(self):
        """读取 AI 配置：模型身份（模型 ID/显示名/参数）取自 models.json 档案，其余取自 config.json"""
        global CHARACTERS
        try:
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                self._cfg = cfg            # 供 _api_key_for_field 按字段名取 key
                key = cfg.get('deepseek_api_key', '')
                if key:
                    self.ai_key = key
                    self.ai_enabled = True
                self.search_api_key = cfg.get('search_api_key', '')  # Tavily 联网搜索 key（可选）
                self.pet_city = cfg.get('city', '重庆')
                self.personality = cfg.get('personality', '温柔')
                self.reply_style = cfg.get('reply_style', 'normal')  # short/normal/detailed
                self.language = cfg.get('language', 'zh')  # zh/en
                self.display_mode = cfg.get('display_mode', 'static')  # static/live2d
                self.live2d_model = cfg.get('live2d_model', 'mao')  # Live2D 模型目录名
                # 模型档案是模型身份的唯一来源：角色表每次从档案重建
                # （改 models.json 即可改显示名/台词，无需动代码）
                CHARACTERS = build_characters()
                if CHARACTERS and getattr(self, 'current', 'flash') not in CHARACTERS:
                    self.current = MODEL_REGISTRY.first_key()
                prof = self._current_profile()
                p_flash, p_pro = MODEL_REGISTRY.get('flash'), MODEL_REGISTRY.get('pro')
                if p_flash is not None:
                    self.model_flash = p_flash.model_id
                if p_pro is not None:
                    self.model_pro = p_pro.model_id
                self.ai_model = self._current_model()
                # 输出上限/思考开关/温度统一由档案提供
                # （原先只看 config.json、菜单里没有入口，且上限三处互相矛盾）
                if prof is not None:
                    self.max_tokens = prof.max_tokens
                    self.reasoning_enabled = prof.reasoning
                    self.temperature = prof.temperature
                else:
                    self.max_tokens = clamp_tokens(cfg.get('max_tokens', 1000))
                    self.reasoning_enabled = cfg.get('reasoning', True)
                    self.temperature = float(cfg.get('temperature', 1.0))
        except Exception:
            pass

    def _current_profile(self):
        """当前角色对应的模型档案（档案缺失时回退第一份 / None）"""
        prof = MODEL_REGISTRY.get(getattr(self, 'current', 'flash'))
        if prof is None and len(MODEL_REGISTRY):
            prof = MODEL_REGISTRY.profiles()[0]
        return prof

    def _current_endpoint(self):
        """当前角色使用的接口地址（由档案提供，不再每个模块各写一份）"""
        prof = self._current_profile()
        return prof.endpoint if prof is not None else DEFAULT_ENDPOINT

    def _api_key_for_field(self, field):
        """按字段名从 config.json 取 key。

        档案里的 api_key_field 决定这一份档案用哪把 key，因此同一台机器可以
        让不同档案分别指向不同的服务商 / 中转（各配各的 key）；
        该字段没配时回退到主 key deepseek_api_key。"""
        field = (str(field or '') or 'deepseek_api_key').strip()
        if field == 'deepseek_api_key':
            return getattr(self, 'ai_key', '') or ''
        cfg = getattr(self, '_cfg', None) or {}
        return str(cfg.get(field) or '').strip() or (getattr(self, 'ai_key', '') or '')

    def _current_api_key(self):
        """当前角色该用哪把 key：由档案的 api_key_field 决定"""
        prof = self._current_profile()
        return self._api_key_for_field(
            prof.api_key_field if prof is not None else 'deepseek_api_key')

    def _current_model(self):
        """按当前角色返回实际请求的模型 ID（取自档案；档案不可用时才回退旧字段）"""
        prof = MODEL_REGISTRY.get(getattr(self, 'current', 'flash'))
        if prof is not None and prof.model_id:
            return prof.model_id
        if self.current == 'pro':
            return getattr(self, 'model_pro', 'deepseek-v4-pro')
        return getattr(self, 'model_flash', 'deepseek-flash')

    def _run_task(self, text):
        """v6.43b：立即执行任务（分配代次 + 置 busy + 起线程）"""
        import threading as _th
        self._ai_generation = getattr(self, '_ai_generation', 0) + 1
        self._cur_task_text = text
        self._ai_busy = True
        try:
            self._refresh_task_sidebar()
        except Exception:
            pass
        _th.Thread(target=self._ai_worker, args=(text,), daemon=True).start()

    def _enqueue_task(self, text):
        """v6.43b：任务入队（FCFS）"""
        import time as _time
        self._task_queue.append({'text': text, 'ts': _time.time()})
        try:
            self._refresh_task_sidebar()
        except Exception:
            pass

    def _next_task(self):
        """v6.43b：空闲时执行队列下一个任务（先来先到）"""
        try:
            if self._task_queue and not getattr(self, '_ai_busy', False):
                t = self._task_queue.pop(0)
                self._run_task(t['text'])
            else:
                if not self._task_queue:
                    self._cur_task_text = None
                try:
                    self._refresh_task_sidebar()
                except Exception:
                    pass
        except Exception:
            pass

    def _refresh_task_sidebar(self):
        """v6.43b：刷新任务侧栏（首行=执行中，其后排队可拖拽）"""
        try:
            self.task_list.clear()
            if self._cur_task_text:
                it = QListWidgetItem('⏳ ' + str(self._cur_task_text)[:13])
                it.setFlags(it.flags() & ~Qt.ItemIsDropEnabled & ~Qt.ItemIsDragEnabled)
                self.task_list.addItem(it)
            for i, t in enumerate(self._task_queue):
                it = QListWidgetItem(f'⏸ {i + 1}. ' + str(t.get('text', ''))[:13])
                it.setData(Qt.UserRole, t)
                self.task_list.addItem(it)
        except Exception:
            pass

    def _toggle_task_sidebar(self):
        """v6.43b：收缩/展开任务侧栏"""
        try:
            vis = self.chat_task_sidebar.isVisible()
            self.chat_task_sidebar.setVisible(not vis)
            self.task_collapse_btn.setText('▶' if vis else '◀')
            if hasattr(self, '_sync_window_to_panel'):
                self._sync_window_to_panel()
        except Exception:
            pass

    def _cancel_queued_task(self, item):
        """v6.43b：双击排队任务取消（执行中任务用 /stop）"""
        try:
            t = item.data(Qt.UserRole)
            if t in self._task_queue:
                self._task_queue.remove(t)
                self._refresh_task_sidebar()
        except Exception:
            pass

    def _on_task_reorder(self, parent, start, end, destination, row):
        """v6.43b：拖拽后按新顺序重建队列（跳过执行中行）"""
        try:
            new_q = []
            for r in range(self.task_list.count()):
                t = self.task_list.item(r).data(Qt.UserRole)
                if isinstance(t, dict) and t in self._task_queue:
                    new_q.append(t)
            if new_q:
                self._task_queue = new_q
        except Exception:
            pass

    def _stop_ai(self):
        """v6.43：强制停止当前 AI 任务（突发卡死/工具失控时用）。
        代次 +1 使旧线程失效 → 清理状态 → 闭合悬空任务防复活"""
        try:
            self._ai_generation = getattr(self, '_ai_generation', 0) + 1
            self._ai_busy = False
            try:
                self._remove_status_line()
            except Exception:
                pass
            self._close_pending_user_msg()
            self._save_chat_memory()
            # v6.43b：紧急停止只停当前任务，队列继续（先来先到）
            self._next_task()
        except Exception:
            pass

    def _close_pending_user_msg(self):
        """v6.43：若历史最后一条是悬空 user（AI 未回复=任务中断），补一条中断说明。
        防止下次对话 AI 把旧任务当待办继续执行"""
        try:
            msgs = self.chat_history_msgs
            if msgs and msgs[-1].get('role') == 'user':
                msgs.append({'role': 'assistant', 'content': '（上轮任务已中断取消，如需继续请重新说明）'})
        except Exception:
            pass

    def ask_ai(self, text):
        """调用 DeepSeek API 对话（线程执行，不卡 UI）"""
        self._load_ai_config()  # 热加载：每次聊天前刷新 config.json（改配置无需重启）
        if not self.ai_enabled:
            self._append_chat('桌宠', '还没配置 AI 呢！在 config.json 里加 deepseek_api_key 就能和我聊天了')
            return
        if getattr(self, '_ai_busy', False):
            # v6.43b：忙碌 → 加入 FCFS 任务队列（先来先到；侧栏可拖拽调优先级、双击取消排队）
            self._enqueue_task(text)
            self._append_chat('桌宠',
                              f'📋 已加入任务队列（第 {len(self._task_queue)} 位，当前完成后自动执行；/stop 紧急停止当前）')
            return
        # v6.43b：流式重置 + 启动任务（_run_task 内分配代次/置 busy/起线程）
        # v6.40 fix：新对话重置流式状态（工具调用轮次由续用逻辑接管，避免正文渲染进孤儿气泡）
        self._chat_type_bubble = None
        self._thinking_label = None
        self._thinking_toggle = None
        self._stream_label = None
        self._stream_active = False
        self._stream_text = ''
        self._stream_pending = ''
        self._thinking_pending = ''
        self._stream_rendered = False
        self._run_task(text)

    # ---------- 智能本地应用检索（v6.36） ----------
    COMMON_ALIASES = {
        '微信': 'wechat', 'weixin': 'wechat', 'vx': 'wechat',
        'qq': 'qq', '扣扣': 'qq', '企鹅': 'qq',
        '浏览器': 'edge', '谷歌': 'chrome', '谷歌浏览器': 'chrome', 'chrome': 'chrome',
        '火狐': 'firefox', 'b站': 'bilibili', '哔哩哔哩': 'bilibili',
        'word': 'word', 'excel': 'excel', 'ppt': 'powerpoint', 'wps': 'wps',
        'ps': 'photoshop', 'photoshop': 'photoshop', 'blender': 'blender',
        'steam': 'steam', '网易云': 'cloudmusic', '音乐': 'cloudmusic', '酷狗': 'kugou',
        'vscode': 'code', '代码编辑器': 'code', 'pycharm': 'pycharm',
        'python': 'python', '计算器': 'calculator', 'calc': 'calculator',
        '记事本': 'notepad', '终端': 'terminal', '命令行': 'terminal',
        '任务管理器': 'taskmgr', '控制面板': 'control', '设置': 'settings',
        '资源管理器': 'explorer', '文件管理器': 'explorer', '我的电脑': 'explorer',
        '画图': 'paint', '远程桌面': 'mstsc', '截图': 'snipping',
        'matlab': 'matlab', 'unity': 'unity', 'godot': 'godot',
        'geosim': 'geosim', '桌宠': 'desktop_pet', '夸克': 'quark', '百度网盘': 'baidunetdisk',
        '联想浏览器': 'lenovo', '腾讯会议': 'wemeet', '钉钉': 'dingtalk', '企业微信': 'wecom',
    }

    def _build_app_index(self):
        """扫描本地应用索引：开始菜单快捷方式 + 注册表已安装应用"""
        import subprocess as _sp
        apps = []  # [{name, path, exe}]
        # 1. 开始菜单 .lnk（一个 PowerShell 进程批量解析）
        ps_code = (
            '$ws = New-Object -ComObject WScript.Shell; '
            '$paths = @("$env:ProgramData\\Microsoft\\Windows\\Start Menu\\Programs", '
            '"$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs"); '
            'foreach ($p in $paths) { if (Test-Path $p) { Get-ChildItem $p -Recurse -Filter *.lnk -ErrorAction SilentlyContinue | '
            'ForEach-Object { $sc = $ws.CreateShortcut($_.FullName); '
            'Write-Output ($_.BaseName + "`t" + $sc.TargetPath) } } }'
        )
        try:
            r = _sp.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps_code],
                        capture_output=True, timeout=40)
            for line in r.stdout.decode('utf-8', errors='ignore').splitlines():
                if '\t' not in line and chr(9) not in line:
                    continue
                parts = line.split(chr(9))
                if len(parts) >= 2 and parts[1].strip():
                    apps.append({'name': parts[0].strip(), 'path': parts[1].strip(),
                                 'exe': os.path.basename(parts[1].strip()).lower()})
        except Exception:
            pass
        # 2. 注册表已安装应用
        try:
            import winreg
            seen = set()
            for hive, subkey in [
                (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'),
                (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'),
                (winreg.HKEY_CURRENT_USER, r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'),
            ]:
                try:
                    key = winreg.OpenKey(hive, subkey)
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            sk = winreg.EnumKey(key, i)
                            skh = winreg.OpenKey(key, sk)
                            try:
                                name, _ = winreg.QueryValueEx(skh, 'DisplayName')
                                icon, _ = winreg.QueryValueEx(skh, 'DisplayIcon')
                            except Exception:
                                continue
                            exe = ''
                            if icon:
                                exe = os.path.basename(icon.split(',')[0]).lower()
                            if name and (name, exe) not in seen:
                                seen.add((name, exe))
                                apps.append({'name': str(name).strip(), 'path': icon.split(',')[0] if icon else '',
                                             'exe': exe})
                        except Exception:
                            continue
                except Exception:
                    continue
        except Exception:
            pass
        return apps

    def _load_app_index(self):
        """加载/构建应用索引（缓存 24h）"""
        idx_path = os.path.join(BASE_DIR, 'app_index.json')
        try:
            if os.path.exists(idx_path):
                with open(idx_path, encoding='utf-8') as f:
                    data = json.load(f)
                if time.time() - data.get('built_at', 0) < 86400:
                    return data.get('apps', [])
        except Exception:
            pass
        apps = self._build_app_index()
        try:
            self._atomic_write_json(idx_path, {'built_at': time.time(), 'apps': apps}, pretty=False)
        except Exception:
            pass
        return apps

    def _smart_find_app(self, query):
        """智能匹配本地应用：别名→精确→子串→拼音首字母→模糊，返回 (path, name) 或 None"""
        import difflib
        q = query.strip().lower().replace('.exe', '').replace('打开', '').replace('启动', '').replace('运行', '').strip()
        if not q:
            return None
        apps = self._load_app_index()
        if not apps:
            return None

        # 系统自带应用直映射（无快捷方式，直接给 system32 路径）
        sysapps = {
            'notepad': (r'C:\Windows\System32\notepad.exe', '记事本'),
            'calc': (r'C:\Windows\System32\calc.exe', '计算器'),
            'calculator': (r'C:\Windows\System32\calc.exe', '计算器'),
            'paint': (r'C:\Windows\System32\mspaint.exe', '画图'),
            'taskmgr': (r'C:\Windows\System32\Taskmgr.exe', '任务管理器'),
            'control': (r'C:\Windows\System32\control.exe', '控制面板'),
            'mstsc': (r'C:\Windows\System32\mstsc.exe', '远程桌面'),
            'explorer': (r'C:\Windows\explorer.exe', '资源管理器'),
        }
        for at in self.COMMON_ALIASES.values():
            pass
        if q in self.COMMON_ALIASES and self.COMMON_ALIASES[q] in sysapps:
            p2, n2 = sysapps[self.COMMON_ALIASES[q]]
            if os.path.exists(p2):
                return (p2, n2)
        if q in sysapps:
            p2, n2 = sysapps[q]
            if os.path.exists(p2):
                return (p2, n2)

        # 别名展开（如 微信→wechat, 浏览器→edge）
        alias_targets = []
        if q in self.COMMON_ALIASES:
            alias_targets.append(self.COMMON_ALIASES[q])
        # 拼音首字母（wx→微信, qq→QQ, wps）
        pinyin_letters = ''.join([c for c in q if c.isascii() and c.isalpha()]).lower()

        def score(app):
            name = (app.get('name') or '').lower()
            exe = app.get('exe') or ''
            p = (app.get('path') or '').lower()
            # 别名目标精确命中 exe（最强证据）
            for at in alias_targets:
                if at == exe or at + '.exe' == exe:
                    return 100
            # 名称/路径精确
            if q == name or q == exe or q == name.replace(' ', ''):
                return 100
            # 别名出现在 exe/路径
            for at in alias_targets:
                if at in exe or at in p:
                    return 95
            # 别名出现在名称
            for at in alias_targets:
                if at in name:
                    return 85
            if q in exe:
                return 80
            if q in name or name in q:
                return 65
            if pinyin_letters and len(pinyin_letters) >= 2:
                if pinyin_letters == ''.join([c for c in name if c.isascii()]).lower()[:len(pinyin_letters)]:
                    return 75
            return 0

        scored = [(score(a), a) for a in apps]
        scored.sort(key=lambda x: -x[0])
        best_score, best = scored[0] if scored else (0, None)
        if best_score >= 75:
            return (best.get('path') or best.get('name'), best.get('name'))
        # 模糊匹配兜底（difflib）
        names = [a.get('name', '') for a in apps]
        close = difflib.get_close_matches(q, [n.lower() for n in names], n=1, cutoff=0.5)
        if close:
            for a in apps:
                if (a.get('name') or '').lower() == close[0]:
                    return (a.get('path') or a.get('name'), a.get('name'))
        return None

    def _load_aliases(self):
        """从 config.json 加载自定义应用快捷指令别名表"""
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            aliases = cfg.get('app_aliases', {})
            return {str(k).strip().lower(): str(v).strip() for k, v in aliases.items() if str(v).strip()}
        except Exception:
            return {}

    def _smart_open(self, app):
        """智能打开：别名表 → 映射表 → 系统命令 → 开始菜单 → 网址 → 文件路径"""
        import subprocess
        app = app.strip()
        if not app:
            return '没有指定要打开的内容'

        # 0.5 智能本地应用检索（v6.36）：先找电脑上装没装，再谈浏览器
        found = self._smart_find_app(app)
        if found:
            target, display = found
            try:
                target = (target or '').strip()
                if target and target.lower().endswith(('.exe', '.lnk', '.bat', '.cmd')):
                    os.startfile(target)
                elif target and os.path.isdir(target):
                    os.startfile(target)
                elif target and os.path.exists(target):
                    # 非可执行文件（如 .ico/.url）：同目录找 exe 兜底
                    import glob as _glob
                    exe_found = None
                    for pat in ('*.exe', '*.lnk'):
                        cands = _glob.glob(os.path.join(os.path.dirname(target), pat))
                        if cands:
                            exe_found = cands[0]
                            break
                    if exe_found:
                        os.startfile(exe_found)
                    else:
                        _open_shell_target(display)
                else:
                    # 只有名字没有路径（如 UWP）：尝试 start
                    _open_shell_target(display)
                return f'已打开 {display}'
            except Exception as e:
                return f'打开 {display} 失败：{e}'

        # 0. 用户自定义别名表（config.json 的 app_aliases，优先级最高）
        alias_key = app.lower().strip()
        if alias_key in self.app_aliases:
            target = self.app_aliases[alias_key]
            try:
                if os.path.isdir(target):
                    os.startfile(target)
                elif os.path.exists(target):
                    os.startfile(target)
                else:
                    _open_shell_target(target)
                return f'已打开 {app}（{target}）'
            except Exception as e:
                return f'打开 {app} 失败：{e}'

        # 1. 已知应用映射表
        appmap = {
            '记事本': 'notepad.exe', '计算器': 'calc.exe', '画图': 'mspaint.exe',
            'cmd': 'cmd.exe', '命令提示符': 'cmd.exe', 'powershell': 'powershell.exe',
            '任务管理器': 'taskmgr.exe', '控制面板': 'control.exe',
            '资源管理器': 'explorer.exe', '文件管理器': 'explorer.exe',
            'word': 'winword.exe', 'excel': 'excel.exe', 'ppt': 'powerpnt.exe',
            'outlook': 'outlook.exe', 'edge': 'msedge.exe',
            '浏览器': None,  # 特殊处理
        }
        key = app.lower()
        if key in appmap:
            target = appmap[key]
            if target is None:  # 浏览器 → 打开主页
                _open_url('http://www.baidu.com')
                return f'已打开浏览器'
            try:
                subprocess.Popen([target])
                return f'已打开 {app}'
            except Exception:
                pass

        # 2. 常见中文名映射（非精确匹配）
        fuzzy = {
            'pycharm': 'pycharm', 'vscode': 'code', 'vs code': 'code',
            '微信': 'wechat', 'qq': 'qq', '哔哩哔哩': 'bilibili',
            'b站': 'bilibili', 'bilibili': 'bilibili', 'steam': 'steam',
            '网易云': 'cloudmusic', '音乐': 'cloudmusic', 'potplayer': 'potplayer',
        }
        if key in fuzzy:
            target = fuzzy[key]
            # 网站类应用：直接浏览器打开，不尝试 start（避免错误弹窗）
            site_map = {'bilibili': 'https://www.bilibili.com', 'wechat': 'https://weixin.qq.com'}
            if target in site_map:
                _open_url(site_map[target])
                return f'已用浏览器打开 {app}'
            # 桌面应用：尝试 start（查找 PATH / 关联）
            result = 1 if _open_shell_target(target) else 0
            if result == 0:
                return f'已尝试打开 {app}'
            # 失败则用浏览器兜底
            _open_search_url(app)
            return f'已尝试打开 {app}，若失败已用浏览器搜索'

        # 3. 检查是否含网址关键词 → 浏览器打开
        url_keywords = ['http', 'www.', '.com', '.cn', '.net', '.org', 'bilibili', '知乎', '百度']
        if any(k in app.lower() for k in url_keywords) or app in ('bilibili', '哔哩哔哩', 'b站'):
            url = app
            if not app.startswith('http'):
                url = f'https://www.{app}.com' if '.' not in app else f'https://{app}'
            _open_url(url)
            return f'已用浏览器打开 {app}'

        # 4. 尝试 where 查找命令
        try:
            where_result = subprocess.run(['where', app], capture_output=True, text=True, timeout=5)
            if where_result.returncode == 0:
                path = where_result.stdout.strip().split('\n')[0]
                subprocess.Popen([path])
                return f'已打开 {app}'
        except Exception:
            pass

        # 5. 尝试文件路径（存在则用默认程序打开）
        if os.path.exists(app):
            os.startfile(app)
            return f'已打开 {app}'

        # 6. 尝试开始菜单搜索（shell:AppsFolder 或直接 start 尝试）
        try:
            result = _open_shell_target(app)
            if result == 0:
                return f'已尝试打开 {app}'
        except Exception:
            pass

        return f'找不到 {app}，请确认名称'

    # ============ 长期记忆系统（v6.11） ============
    def _load_memory(self):
        """加载 memory.json（事实 + 摘要；数据层拆至 memory_store）"""
        self.memory_facts, self.memory_summaries = load_memory(MEMORY_PATH)

    def _save_memory(self):
        """保存 memory.json（数据层拆至 memory_store）"""
        save_memory(MEMORY_PATH, self.memory_facts, self.memory_summaries)

    # ---------- v6.41 记忆引擎：检索重排 + 自动抽取（memory_engine） ----------
    def _rerank_memories(self, query, candidates):
        """LLM 重排：候选记忆 → 选最相关 top-3（8 选 3 把关，复用 deepseek_client）"""
        try:
            import re as _re
            lines = '\n'.join(f'{i + 1}. {c.get("text", "")}' for i, c in enumerate(candidates))
            prompt = (f'用户问：{query}\n候选记忆：\n{lines}\n'
                      f'请选出与问题最相关的 1-3 条（宁缺毋滥，不相关的不选），'
                      f'按相关度从高到低只输出编号，用逗号分隔。')
            data = json.dumps({'model': self._current_model(),
                               'messages': [{'role': 'user', 'content': prompt}],
                               'max_tokens': 30}).encode()
            resp = chat_completions(self._current_api_key(), data)
            self._record_api_usage(resp)
            nums = [int(n) for n in _re.findall(r'\d+', resp['choices'][0]['message'].get('content') or '')]
            picked = [candidates[i - 1]['id'] for i in nums if 1 <= i <= len(candidates)]
            return picked or [c['id'] for c in candidates[:3]]
        except Exception:
            return [c['id'] for c in candidates[:3]]

    def _maybe_extract_memory(self):
        """低频触发自动抽取：距上次 ≥30 分钟且对话 ≥4 轮"""
        try:
            now = time.time()
            last = getattr(self, '_last_extract_ts', 0)
            if now - last < 1800:
                return
            if len(self.chat_history_msgs) < 4:
                return
            self._last_extract_ts = now
            import threading as _th
            _th.Thread(target=self._extract_worker, daemon=True).start()
        except Exception:
            pass

    def _extract_chat(self, messages, max_tokens):
        """抽取用的 LLM 调用（worker 线程，非流式）"""
        try:
            data = json.dumps({'model': self._current_model(),
                               'messages': messages, 'max_tokens': max_tokens}).encode()
            resp = chat_completions(self._current_api_key(), data)
            self._record_api_usage(resp)
            return resp['choices'][0]['message'].get('content') or ''
        except Exception:
            return ''

    def _extract_worker(self):
        """抽取线程：最近对话 → LLM 提炼事实/事件 → 写回 memory.json / memories.json"""
        try:
            recent = list(self.chat_history_msgs[-8:])
            dialogue = '\n'.join(
                f'{"用户" if m.get("role") == "user" else "桌宠"}: {str(m.get("content", ""))[:150]}'
                for m in recent if m.get('content'))
            existing = '；'.join(str(f.get('content', ''))[:60] for f in self.memory_facts[-10:]
                                 if f.get('status', 'active') == 'active')
            result = extract_memories(self._extract_chat, dialogue, existing)
            changed = False
            for f in result.get('facts', []):
                content = str(f.get('content', '')).strip()
                if content:
                    self.memory_facts, _msg = remember_fact(
                        self.memory_facts, 'add', content, f.get('importance', 3), role='both')
                    changed = True
            for u in result.get('update_facts', []):
                fid = str(u.get('id', ''))
                content = str(u.get('content', '')).strip()
                if fid and content:
                    self.memory_facts, _msg = remember_fact(
                        self.memory_facts, 'update', content, fid=fid, role='both')
                    changed = True
            if changed:
                self._save_memory()
            for e in result.get('events', []):
                title = str(e.get('title', '')).strip()
                if title:
                    try:
                        self.memories.add(self.current, 'event', title,
                                          str(e.get('detail', ''))[:200])
                    except Exception:
                        pass
        except Exception:
            pass

    def _remember_fact(self, action, content='', importance=3, fid='', role='both'):
        """memorize 工具处理（数据逻辑拆至 memory_store.remember_fact，此处持有状态+落盘）"""
        self.memory_facts, msg = remember_fact(
            self.memory_facts, action, content, importance, fid, role)
        self._save_memory()
        return msg

    def _memory_block(self):
        """生成注入 system prompt 的记忆块（拆至 prompt_builder.build_memory_block）"""
        return build_memory_block(self.memory_facts, self.memory_summaries, self.current)

    def _summarize_old(self):
        """旧消息滚动摘要：chat_history_msgs 超 20 条时，最旧 10 条压成摘要"""
        if len(self.chat_history_msgs) <= 20 or not self.ai_enabled:
            return
        try:
            old = self.chat_history_msgs[:10]
            texts = []
            for m in old:
                c = (m.get('content') or '').strip()
                if c and not c.startswith('（'):
                    texts.append(f'{"用户" if m.get("role") == "user" else "桌宠"}: {c[:100]}')
            if not texts:
                self.chat_history_msgs = self.chat_history_msgs[10:]
                return
            # 复用抽取用的 LLM 调用：模型与接口地址均取自模型档案。
            # 原实现裸写 URL 并引用了本作用域不存在的 cur_model，抛出的 NameError
            # 被下方 except 吞掉 → 摘要从不生成、最旧 10 条从不裁剪。
            summary = (self._extract_chat(
                [{'role': 'user',
                  'content': f'把下面的对话压缩成 1-2 句中文摘要（≤120字），只留关键信息：\n' + '\n'.join(texts[-8:])}],
                200) or '').strip()
            if summary:
                self.memory_summaries.append({'content': summary, 'time': __import__('datetime').datetime.now().isoformat(timespec='seconds')})
                if len(self.memory_summaries) > 6:
                    self.memory_summaries = self.memory_summaries[-6:]
                self._save_memory()
            self.chat_history_msgs = self.chat_history_msgs[10:]
        except Exception:
            pass

    def _request_confirm(self, message):
        """跨线程请求用户确认（主线程弹窗），返回 True/False"""
        import threading
        evt = threading.Event()
        result = {'ok': False}
        def ask():
            try:
                from PySide6.QtWidgets import QMessageBox
                is_en = getattr(self, 'language', 'zh') == 'en'
                box = QMessageBox(self)
                box.setWindowTitle(self._t('dlg_confirm'))
                box.setIcon(QMessageBox.Warning)
                box.setText(message)
                box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
                box.setDefaultButton(QMessageBox.No)
                box.button(QMessageBox.Yes).setText(self._t('allow'))
                box.button(QMessageBox.No).setText(self._t('deny'))
                result['ok'] = (box.exec() == QMessageBox.Yes)
            except Exception:
                result['ok'] = False
            evt.set()
        self.confirm_signal.emit(ask)
        evt.wait(timeout=120)
        return result['ok']

    # ============ 记忆管理 UI（v6.12） ============
    def _show_memory(self):
        """查看长期记忆（显示到聊天面板）"""
        active = [f for f in self.memory_facts if f.get('status') == 'active']
        if not active:
            self._append_chat('桌宠', '🧠 还没有长期记忆。对话中告诉我你的偏好/重要信息，我会自动记住')
            return
        active.sort(key=lambda x: -x.get('importance', 3))
        lines = [f'🧠 长期记忆（{len(active)} 条）：']
        for f in active:
            lines.append(f'  ★{f.get("importance", 3)} {f.get("content", "")}')
        self._append_chat('桌宠', '\n'.join(lines))

    def _delete_memory_dialog(self):
        """弹窗选择要删除的记忆"""
        active = [f for f in self.memory_facts if f.get('status') == 'active']
        if not active:
            self._append_chat('桌宠', '🧠 还没有长期记忆可删除')
            return
        items = [f.get('content', '')[:40] for f in active]
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getItem(self, '删除记忆', '选择要遗忘的记忆：', items, 0, False)
        if ok and text:
            for f in active:
                if f.get('content', '')[:40] == text:
                    self._remember_fact('delete', fid=f.get('id', ''))
                    self._append_chat('桌宠', f'🗑 已遗忘：{f.get("content", "")}')
                    return

    def _clear_memory_confirm(self):
        """确认后清空全部记忆"""
        active = [f for f in self.memory_facts if f.get('status') == 'active']
        if not active:
            self._append_chat('桌宠', '🧠 没有需要清空的记忆' if getattr(self, 'language', 'zh') != 'en' else '🧠 No memory to clear')
            return
        from PySide6.QtWidgets import QMessageBox
        is_en = getattr(self, 'language', 'zh') == 'en'
        box = QMessageBox(self)
        box.setWindowTitle(self._t('dlg_clear_mem'))
        box.setIcon(QMessageBox.Warning)
        box.setText(f'确定清空全部 {len(active)} 条长期记忆吗？\n清空后桌宠将不再记得这些信息' if not is_en else f'Clear all {len(active)} memories?\nThe pet will forget this information')
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        box.button(QMessageBox.Yes).setText('清空' if not is_en else 'Clear')
        box.button(QMessageBox.No).setText('取消' if not is_en else 'Cancel')
        if box.exec() == QMessageBox.Yes:
            for f in active:
                self._remember_fact('delete', fid=f.get('id', ''))
            self._save_memory()
            self._append_chat('桌宠', '🧹 长期记忆已全部清空' if not is_en else '🧹 All memories cleared')

    # ============ 全局快捷键（v6.12，Ctrl+Alt+P 呼出） ============
    def _on_global_hotkey(self):
        """全局热键回调：唤出桌宠 + 打开聊天面板"""
        self.show()
        self.raise_()
        self.activateWindow()
        if not self.chat_panel.isVisible():
            self.toggle_chat_panel()
        self.chat_input.setFocus()

    # ============ TODO 待办清单（v6.17） ============
    def _load_todos(self):
        """加载 todos.json"""
        try:
            import json as _j
            if os.path.exists(TODO_PATH):
                self.todos = _j.load(open(TODO_PATH, encoding='utf-8'))
            else:
                self.todos = []
        except Exception:
            self.todos = []

    def _save_todos(self):
        try:
            self._atomic_write_json(TODO_PATH, self.todos)
        except Exception:
            pass

    def _todo_block(self):
        """生成注入 prompt 的待办清单块（拆至 prompt_builder.build_todo_block）"""
        return build_todo_block(self.todos)

    def _manage_todo(self, action, text='', tid=''):
        """待办操作：add/list/done/remove"""
        import datetime
        now = datetime.datetime.now().strftime('%m-%d %H:%M')
        action = (action or 'list').lower()
        if action == 'add':
            if not text.strip():
                return '内容为空'
            self.todos.append({'id': f't{int(datetime.datetime.now().timestamp() * 1000)}',
                               'text': text.strip(), 'done': False, 'created': now})
            self._save_todos()
            return f'已加入待办：{text.strip()}（当前 {len(self.todos)} 项）'
        if action == 'list':
            if not self.todos:
                return '当前没有待办事项'
            return '\n'.join(f'{"✅" if t.get("done") else "⬜"} {t.get("text", "")}' for t in self.todos)
        if action == 'done':
            for t in self.todos:
                if t.get('id') == tid or (text and (text in t.get('text', ''))):
                    t['done'] = True
                    self._save_todos()
                    return f'已完成：{t.get("text", "")}'
            return '未找到对应待办'
        if action == 'remove':
            for t in self.todos[:]:
                if t.get('id') == tid or (text and (text in t.get('text', ''))):
                    self.todos.remove(t)
                    self._save_todos()
                    return f'已删除待办：{t.get("text", "")}'
            return '未找到对应待办'
        return '未知操作（add/list/done/remove）'

    def _open_todo_manager(self):
        """待办管理窗口：添加/勾选完成/删除/清空已完成"""
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
                                       QPushButton, QHeaderView, QLineEdit)
        is_en = getattr(self, 'language', 'zh') == 'en'
        T = self._t
        dlg = QDialog(self)
        dlg.setWindowTitle(T('todo_menu'))
        dlg.resize(540, 420)
        lay = QVBoxLayout(dlg)

        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels([T('todo_status'), T('mem_content'), T('todo_time')])
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.setColumnWidth(0, 70)
        table.setColumnWidth(2, 110)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        lay.addWidget(table, 1)

        def refresh():
            table.setRowCount(0)
            for t in self.todos:
                r = table.rowCount()
                table.insertRow(r)
                table.setItem(r, 0, QTableWidgetItem('✅' if t.get('done') else '⬜'))
                table.setItem(r, 1, QTableWidgetItem(t.get('text', '')))
                table.setItem(r, 2, QTableWidgetItem(t.get('created', '')))

        def toggle_done(row, col):
            if row < len(self.todos):
                self.todos[row]['done'] = not self.todos[row].get('done', False)
                self._save_todos()
                refresh()

        def add_todo():
            txt = inp.text().strip()
            if txt:
                self._manage_todo('add', txt)
                inp.clear()
                refresh()

        def done_selected():
            rows = sorted({i.row() for i in table.selectedIndexes()}, reverse=True)
            for r in rows:
                if 0 <= r < len(self.todos):
                    self.todos[r]['done'] = True
            self._save_todos()
            refresh()

        def del_selected():
            rows = sorted({i.row() for i in table.selectedIndexes()}, reverse=True)
            for r in rows:
                if 0 <= r < len(self.todos):
                    self.todos.pop(r)
            self._save_todos()
            refresh()

        def clear_done():
            self.todos = [t for t in self.todos if not t.get('done')]
            self._save_todos()
            refresh()

        # 输入行
        top = QHBoxLayout()
        inp = QLineEdit()
        inp.setPlaceholderText(T('todo_placeholder'))
        inp.returnPressed.connect(add_todo)
        b_add = QPushButton(T('todo_add'))
        b_add.clicked.connect(add_todo)
        top.addWidget(inp, 1)
        top.addWidget(b_add)
        lay.addLayout(top)

        # 操作行
        bottom = QHBoxLayout()
        b_done = QPushButton(T('todo_done'))
        b_done.clicked.connect(done_selected)
        b_del = QPushButton(T('todo_del'))
        b_del.clicked.connect(del_selected)
        b_clear = QPushButton(T('todo_clear_done'))
        b_clear.clicked.connect(clear_done)
        b_close = QPushButton('✕')
        b_close.clicked.connect(dlg.close)
        bottom.addWidget(b_done)
        bottom.addWidget(b_del)
        bottom.addWidget(b_clear)
        bottom.addStretch(1)
        bottom.addWidget(b_close)
        lay.addLayout(bottom)

        table.cellDoubleClicked.connect(toggle_done)
        refresh()
        dlg.exec()

    # ============ AI 状态预判（v6.19） ============
    @staticmethod
    def _guess_status(text):
        """按用户消息关键词预判 AI 状态（拆至 prompt_builder.guess_status）"""
        return guess_status(text)

    def _web_search(self, query):
        """Tavily 联网搜索：返回格式化结果给 LLM；未配置 key 时返回提示"""
        if not getattr(self, 'search_api_key', ''):
            return '（未配置搜索 API key：请在 设置 → 联网搜索 中填写 Tavily API key 后重试）'
        try:
            import urllib.request as _ur
            payload = json.dumps({
                'api_key': self.search_api_key,
                'query': query,
                'max_results': 5,
                'search_depth': 'basic',
            }).encode()
            req = _ur.Request('https://api.tavily.com/search', data=payload,
                              headers={'Content-Type': 'application/json'})
            with _ur.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode())
            results = data.get('results', [])
            if not results:
                return '（搜索无结果）'
            lines = []
            for r in results[:5]:
                title = r.get('title', '')
                url = r.get('url', '')
                content = (r.get('content') or '')[:200]
                lines.append(f'- {title} | {url}\n  {content}')
            return '\n'.join(lines)
        except Exception as e:
            return f'（搜索失败：{e}）'

    # ---------- AI 自我管理（阶段1+2：改配置/读自己代码） ----------
    CONFIG_WHITELIST = ('personality', 'reply_style', 'max_tokens', 'city', 'language',
                        'active_chat', 'display_mode', 'live2d_model', 'sedentary_minutes',
                        'api_prices')

    def _search_code(self, keyword, max_results=20):
        """薄委托（实现见 pet_selfcode.search_code，v6.51 搬出）"""
        return search_code(keyword, max_results, base_dir=BASE_DIR)


    def _write_config_tool(self, key, value):
        """AI 修改白名单配置（敏感字段禁止，改完热加载）"""
        key = (key or '').strip()
        value = (value or '').strip()
        if key not in self.CONFIG_WHITELIST:
            return f'（字段 {key} 不在可修改白名单：{"/".join(self.CONFIG_WHITELIST)}）'
        # 值类型校验
        if key in ('max_tokens', 'sedentary_minutes'):
            try:
                value = str(clamp_tokens(value) if key == 'max_tokens' else max(5, min(int(value), 240)))
            except ValueError:
                return '（需要数字）'
        if key == 'reply_style' and value not in ('short', 'normal', 'detailed'):
            return '（reply_style 需为 short/normal/detailed）'
        if key == 'language' and value not in ('zh', 'en'):
            return '（language 需为 zh/en）'
        if key == 'display_mode' and value not in ('static', 'live2d'):
            return '（display_mode 需为 static/live2d）'
        if key == 'active_chat':
            value = 'true' if value.lower() in ('true', '1', '开', 'on', 'yes') else 'false'
        if key == 'api_prices':
            # JSON 对象：{"模型名": {"input": x, "cache": y, "output": z}}（每百万 token 单价）
            try:
                parsed = json.loads(value)
            except Exception:
                return '（api_prices 需要合法 JSON，如 {"deepseek-flash":{"input":1,"output":2}}）'
            if not isinstance(parsed, dict):
                return '（api_prices 需要 JSON 对象）'
            for k, v in parsed.items():
                if not isinstance(v, dict):
                    return f'（模型 {k} 的价格需要对象，如 {{"input":1,"output":2}}）'
            value = json.dumps(parsed, ensure_ascii=False)
        if self._save_cfg_value(key, value):
            # 热加载
            try:
                if key == 'personality':
                    self.personality = value
                elif key == 'reply_style':
                    self.reply_style = value
                elif key == 'max_tokens':
                    self.max_tokens = int(value)
                elif key == 'city':
                    self.pet_city = value
                elif key == 'language':
                    QTimer.singleShot(0, lambda v=value: self._set_language(v))  # GUI 回主线程（v6.25.1）
                elif key == 'active_chat':
                    self.active_chat_enabled = value == 'true'
                elif key == 'display_mode':
                    QTimer.singleShot(0, lambda v=value: self._set_display_mode(v))  # GUI 回主线程（v6.25.1）
                elif key == 'api_prices':
                    # 热加载价格（空对象 = 恢复出厂价）；经 api_stats 统一处理，
                    # 有模型档案时写进档案，避免与内置表各存一份
                    self.api_stats.reload_prices()
                elif key == 'live2d_model':
                    self._set_live2d_model(value)
                elif key == 'sedentary_minutes':
                    self.sedentary_minutes = int(value)
            except Exception:
                pass
            return f'✅ 已修改 {key}={value}'
        return '（写入失败）'

    def _write_file_tool(self, filename, content):
        """薄委托（实现见 pet_selfcode.write_file_tool）"""
        return write_file_tool(filename, content, base_dir=BASE_DIR)

    def _edit_own_code(self, old_text, new_text, start_line=None, end_line=None,
                      file='desktop_pet.py'):
        """薄委托（实现见 pet_selfcode.edit_own_code）"""
        return edit_own_code(old_text, new_text, start_line, end_line, file,
                             base_dir=BASE_DIR)

    # v6.51：工具分发改成注册表——原先 29 个 if/elif 分支串在一个 169 行的方法里，
    # 加一个工具要读懂整条链子。现在：注册表一行 + 一个 _tool_xxx 小方法。
    _TOOL_HANDLERS = {
        'calculate': '_tool_calculate',
        'control_volume': '_tool_control_volume',
        'edit_own_code': '_tool_edit_own_code',
        'get_system_info': '_tool_get_system_info',
        'get_time': '_tool_get_time',
        'install_plugin': '_tool_install_plugin',
        'kill_process': '_tool_kill_process',
        'list_plugins': '_tool_list_plugins',
        'list_processes': '_tool_list_processes',
        'lock_screen': '_tool_lock_screen',
        'manage_todo': '_tool_manage_todo',
        'memorize': '_tool_memorize',
        'offer_choices': '_tool_offer_choices',
        'open_app': '_tool_open_app',
        'query_weather': '_tool_query_weather',
        'read_clipboard': '_tool_read_clipboard',
        'read_file': '_tool_read_file',
        'run_powershell': '_tool_run_powershell',
        'schedule_followup': '_tool_schedule_followup',
        'search_code': '_tool_search_code',
        'search_files': '_tool_search_files',
        'set_reminder': '_tool_set_reminder',
        'set_theme': '_tool_set_theme',
        'skill_run': '_tool_skill_run',
        'uninstall_plugin': '_tool_uninstall_plugin',
        'web_search': '_tool_web_search',
        'write_clipboard': '_tool_write_clipboard',
        'write_config': '_tool_write_config',
        'write_file': '_tool_write_file',
    }

    def _execute_tool(self, name, args):
        """执行 AI 请求的工具，返回结果文本"""
        try:
            if name.startswith('mcp_'):
                # v6.20 MCP 工具转发：mcp_<server>_<tool>
                return self.mcp.call_tool(name, args)
            if name in self.plugin_mgr.tool_names():
                # v6.21 插件工具转发
                return self.plugin_mgr.handle_tool(name, args)
            handler = self._TOOL_HANDLERS.get(name)
            if handler is None:
                return f'未知工具 {name}'
            return getattr(self, handler)(args)
        except Exception as e:
            return f'工具执行失败：{e}'

    def _tool_install_plugin(self, args):
        # v6.21 AI 自主安装插件（校验+写入+热加载）
        _, msg = self.plugin_mgr.install(
            args.get('name', ''),
            args.get('meta') or {},
            args.get('entry_content'),
            args.get('rules_content'))
        return msg

    def _tool_uninstall_plugin(self, args):
        _, msg = self.plugin_mgr.uninstall(args.get('name', ''))
        return msg

    def _tool_list_plugins(self, args):
        return self.plugin_mgr.status_text()

    def _tool_set_theme(self, args):
        # v6.23 主题切换（default / theme 插件名）；v6.25.1 GUI 应用回主线程（防跨线程崩溃）
        tname = str(args.get('name') or 'default').strip()
        available = ['default'] + [str(x) for x in self.plugin_mgr.theme_names()]
        if tname not in available:
            return f'（可用主题：{"、".join(available)}）'
        # 数据部分（线程安全）立即更新（与右键菜单入口共用同一方法）
        self._set_theme_data(tname)
        # GUI 部分回主线程执行（QTimer.singleShot 线程安全）
        QTimer.singleShot(0, self._apply_theme)
        self._save_cfg_value('theme', tname)
        return f'✅ 已切换主题：{tname}（样式即将生效）'

    def _tool_skill_run(self, args):
        # v6.23 复合技能：返回步骤清单，AI 逐步执行
        sname = str(args.get('name') or '').strip()
        steps = self.plugin_mgr.skill_steps(sname)
        if steps is None:
            avail = [str(x) for x in self.plugin_mgr.skill_names()]
            return f'（未找到技能 {sname}；可用技能：{"、".join(avail) or "无"}）'
        return steps

    def _tool_open_app(self, args):
        app = args.get('name', '')
        return self._smart_open(app)

    def _tool_get_time(self, args):
        import datetime
        return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    def _tool_web_search(self, args):
        return self._web_search(args.get('query', ''))

    def _tool_search_code(self, args):
        return search_code(args.get('keyword', ''), base_dir=BASE_DIR)

    def _tool_read_file(self, args):
        return read_own_file(args.get('path', ''), BASE_DIR, args.get('start_line'), args.get('end_line'))

    def _tool_edit_own_code(self, args):
        return edit_own_code(args.get('old_text', ''), args.get('new_text', ''),
                                   args.get('start_line'), args.get('end_line'),
                                   args.get('file', 'desktop_pet.py'), base_dir=BASE_DIR)

    def _tool_write_file(self, args):
        return write_file_tool(args.get('filename', ''), args.get('content', ''), base_dir=BASE_DIR)

    def _tool_write_config(self, args):
        return self._write_config_tool(args.get('key', ''), args.get('value', ''))

    def _tool_calculate(self, args):
        return calculate_expr(args.get('expr', ''))

    def _tool_set_reminder(self, args):
        sec = max(1, min(int(args.get('seconds', 60)), 86400))
        text = args.get('text', '提醒')
        self._add_reminder(sec, text)
        return f'已设置 {sec} 秒后提醒：{text}'

    def _tool_lock_screen(self, args):
        ctypes.windll.user32.LockWorkStation()
        return '已锁定屏幕'

    def _tool_offer_choices(self, args):
        # v6.30 情感选项：支持字符串或 {text, affect} 对象，返回特殊标记
        raw = args.get('choices') or []
        choices = []
        for c in raw:
            if isinstance(c, dict):
                t = str(c.get('text') or '').strip()[:20]
                if t:
                    choices.append({'text': t, 'affect': c.get('affect') or c.get('affection')})
            else:
                t = str(c).strip()[:20]
                if t:
                    choices.append({'text': t, 'affect': None})
        if len(choices) < 2:
            return '需要至少 2 个选项'
        self._pending_choices = choices[:3]
        return '__CHOICES__'

    def _tool_query_weather(self, args):
        # 真正联网查天气（wttr.in，网络层拆至 tools_executor.query_weather）
        return query_weather(args.get('city', '') or self.pet_city)

    def _tool_run_powershell(self, args):
        cmd = args.get('command', '')
        blocked = _check_dangerous(cmd)
        if blocked:
            # 危险操作改为询问用户：允许才执行
            if self._request_confirm(f'检测到危险操作，是否允许执行？\n\n{cmd}'):
                return _run_ps(cmd, skip_check=True)
            return '用户拒绝了危险操作，未执行'
        return _run_ps(cmd)

    def _tool_memorize(self, args):
        return self._remember_fact(args.get('action', 'add'), args.get('content', ''), args.get('importance', 3), args.get('id', ''), args.get('role', 'both'))

    def _tool_manage_todo(self, args):
        return self._manage_todo(args.get('action', 'list'), args.get('text', ''), args.get('id', ''))

    def _tool_schedule_followup(self, args):
        sec = max(600, min(int(args.get('seconds', 3600)), 21600))
        reason = (args.get('reason', '关心一下') or '').strip()
        self._add_reminder(sec, reason, rtype='followup')
        return f'已安排 {sec} 秒后回访：{reason}'

    def _tool_read_clipboard(self, args):
        txt = _read_clipboard_text()
        if txt is None:
            return '剪贴板没有文本内容'
        return f'剪贴板内容（{len(txt)} 字符）：\n{txt[:1000]}' + ('…（过长已截断）' if len(txt) > 1000 else '')

    def _tool_write_clipboard(self, args):
        txt = args.get('text', '')
        if not txt:
            return '没有可写入的内容'
        return '已写入剪贴板，用户可直接粘贴' if _write_clipboard_text(txt) else '剪贴板写入失败'

    def _tool_get_system_info(self, args):
        return _run_ps('$os = Get-CimInstance Win32_OperatingSystem; $cpu = Get-CimInstance Win32_Processor; $cs = Get-CimInstance Win32_ComputerSystem; "系统: $($os.Caption) $($os.Version)"; "CPU: $($cpu.Name)"; "内存: $([math]::Round(($os.TotalVisibleMemorySize/1MB),1)) GB 总量, $([math]::Round(($os.FreePhysicalMemory/1MB),1)) GB 可用"; "开机: $($os.LastBootUpTime)"; "用户: $($cs.UserName)"')

    def _tool_list_processes(self, args):
        n = int(args.get('n', 10))
        return _run_ps(f'Get-Process | Sort-Object WS -Descending | Select-Object -First {n} Name, Id, @{{N="内存MB";E={{[math]::Round($_.WS/1MB)}}}} | Format-Table -AutoSize | Out-String -Width 100')

    def _tool_kill_process(self, args):
        proc = args.get('name', '').replace('.exe', '')
        protected = {'system', 'svchost', 'explorer', 'winlogon', 'csrss', 'services', 'dwm', 'pythonw', 'python', 'autoclaw'}
        if proc.lower() in protected:
            return f'{proc} 是系统/关键进程，已保护，不能结束'
        if not _is_safe_process_name(proc):
            return f'进程名 {proc} 含非法字符，已拒绝（防命令注入）'
        # skip_check：进程名已过白名单校验（仅字母数字._- 空格），
        # 且 Stop-Process 是本工具的既定行为，不是 AI 自由拼串
        return _run_ps('Get-Process -Name ' + _ps_quote(proc) +
                       ' -ErrorAction SilentlyContinue | Stop-Process; '
                       f'if ($?) {{ "已结束进程 {proc}" }} else {{ "未找到进程 {proc}" }}',
                       skip_check=True)

    def _tool_control_volume(self, args):
        action = (args.get('action') or '').lower()
        if action == 'set':
            pct = int(args.get('percent', 50))
            pct = max(0, min(100, pct))
            return _volume_ps(f'[Volume]::SetPercent({pct}); "已精确设置音量 {pct}%"')
        if action in ('mute', 'unmute'):
            flag = 'true' if action == 'mute' else 'false'
            return _volume_ps(f'[Volume]::SetMuted({flag}); "已{"静音" if action == "mute" else "取消静音"}"')
        if action in ('up', 'down'):
            steps = max(1, min(int(args.get('steps', 5)), 100))
            op = '+' if action == 'up' else '-'
            return _volume_ps(f'$cur = [Volume]::GetPercent(); $new = [math]::Max(0, [math]::Min(100, $cur {op} {steps})); [Volume]::SetPercent($new); "音量 $cur% → $new%"')
        return '音量操作只能是 set/up/down/mute/unmute'

    def _tool_search_files(self, args):
        fname = (args.get('name') or '').strip()
        fpath = (args.get('path') or os.path.expanduser('~')).strip()
        if not fname:
            return '请提供文件名关键词'
        cmd = ('Get-ChildItem -LiteralPath ' + _ps_quote(fpath) +
               ' -Recurse -Filter ' + _ps_quote('*' + fname + '*') +
               ' -File -ErrorAction SilentlyContinue '
               '| Select-Object -First 10 FullName | Out-String -Width 200')
        result = _run_ps(cmd, timeout=12)
        if '（' in result and 'Error' in result:
            return result
        return result if result and '（无输出' not in result else f'没找到包含 "{fname}" 的文件'

    # ================= 窄接口（v6.51：为"搬模块"重构解耦测试而加） =================
    # 回归测试原先直接读写宿主的私有属性（_stream_text / _thinking_label / api_stats /
    # current …），这会让任何一次内部改名都变成"测试大面积变红"，重构寸步难行。
    # 这里把测试与外部模块真正需要的状态收敛成五个入口：读用 snapshot()/ui_probe()，
    # 写用 set_state()（白名单键，写错键名直接报错，避免悄悄写坏内部状态）。

    def snapshot(self):
        """只读状态快照（对外契约）"""
        return {
            'char': self.current,
            'model': self._current_model(),
            'endpoint': self._current_endpoint(),
            'language': getattr(self, 'language', 'zh'),
            'max_tokens': getattr(self, 'max_tokens', None),
            'temperature': getattr(self, 'temperature', None),
            'theme': dict(getattr(self, 'theme', {}) or {}),
            'current_theme': getattr(self, 'current_theme', 'default'),
            'edge_mode': getattr(self, '_edge_mode', 'peek'),
            'display_mode': getattr(self, 'display_mode', 'static'),
            'personality': getattr(self, 'personality', ''),
            'reply_style': getattr(self, 'reply_style', 'normal'),
            'active_care': bool(getattr(self, 'active_chat_enabled', False)),
            'ai_enabled': bool(getattr(self, 'ai_enabled', False)),
            'chat_msgs': list(getattr(self, 'chat_history_msgs', []) or []),
            'memory_summaries': list(getattr(self, 'memory_summaries', []) or []),
            'api_stats': getattr(self, 'api_stats', None),
        }

    _SET_STATE_KEYS = anim.SET_STATE_KEYS  # 白名单已搬至 pet_anim（批 4）

    def set_state(self, **kw):
        """受控写入口：只接受白名单键（写错立刻报错，不静默写坏状态）
        （实现已搬至 pet_anim.set_state / SET_STATE_KEYS）"""
        return anim.set_state(self, **kw)
    def ui_probe(self):
        """UI 探针（只读）：流式/思考/状态行/选项按钮的可见状态"""
        def _txt(w):
            try:
                return w.text() if w is not None else None
            except Exception:
                return None
        bubble = getattr(self, '_chat_type_bubble', None)
        btns = []
        if bubble is not None:
            try:
                btns = [b.text() for b in bubble.findChildren(QPushButton)]
            except Exception:
                btns = []
        lbl = getattr(self, '_thinking_label', None)
        return {
            'stream_text': getattr(self, '_stream_text', ''),
            'thinking_text': _txt(lbl),
            'thinking_hidden': bool(lbl.isHidden()) if lbl is not None else True,
            'status_widget': getattr(self, '_status_widget', None) is not None,
            'bubble_text': _txt(bubble),
            'choice_buttons': btns,
        }

    def ui_clear_handles(self):
        """测试用：清空流式/思考区控件句柄（模拟新一轮对话开始前的状态）"""
        self._chat_type_bubble = None
        self._thinking_label = None
        self._stream_label = None

    def ui_thinking_toggle(self):
        """测试用：思考区折叠按钮句柄（点它验证折叠/展开）"""
        return getattr(self, '_thinking_toggle', None)

    def _ai_worker(self, text):
        """后台线程：调用 DeepSeek API（支持 function calling 循环）"""
        import urllib.request
        import json as jsonlib

        def _post(data, status_zh, status_en):
            """API 请求（网络层已拆至 deepseek_client，此处薄封装：注入 key/语言/状态信号/用量记录）"""
            is_en = getattr(self, 'language', 'zh') == 'en'
            resp = chat_completions(
                self._current_api_key(), data,
                status_cb=lambda s: self.ai_status_signal.emit(s),
                status_zh=status_zh, status_en=status_en, is_en=is_en,
                endpoint=self._current_endpoint(),
            )
            self._record_api_usage(resp)
            return resp

        def _post_stream(data, status_zh, status_en):
            """SSE 流式（网络层已拆至 deepseek_client，薄封装）"""
            is_en = getattr(self, 'language', 'zh') == 'en'
            yield from stream_chat_completions(
                self._current_api_key(), data,
                status_cb=lambda s: self.ai_status_signal.emit(s),
                status_zh=status_zh, status_en=status_en, is_en=is_en,
                endpoint=self._current_endpoint(),
            )

        try:
            # v6.43：记录本次任务代次（用于强制停止判断）
            self._cur_gen = getattr(self, '_ai_generation', 0)
            # v6.43 fix：闭合悬空任务——上次中断遗留的 user 无 assistant 回复，
            # 不闭合则下次对话 AI 会误继续执行旧任务（如：卡住的"找文件夹"在你说 evening 时复活）
            self._close_pending_user_msg()
            # v6.40 fix：用户消息立即入历史并保存（AI 回复中断/进程退出也不丢用户说的话）
            self.chat_history_msgs.append({'role': 'user', 'content': text})
            self._save_chat_memory()
            # 旧消息超 20 条 → 先滚动摘要（不阻塞主流程）
            self._summarize_old()
            # 意图预判：秒出状态提示（猜测，工具确认后覆盖）
            gs = self._guess_status(text)
            self.ai_status_signal.emit(gs[1] if getattr(self, 'language', 'zh') == 'en' else gs[0])
            # 上下文：最近 10 条 + 当前消息
            ctx = self.chat_history_msgs[-30:] + [{'role': 'user', 'content': text}]
            # 根据配置生成回复风格提示
            style_hint = {
                'short': '回复尽量简短（一两句话以内）。',
                'detailed': '分析类问题可以详细回答，允许用列表/表格，不必受简短限制。',
                'normal': '回答简短可爱，但分析类问题可以稍详细。',
            }.get(getattr(self, 'reply_style', 'normal'), '回答简短可爱。')
            # 长期记忆注入（v6.41：core + 按问题检索相关记忆）
            mem = self._memory_block()
            try:
                # BM25 粗筛 + LLM 重排 top-3（memory_engine）
                rel = search_memory(self.memory_facts, text, top_k=3, rerank=self._rerank_memories)
                if rel:
                    rel_block = '\n'.join(f'★{c.get("importance", 3)} {c["text"]}' for c in rel)
                    mem = (rel_block + '\n\n' + mem) if mem else rel_block
            except Exception:
                pass
            mem_hint = f'\n\n【你的长期记忆】\n{mem}' if mem else ''
            mem_rule = '\n当你发现用户的重要偏好/个人事实/任务目标时，调用 memorize 工具记住它；用户明确说"忘了/不要记住"时用 memorize 删除对应记忆。' if mem else '\n记忆规则：当你发现用户的重要偏好/个人事实/任务目标时，调用 memorize 工具记住它。'
            # 插件规则注入（v6.21：rules 类插件内容拼进 system prompt）
            plugin_rules = self.plugin_mgr.rules_text()
            plugin_rules_hint = f'\n\n【插件规则】\n{plugin_rules}' if plugin_rules else ''
            # 待办清单注入
            todo_block = self._todo_block()
            todo_hint = f'\n\n【待办清单】\n{todo_block}' if todo_block else ''
            cur_model = self._current_model()
            # 语言指示：AI 回复语言跟随配置
            lang_hint = self._t('lang_hint')
            # v6.30 好感度：人设阶段 + 最近回忆注入（动态随好感度进化）
            affection_hint = ''
            try:
                _stage_t = self.affection.stage_prompt(self.current)
                _mem_t = self.memories.prompt_hint(self.current)
                if _stage_t or _mem_t:
                    affection_hint = '\n\n【关系与回忆（随好感度动态进化）】' + f'\n{_stage_t}' + (_mem_t or '')
            except Exception:
                affection_hint = ''
            # 角色身份锚定：名字优先级 系统设定 > 记忆中的角色命名
            char_name = CHARACTERS[self.current]['name']
            role_anchor = f'你是{char_name}（角色：{self.current}，模型：{cur_model}）。回答"你是谁"时先明确你是{char_name}（{self.current}）；如果长期记忆中有用户给你起的名字（如小蓝/大蓝），按角色对应使用（只认与你当前角色匹配的名字），不要混用其他角色的名字。'
            messages = [
                {'role': 'system', 'content': build_system_prompt(
                    CHARACTERS[self.current]['name'], self.current, cur_model, self.personality,
                    style_hint, lang_hint, mem_hint, todo_hint, mem_rule, plugin_rules_hint, affection_hint)},
            ] + ctx

            # 最多 5 轮工具调用；空回复自动重试（防截断/空content）
            final_reply = None
            empty_retries = 0
            for _ in range(5):
                # v6.43：被新任务取代或 /stop → 静默退出（不 emit 内容）
                if getattr(self, '_ai_generation', 0) != getattr(self, '_cur_gen', -1):
                    return
                # 请求阶段：覆盖预判为确定状态；v6.40 真流式（SSE）
                self.ai_status_signal.emit('正在思考…' if getattr(self, 'language', 'zh') != 'en' else 'Thinking…')
                data = jsonlib.dumps({
                    'model': cur_model,
                    'messages': messages,
                    'tools': AI_TOOLS + self.mcp.tool_schemas() + self.plugin_mgr.tool_schemas(),  # v6.20/21 动态合并 MCP+插件工具
                    'max_tokens': getattr(self, 'max_tokens', 1000),
                    'stream': True,
                    'stream_options': {'include_usage': True},  # v6.40 fix：流式返回 usage（api_stats 统计）
                    'temperature': getattr(self, 'temperature', 1.0),
                }).encode()
                self.stream_done_signal.emit()  # 上一轮流式收尾（防残留）
                full = None
                for evt, val in _post_stream(data, '正在思考…', 'Thinking…'):
                    if evt == 'reasoning':
                        self.reasoning_signal.emit(val)
                    elif evt == 'content':
                        self.stream_signal.emit(val)
                    elif evt == 'done':
                        full = val
                if full is None:
                    raise RuntimeError('流式响应为空')
                # 记录 API 用量（v6.40 fix：stream_options.include_usage 后流式响应带 usage）
                if full.get('usage'):
                    try:
                        self._record_api_usage({'usage': full['usage']}, fallback_model=cur_model)
                    except Exception:
                        pass
                msg = {
                    'role': 'assistant',  # v6.40 fix：缺 role 导致工具调用后第二轮请求 400（DeepSeek 报 role 错误）
                    'content': full.get('content') or '',
                    'tool_calls': full.get('tool_calls'),
                    'reasoning_content': full.get('reasoning_content') or '',
                }
                self.stream_done_signal.emit()
                messages.append(msg)

                # 检查是否有工具调用
                tool_calls = msg.get('tool_calls') or []
                content = (msg.get('content') or '').strip()
                if not tool_calls:
                    if content:
                        final_reply = content
                        break
                    # content 为空：重试（不带工具强制纯文本回复）
                    if empty_retries < 2:
                        empty_retries += 1
                        data2 = jsonlib.dumps({
                            'model': cur_model,
                            'messages': messages[:-1] + [{'role': 'user', 'content': '请用简短中文回复上一条消息（不要调用工具）'}],
                            'max_tokens': 500,
                        }).encode()
                        result2 = _post(data2, '正在思考…', 'Thinking…')
                        final_reply = (result2['choices'][0]['message'].get('content') or '').strip() or '（我刚才卡壳了，换个说法再问我一次？）'
                        break
                    final_reply = '（我刚才卡壳了，换个说法再问我一次？）'
                    break

                # 执行工具
                for tc in tool_calls:
                    fn = tc['function']
                    name = fn['name']
                    args = jsonlib.loads(fn.get('arguments') or '{}')
                    is_en = getattr(self, 'language', 'zh') == 'en'
                    st = TOOL_STATUS.get(name, (f'正在执行 {name}', f'Running {name}'))
                    self.ai_status_signal.emit((st[1] if is_en else st[0]) + '…')
                    result_text = self._execute_tool(name, args)
                    if result_text == '__CHOICES__':
                        # v6.30 情感选项：保留 AI 简短正文，暂停对话流等用户点击
                        final_reply = (msg.get('content') or '').strip()
                        self._choices_requested = True
                        break
                    messages.append({
                        'role': 'tool',
                        'tool_call_id': tc['id'],
                        'content': result_text,
                    })
                if getattr(self, '_choices_requested', False):
                    break

            if final_reply is None:
                # 工具轮次耗尽但没生成文本回复：强制不带工具重试一次
                self.ai_status_signal.emit('正在整理结果…' if getattr(self, 'language', 'zh') != 'en' else 'Preparing result…')
                try:
                    data3 = jsonlib.dumps({
                        'model': cur_model,
                        'messages': messages + [{'role': 'user', 'content': '请用简短中文总结一下刚才的处理结果（不要调用工具）'}],
                        'max_tokens': 300,
                    }).encode()
                    result3 = _post(data3, '正在整理结果…', 'Preparing result…')
                    final_reply = (result3['choices'][0]['message'].get('content') or '').strip()
                except Exception:
                    final_reply = None
                if not final_reply:
                    final_reply = '（刚才分析到一半走神了，换个问法再试一次？）'

            # 保存到对话记忆（占位/错误回复不存；user 消息已在开头保存，此处只存 assistant）
            if final_reply and not final_reply.startswith('（'):
                # v6.40 fix：上下文存剥标签后的回复（原始含[emotion:xxx]会污染上下文+被AI模仿输出）
                self.chat_history_msgs.append({'role': 'assistant', 'content': self._strip_emotion_tags(final_reply)[0]})
            # v6.30 好感度：对话完成事件（占位/错误回复不计）
            if final_reply and not final_reply.startswith('（'):
                try:
                    self._handle_affection(self.affection.trigger(self.current, 'chat'))
                except Exception:
                    pass
            if getattr(self, '_ai_generation', 0) != getattr(self, '_cur_gen', -1):
                return  # v6.43：已被新任务取代，静默丢弃本次回复
            self.ai_reply_signal.emit(final_reply)
            # v6.41 自动记忆抽取（低频：间隔 30 分钟且 ≥4 轮对话）
            try:
                self._maybe_extract_memory()
            except Exception:
                pass
        except Exception as e:
            # 400 等 HTTP 错误：显示响应体中的具体原因（DeepSeek error.message）
            try:
                import urllib.error as _ue
                if isinstance(e, _ue.HTTPError):
                    body = e.read().decode('utf-8', 'replace')
                    detail = body
                    try:
                        detail = jsonlib.loads(body).get('error', {}).get('message') or body[:200]
                    except Exception:
                        pass
                    self.ai_reply_signal.emit(f'（AI 出错了：HTTP {e.code} — {detail}）')
                else:
                    self.ai_reply_signal.emit(f'（AI 出错了：{e}）')
            except Exception:
                self.ai_reply_signal.emit(f'（AI 出错了：{e}）')
        finally:
            # v6.43b：仅当代任务清 busy，然后自动执行队列下一任务（FCFS）
            if getattr(self, '_ai_generation', 0) == getattr(self, '_cur_gen', -1):
                self._ai_busy = False
                self._cur_task_text = None
                try:
                    self._refresh_task_sidebar()
                except Exception:
                    pass
                self._next_task()

    EMOTION_STATE_MAP = {
        'happy': 'happy', 'excited': 'excited', 'calm': 'idle',
        'thinking': 'thinking', 'sleep': 'sleep', 'tired': 'sleep',
        'shy': 'shy', 'angry': 'angry', 'sad': 'sad', 'cry': 'sad',
    }
    EMOTION_EMOJI_MAP = {
        'happy': '😊', 'excited': '🎉', 'calm': '😌',
        'thinking': '🤔', 'sleep': '💤', 'tired': '😪',
        'shy': '😳', 'angry': '😠', 'sad': '😢', 'cry': '😭',
    }

    @staticmethod
    def _strip_emotion_tag(text):
        """剥离文本中的 [emotion:xxx] / [emotion=xxx] 标签，返回 (剥离后的文本, 情绪名或None)
        （实现已搬至 pet_bubble.strip_emotion_tag）"""
        return pb.strip_emotion_tag(text)
    def _apply_emotion(self, emotion):
        """应用情绪：切立绘 + emoji 气泡 + 定时恢复（10 秒，可重启不叠加）"""
        if self.sleeping:
            return  # 睡觉时不切情绪立绘（AI 回复照常显示，但立绘保持睡眠图）
        target_state = self.EMOTION_STATE_MAP.get(emotion)
        if not target_state:
            return
        self._show_state_image(target_state)
        self.show_emotion(self.EMOTION_EMOJI_MAP.get(emotion, '✨'), 2000)
        if self._emotion_restore_timer is None:
            self._emotion_restore_timer = QTimer(self)
            self._emotion_restore_timer.setSingleShot(True)
            self._emotion_restore_timer.timeout.connect(self._restore_state_after_emotion)
        self._emotion_restore_timer.start(5000)  # 表情持续 5 秒后恢复 idle

    # ---------- v6.40 真流式渲染（思考+正文同卡片，AutoClaw 风格） ----------
    def _chat_type_stream_begin(self):
        """流式渲染开始：创建气泡（思考折叠区 + 正文流式区）"""
        import datetime as _dt
        ts = _dt.datetime.now().strftime('%m-%d %H:%M')
        self._remove_status_line()
        self._chat_type_bubble, self._chat_type_content = self._new_bubble('桌宠', ts, is_user=False, text='')
        # 思考折叠区（同卡片顶部，AutoClaw 风格）
        try:
            head = self._chat_type_bubble.layout().itemAt(0).layout()
            thinking_toggle = QPushButton('💭 思考过程 ▼')
            thinking_toggle.setStyleSheet(
                'QPushButton { background:transparent; color:#7a8aa0; border:none;'
                ' font-size:11px; padding:0; text-align:left; }'
                'QPushButton:hover { color:#9fd0ff; }')
            thinking_toggle.setCursor(Qt.PointingHandCursor)
            thinking_toggle._collapsed = False
            def _toggle():
                # v6.40 fix：闭包捕获本气泡局部变量（旧代码引用 self._thinking_* 最新值，
                # 导致多轮对话后旧气泡的折叠按钮操作的是最新气泡——旧对话无法折叠）
                collapsed = not getattr(thinking_toggle, '_collapsed', False)
                thinking_toggle._collapsed = collapsed
                if thinking_label is not None:
                    thinking_label.setVisible(not collapsed)
                thinking_toggle.setText('💭 思考过程 ▶' if collapsed else '💭 思考过程 ▼')
            thinking_toggle.clicked.connect(_toggle)
            head.insertWidget(2, thinking_toggle)
            head.insertStretch(3, 1)
            self._thinking_toggle = thinking_toggle
            self._thinking_collapsed = False
        except Exception:
            self._thinking_toggle = None
        thinking_label = QLabel('')
        thinking_label.setWordWrap(True)
        thinking_label.setTextFormat(Qt.PlainText)
        thinking_label.setStyleSheet(
            'color:#7a8aa0; font-size:12px; background:#141b2c; border-radius:6px; padding:6px;')
        thinking_label.hide()  # 无思考时不占位
        self._chat_type_content.addWidget(thinking_label)
        self._thinking_label = thinking_label
        # 正文流式区
        self._stream_label = QLabel('')
        self._stream_label.setWordWrap(True)
        self._stream_label.setTextFormat(Qt.PlainText)
        self._stream_label.setStyleSheet(f'color:{self.theme.get("bubble_text", "#eee")}; font-size:14px;')
        self._chat_type_content.addWidget(self._stream_label)
        self._chat_scroll_bottom()
        self._stream_active = True

    def _strip_emotion_tags(self, combined):
        """过滤 emotion 控制标签（跨 chunk 安全）。返回 (清理文本, 未闭合尾缀, 提取到的情绪列表)
        （实现已搬至 pet_bubble.strip_emotion_tags）"""
        return pb.strip_emotion_tags(combined)
    def _on_stream(self, chunk):
        """主线程槽：流式正文 chunk → 直接渲染（真流式，无卡顿）"""
        try:
            if not self._stream_active:
                if (getattr(self, '_thinking_label', None) is not None
                        and getattr(self, '_chat_type_content', None) is not None
                        and self._thinking_label.parent() is not None):
                    # v6.40 fix：工具调用轮次续用——思考区已在本气泡，复用气泡只重建正文 label
                    self._stream_label = QLabel('')
                    self._stream_label.setWordWrap(True)
                    self._stream_label.setTextFormat(Qt.PlainText)
                    self._stream_label.setStyleSheet(f'color:{self.theme.get("bubble_text", "#eee")}; font-size:14px;')
                    self._chat_type_content.addWidget(self._stream_label)
                else:
                    self._chat_type_stream_begin()
                self._stream_active = True
            # v6.41 fix：正文渲染即标记（reasoning 先触发 begin 后 content 到达也必须标记，
            # 否则 _display_ai_reply 误走非流式分支 → 正文重复打字机渲染 + 情感选项不弹出）
            self._stream_rendered = True
            combined = getattr(self, '_stream_pending', '') + chunk
            cleaned, pending, emotions = self._strip_emotion_tags(combined)
            self._stream_pending = pending
            for emo in emotions:
                try:
                    self._apply_emotion(emo)
                except Exception:
                    pass
            if not cleaned:
                return
            self._stream_text += cleaned
            if self._stream_label is not None:
                self._stream_label.setText(self._stream_text)
                self._chat_scroll_bottom()
        except Exception:
            pass

    def _on_reasoning(self, chunk):
        """主线程槽：流式思考 chunk → 同卡片灰色思考区（可折叠）；过滤 emotion 标签"""
        try:
            if self._thinking_label is None:
                self._chat_type_stream_begin()
                self._stream_rendered = True
            if self._thinking_label is None:
                return
            combined = getattr(self, '_thinking_pending', '') + chunk
            cleaned, pending, _emotions = self._strip_emotion_tags(combined)
            self._thinking_pending = pending
            if not cleaned:
                return
            if not self._thinking_label.isVisible():
                self._thinking_label.show()
            self._thinking_label.setText('💭 ' + self._thinking_label.text()[2:] + cleaned)
            self._chat_scroll_bottom()
        except Exception:
            pass

    def _on_stream_done(self):
        """主线程槽：流式结束（清状态行；思考区保留在卡片内可折叠）"""
        self._stream_active = False
        # flush 残留 pending（若流结束时仍未凑成标签 → 是普通文本，显示出来）
        if getattr(self, '_stream_pending', ''):
            self._stream_text += self._stream_pending
            self._stream_pending = ''
            if self._stream_label is not None:
                self._stream_label.setText(self._stream_text)
                self._chat_scroll_bottom()
        if getattr(self, '_thinking_pending', ''):
            if self._thinking_label is not None:
                self._thinking_label.setText('💭 ' + self._thinking_label.text()[2:] + self._thinking_pending)
            self._thinking_pending = ''
        self._stream_label = None
        try:
            self._remove_status_line()
        except Exception:
            pass

    # ---------- v6.40 流式富文本恢复 ----------
    @staticmethod
    def _looks_like_table(text):
        """粗略判断：多行且含管道符的表格（拆至 chat_render.looks_like_table）"""
        return looks_like_table(text)

    def _rerender_rich(self, text):
        """流式结束后：把纯文本气泡重渲染为富文本（代码卡/表格卡，含复制按钮）"""
        content = getattr(self, '_chat_type_content', None)
        if content is None:
            return
        thinking = getattr(self, '_thinking_label', None)
        while content.count():
            item = content.takeAt(0)
            w = item.widget()
            if w is thinking:
                continue  # v6.40 fix：思考区保留，不被重渲染清掉（否则折叠后无法展开）
            if w:
                w.deleteLater()
        blocks = self._split_rich_blocks(text)
        for kind, c in blocks:
            self._render_one_block(content, kind, c)
        if thinking is not None:
            content.insertWidget(0, thinking)  # 思考区保持在正文上方
            thinking.setVisible(not getattr(self, '_thinking_collapsed', False) and bool(thinking.text().strip()))
        self._chat_scroll_bottom()

    def _display_ai_reply(self, reply):
        """主线程槽：显示 AI 回复（解析情绪标签切换立绘）"""
        # v6.42 fix：任何回复路径先清状态行（工具轮耗尽/超时后的非流式回复会残留 ⏳）
        try:
            self._remove_status_line()
        except Exception:
            pass
        if getattr(self, '_stream_rendered', False) and reply:
            # v6.40 流式已渲染正文：只记录历史 + 情绪切换，不重复打字机
            self._stream_rendered = False
            import datetime as _dt
            ts = _dt.datetime.now().strftime('%m-%d %H:%M')
            _display, emotion = self._strip_emotion_tag(reply)
            self.display_msgs.append({'who': '桌宠', 'text': str(_display), 'ts': ts})  # v6.40 fix：历史存剥标签后的正文
            if len(self.display_msgs) > 300:
                self.display_msgs = self.display_msgs[-300:]
            self._apply_emotion(emotion)
            self._save_chat_memory()  # v6.40 fix：流式路径此前跳过保存，对话历史不落盘
            try:
                self._attach_bubble_actions(self._chat_type_bubble, _display)  # v6.40 fix：复制按钮存剥标签后的正文（原始reply含[emotion:xxx]）
            except Exception:
                pass
            # v6.40+ 富文本恢复：含代码块/表格 → 同气泡重渲染成卡片（复制按钮回归）
            if ('```' in _display) or self._looks_like_table(_display):
                try:
                    self._rerender_rich(_display)
                except Exception:
                    pass
            # v6.41 fix：流式路径也渲染情感选项（AI 正文 + offer_choices 工具调用时）
            if getattr(self, '_choices_requested', False):
                self._choices_requested = False
                try:
                    self._render_choices()
                except Exception:
                    pass
            return
        if not reply and getattr(self, '_choices_requested', False):
            self._choices_requested = False
            self._render_choices()
            return
        display, emotion = self._strip_emotion_tag(reply)
        if emotion:
            self._apply_emotion(emotion)
        # AI 回复流式显示到聊天框（打字机效果），不弹气泡避免挡脸
        self._chat_type_start(display)
        self._play_sound('msg')
        self._save_chat_memory()

    # ---------- 聊天面板打字机（v6.15 流式显示，按 Markdown 块渲染） ----------
    @staticmethod
    def _split_md_blocks(text):
        """把 markdown 拆成渲染块（拆至 chat_render.split_md_blocks）
        （实现已搬至 pet_bubble.split_typewriter_blocks）"""
        return pb.split_typewriter_blocks(text)
    def _chat_type_start(self, text):
        """开始流式显示：拆块预渲染，逐块插入（回复到达时先清掉残留状态行）"""
        text = self._strip_emotion_tags(str(text))[0]  # v6.40 出口统一剥 emotion 标签
        self.chat_type_blocks = self._split_rich_blocks(text)  # (类型, 内容) 元组列表
        self.chat_type_index = 0
        # 记录显示历史（AI 回复全文，与面板显示同步——打字机只是动画，历史立即入栈）
        import datetime as _dt
        ts = _dt.datetime.now().strftime('%m-%d %H:%M')
        self.display_msgs.append({'who': '桌宠', 'text': str(text), 'ts': ts})
        if len(self.display_msgs) > 300:
            self.display_msgs = self.display_msgs[-300:]
        # 回复到达：自动检查代码块语法（v6.17），并清除残留状态行
        self._code_check_warning = self._check_code_blocks(text)
        self._remove_status_line()
        # 创建气泡骨架（头部 + 空内容区，逐块填充；v6.19b 传 text 使 AI 消息也有复制/存图按钮）
        self._chat_type_bubble, self._chat_type_content = self._new_bubble('桌宠', ts, is_user=False, text=str(text))
        self._chat_scroll_bottom()
        if not self.chat_type_blocks:
            return
        self.chat_type_timer.start(30)

    def _chat_type_tick(self):
        """打字机 tick：渲染一块（文本段落/代码卡片/表格卡片）"""
        if self.chat_type_index >= len(self.chat_type_blocks):
            self.chat_type_timer.stop()
            return
        kind, content = self.chat_type_blocks[self.chat_type_index]
        self._render_one_block(self._chat_type_content, kind, content)
        self.chat_type_index += 1
        self._chat_scroll_bottom()
        if self.chat_type_index >= len(self.chat_type_blocks):
            self.chat_type_timer.stop()
            # v6.30 打字机完成：追加待展示的选项按钮（同气泡）
            if getattr(self, '_pending_choices', None):
                self._render_choices()
            self._maybe_append_code_warning()

    def _chat_type_finish(self):
        """立即完成剩余块（新消息到达时 fast-forward）"""
        if not self.chat_type_timer.isActive():
            return
        self.chat_type_timer.stop()
        while self.chat_type_index < len(getattr(self, 'chat_type_blocks', [])):
            self._chat_type_tick()

    # ---------- 对话记忆（按角色隔离，v6.16） ----------
    def _chat_memory_path(self):
        """每个角色独立的对话历史文件"""
        return os.path.join(BASE_DIR, f'chat_memory_{self.current}.json')

    def _load_chat_memory(self):
        """从文件加载当前角色的历史对话（LLM 上下文 + 显示历史分离）——只加载数据，回显由 _echo_display_history 在面板创建后执行"""
        mem_path = self._chat_memory_path()
        try:
            if os.path.exists(mem_path):
                with open(mem_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.chat_history_msgs = data.get('messages', [])
                self.display_msgs = data.get('display', [])[-300:]
                # v6.40：净化历史数据中残留的 emotion 控制标签（旧版保存过含标签的显示历史）
                import re as _re
                for _m in self.display_msgs:
                    if isinstance(_m, dict) and _m.get('text'):
                        _m['text'] = _re.sub(r'\[emotion:[^\]]*\]', '', str(_m['text']))
        except Exception:
            pass

    def _echo_display_history(self):
        """回显最近 30 条显示历史到面板（在聊天历史区创建后调用）"""
        shown = self.display_msgs[-30:]
        for m in shown:
            ts = m.get('ts', '')
            who = m.get('who', '桌宠')
            bubble, content = self._new_bubble(who, ts, is_user=(who == '我'), text=str(m.get('text', '')))
            self._render_md_into(content, str(m.get('text', '')))
        self._display_offset = max(0, len(self.display_msgs) - len(shown))
        self._update_more_button()

    def _save_chat_memory(self):
        """保存当前角色的对话历史到文件（LLM 上下文 + 显示历史）"""
        mem_path = self._chat_memory_path()
        try:
            # 只保留最近 50 条 LLM 上下文 + 最近 300 条显示历史
            msgs = self.chat_history_msgs[-50:]
            self._atomic_write_json(mem_path, {'messages': msgs, 'display': self.display_msgs[-300:]})
        except Exception:
            pass

    def _clear_chat_memory(self):
        self.chat_history_msgs = []
        self.display_msgs = []
        self._display_offset = 0
        self._save_chat_memory()
        self._clear_chat_history()
        self._update_more_button()

    def _select_msgs_dialog(self):
        """导出前选择要导出的聊天消息（可视化勾选）——返回选中的 display_msgs 子集；取消返回 None"""
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
                                       QPushButton, QHeaderView, QCheckBox, QWidget, QAbstractItemView)
        msgs = self.display_msgs
        if not msgs:
            self._append_chat('桌宠', '没有可导出的聊天记录')
            return None
        is_en = getattr(self, 'language', 'zh') == 'en'
        T = self._t
        dlg = QDialog(self)
        dlg.setWindowTitle(T('export_chat'))
        dlg.resize(640, 460)
        lay = QVBoxLayout(dlg)

        table = QTableWidget(len(msgs), 4)
        table.setHorizontalHeaderLabels(['✓', T('mem_time'), T('mem_who'), T('mem_content')])
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        table.setColumnWidth(0, 40)
        table.setColumnWidth(1, 100)
        table.setColumnWidth(2, 60)
        table.verticalHeader().setVisible(False)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        checks = []
        for i, m in enumerate(msgs):
            cb = QCheckBox()
            cb.setChecked(True)
            w = QWidget()
            from PySide6.QtWidgets import QHBoxLayout as _HL
            hl = _HL(w)
            hl.addWidget(cb)
            hl.setAlignment(Qt.AlignCenter)
            hl.setContentsMargins(0, 0, 0, 0)
            table.setCellWidget(i, 0, w)
            checks.append(cb)
            table.setItem(i, 1, QTableWidgetItem(m.get('ts', '')))
            table.setItem(i, 2, QTableWidgetItem(m.get('who', '桌宠')))
            text = str(m.get('text', '')).replace('\n', ' ')
            table.setItem(i, 3, QTableWidgetItem(text[:60] + ('…' if len(text) > 60 else '')))
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        lay.addWidget(table, 1)

        def set_all(v):
            for c in checks:
                c.setChecked(v)

        def set_who(who):
            for i, m in enumerate(msgs):
                checks[i].setChecked(m.get('who') == who)

        top = QHBoxLayout()
        b_all = QPushButton(T('mem_select_all'))
        b_all.clicked.connect(lambda: set_all(True))
        b_none = QPushButton(T('mem_select_none'))
        b_none.clicked.connect(lambda: set_all(False))
        b_me = QPushButton(T('mem_select_me'))
        b_me.clicked.connect(lambda: set_who('我'))
        b_pet = QPushButton(T('mem_select_pet'))
        b_pet.clicked.connect(lambda: set_who('桌宠'))
        for b in (b_all, b_none, b_me, b_pet):
            top.addWidget(b)
        top.addStretch(1)
        lay.addLayout(top)

        bottom = QHBoxLayout()
        label = QTableWidgetItem if False else None
        b_ok = QPushButton(T('mem_export'))
        b_cancel = QPushButton('✕')
        bottom.addStretch(1)
        bottom.addWidget(b_ok)
        bottom.addWidget(b_cancel)
        lay.addLayout(bottom)

        def update_count():
            """按钮显示选中条数；0 条时禁用"""
            sel = sum(1 for c in checks if c.isChecked())
            b_ok.setText(T('mem_export') + f' ({sel})')
            b_ok.setEnabled(sel > 0)

        for c in checks:
            c.toggled.connect(update_count)
        update_count()

        result = {'selected': None}

        def on_ok():
            result['selected'] = [m for m, c in zip(msgs, checks) if c.isChecked()]
            dlg.accept()

        b_ok.clicked.connect(on_ok)
        b_cancel.clicked.connect(dlg.reject)
        dlg.exec()
        return result['selected']

    def _export_chat(self):
        """导出聊天记录——先可视化勾选要导出的消息，再选保存位置（默认 聊天记录/ 文件夹）"""
        try:
            import datetime as _dt
            from PySide6.QtWidgets import QFileDialog
            msgs = self._select_msgs_dialog()
            if msgs is None:
                return  # 用户取消选择
            if not msgs:
                self._append_chat('桌宠', '未选择任何消息')
                return
            # 默认导出目录：BASE_DIR/聊天记录/（不存在则创建）
            export_dir = os.path.join(BASE_DIR, '聊天记录')
            os.makedirs(export_dir, exist_ok=True)
            default_name = f'聊天记录_{_dt.datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'
            default_path = os.path.join(export_dir, default_name)
            path, _ = QFileDialog.getSaveFileName(
                self, '导出聊天记录', default_path, '文本文件 (*.txt)')
            if not path:
                return  # 用户取消保存
            with open(path, 'w', encoding='utf-8') as f:
                f.write(f'DeepSeek 桌宠聊天记录（导出时间 {_dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}，共 {len(msgs)} 条）\n')
                f.write('=' * 40 + '\n')
                for m in msgs:
                    who = m.get('who', '桌宠')
                    c = (m.get('text') or '').strip()
                    ts = m.get('ts', '')
                    if c:
                        import re as _rex
                        c = _rex.sub(r'\[emotion:[a-z_]+\]?\s*', '', c)
                        f.write(f'[{ts}] {who}: {c}\n')
            self._append_chat('桌宠', f'📤 已导出 {len(msgs)} 条：{path}')
        except Exception as e:
            self._append_chat('桌宠', f'导出失败：{e}')

    def _scan_live2d_models(self):
        """扫描 assets/live2d/ 下所有含 model3.json 的模型目录，返回 {目录名: 路径}"""
        result = {}
        root = os.path.join(BASE_DIR, 'assets', 'live2d')
        if os.path.isdir(root):
            for d in os.listdir(root):
                sub = os.path.join(root, d)
                if os.path.isdir(sub):
                    for f in os.listdir(sub):
                        if f.endswith('.model3.json'):
                            result[d] = os.path.join(sub, f)
                            break
        return result

    def _live2d_model_path(self):
        """当前配置的 Live2D 模型路径（不存在则回退第一个可用）"""
        models = self._scan_live2d_models()
        name = getattr(self, 'live2d_model', 'mao')
        if name in models:
            return models[name]
        if models:
            self.live2d_model = next(iter(models))
            return models[self.live2d_model]
        return None

    def _create_l2d_embedded(self):
        """创建内嵌 Live2D 显示部件（透明 GL，替代静态立绘区域）"""
        model_path = self._live2d_model_path()
        if model_path is None or not os.path.exists(model_path):
            return None
        try:
            import live2d.v3 as live2d
            from PySide6.QtOpenGLWidgets import QOpenGLWidget
        except Exception:
            return None
        if not getattr(self, '_l2d_inited', False):
            try:
                live2d.init()
                self._l2d_inited = True
            except Exception:
                return None

        class L2DPet(QOpenGLWidget):
            def __init__(self, pet, parent=None):
                super().__init__(parent)
                self.pet = pet
                self.model = None
                self.t = 0
                self._look = None
                self._gl_ready = False
                self.setMouseTracking(True)

            def initializeGL(self):
                try:
                    live2d.glInit()
                    self.model = live2d.LAppModel()
                    self.model.LoadModelJson(model_path)
                    self.model.Resize(max(1, self.width()), max(1, self.height()))
                    self.model.SetAutoBlinkEnable(True)
                    self.model.SetAutoBreathEnable(True)
                    self.model.StartRandomMotion('Idle', 1)
                    self._gl_ready = True
                    # 动画驱动 30fps
                    from PySide6.QtCore import QTimer as _QT
                    self.drive_timer = _QT(self)
                    self.drive_timer.timeout.connect(self._drive)
                    self.drive_timer.start(33)
                except Exception:
                    import traceback
                    traceback.print_exc()

            def _drive(self):
                if self.model is None or not self._gl_ready:
                    return
                import math
                self.t += 0.033
                try:
                    if self._look:
                        nx, ny = self._look
                        self.model.SetParameterValue('ParamEyeBallX', nx * 1.0)
                        self.model.SetParameterValue('ParamEyeBallY', ny * 0.8)
                        self.model.SetParameterValue('ParamAngleZ', nx * 12.0)
                        self.model.SetParameterValue('ParamAngleX', ny * 10.0)
                    else:
                        self.model.SetParameterValue('ParamAngleZ', math.sin(self.t * 1.2) * 8.0)
                        self.model.SetParameterValue('ParamAngleX', math.sin(self.t * 0.8) * 4.0)
                    self.model.SetParameterValue('ParamBodyAngleZ', math.sin(self.t * 0.6) * 4.0)
                    blink = max(0.0, math.sin(self.t * math.pi / 3.0))
                    self.model.SetParameterValue('ParamEyeLOpen', blink)
                    self.model.SetParameterValue('ParamEyeROpen', blink)
                    self.model.SetParameterValue('ParamBreath', math.sin(self.t * 1.5) * 0.5 + 0.5)
                    self.update()
                except Exception:
                    pass

            def paintGL(self):
                live2d.clearBuffer(0, 0, 0, 0)
                if self.model and self._gl_ready:
                    self.model.Update()
                    self.model.Draw()

            def resizeGL(self, w, h):
                if self.model:
                    self.model.Resize(max(1, w), max(1, h))

            def mousePressEvent(self, e):
                self.pet.mousePressEvent(e)

            def mouseReleaseEvent(self, e):
                self.pet.mouseReleaseEvent(e)
                if self.model and not self.pet.dragging:
                    self.model.StartRandomMotion('TapBody', 2)

            def mouseDoubleClickEvent(self, e):
                self.pet.mouseDoubleClickEvent(e)

            def mouseMoveEvent(self, e):
                self._look = ((e.position().x() / max(1, self.width()) - 0.5) * 2,
                              (e.position().y() / max(1, self.height()) - 0.5) * 2)
                if self.pet.dragging and (e.buttons() & Qt.LeftButton):
                    self.pet.move(e.globalPosition().toPoint() - self.pet.drag_offset)

            def leaveEvent(self, e):
                self._look = None

        w = L2DPet(self)
        w.setMinimumSize(200, 300)
        return w

    def _set_live2d_model(self, name):
        """切换 Live2D 模型（重建显示部件）"""
        is_en = getattr(self, 'language', 'zh') == 'en'
        models = self._scan_live2d_models()
        if name not in models:
            self._append_chat('桌宠', '模型不存在' if not is_en else 'Model not found')
            return
        self.live2d_model = name
        self._save_cfg_value('live2d_model', name)
        if getattr(self, 'display_mode', 'static') == 'live2d':
            # 销毁旧部件重建
            old = getattr(self, '_l2d_widget', None)
            if old is not None:
                self.pet_stack.removeWidget(old)
                old.deleteLater()
                self._l2d_widget = None
            w = self._create_l2d_embedded()
            if w is not None:
                self.pet_stack.addWidget(w)
                self._l2d_widget = w
                self.pet_stack.setCurrentWidget(w)
                self.bubble.raise_()
        self._append_chat('桌宠', f'🤖 已切换 Live2D 模型：{name}' if not is_en else f'🤖 Switched Live2D model: {name}')

    def _set_display_mode(self, mode):
        """切换显示模式：static 静态立绘 / live2d 模型"""
        if mode not in ('static', 'live2d'):
            return
        is_en = getattr(self, 'language', 'zh') == 'en'
        if mode == 'live2d':
            if not hasattr(self, '_l2d_widget') or self._l2d_widget is None:
                w = self._create_l2d_embedded()
                if w is None:
                    self._append_chat('桌宠', 'Live2D 不可用（缺少 live2d-py 或模型文件）' if not is_en else 'Live2D unavailable (missing live2d-py or model)')
                    return
                self.pet_stack.addWidget(w)
                self._l2d_widget = w
            self.display_mode = 'live2d'
            self.pet_stack.setCurrentWidget(self._l2d_widget)
            self.bubble.raise_()
            self._save_cfg_value('display_mode', 'live2d')
            self._append_chat('桌宠', '🎬 已切换到 Live2D 模式（右键可切回静态立绘）' if not is_en else '🎬 Switched to Live2D mode')
        else:
            self.display_mode = 'static'
            self.pet_stack.setCurrentWidget(self.pet_label)
            self._save_cfg_value('display_mode', 'static')
            self._append_chat('桌宠', '🖼️ 已切换回静态立绘模式' if not is_en else '🖼️ Switched to static art mode')

    def _open_live2d_preview(self):
        """Live2D 预览窗口（Mao 模型：自动眨眼/呼吸/跟随光标），与静态立绘并行"""
        if getattr(self, '_l2d_win', None) is not None:
            try:
                self._l2d_win.show()
                self._l2d_win.raise_()
                return
            except Exception:
                self._l2d_win = None
        if not os.path.exists(LIVE2D_MODEL):
            self._append_chat('桌宠', 'Live2D 模型不存在（assets/live2d/mao/），无法预览')
            return
        try:
            import live2d.v3 as live2d
            from PySide6.QtWidgets import QMainWindow
            from PySide6.QtOpenGLWidgets import QOpenGLWidget
        except Exception as e:
            self._append_chat('桌宠', f'Live2D 依赖缺失：{e}（需要 pip install live2d-py）')
            return
        if not getattr(self, '_l2d_inited', False):
            try:
                live2d.init()
                self._l2d_inited = True
            except Exception as e:
                self._append_chat('桌宠', f'Live2D 初始化失败：{e}')
                return

        class L2DWidget(QOpenGLWidget):
            def __init__(self, parent=None):
                super().__init__(parent)
                self.model = None
                self.t = 0
                self.ids = []
                self._look = None  # 视线跟随目标 (nx, ny)，None=无鼠标
                self.setMouseTracking(True)  # 关键：不按鼠标也触发 mouseMoveEvent（视线跟随）

            def initializeGL(self):
                try:
                    live2d.glInit()
                    self.model = live2d.LAppModel()
                    self.model.LoadModelJson(LIVE2D_MODEL)
                    self.model.Resize(self.width(), self.height())
                    self.ids = self.model.GetParamIds()
                    self.model.SetAutoBlinkEnable(True)
                    self.model.SetAutoBreathEnable(True)
                    self.model.StartRandomMotion('Idle', 1)
                    # 手动动画驱动 30fps：头部摆动/眨眼/呼吸，确保明显可见
                    self.anim_timer = QTimer(self)
                    self.anim_timer.timeout.connect(self._drive)
                    self.anim_timer.start(33)
                except Exception:
                    import traceback
                    traceback.print_exc()

            def _drive(self):
                """每帧驱动：视线跟随（有鼠标）或自动摆动（无鼠标）+ 眨眼呼吸"""
                if self.model is None:
                    return
                import math
                self.t += 0.033
                try:
                    if self._look:
                        # 鼠标在窗口内：头部+眼球跟随光标（满幅度）
                        nx, ny = self._look
                        self.model.SetParameterValue('ParamEyeBallX', nx * 1.0)
                        self.model.SetParameterValue('ParamEyeBallY', ny * 0.8)
                        self.model.SetParameterValue('ParamAngleZ', nx * 12.0)
                        self.model.SetParameterValue('ParamAngleX', ny * 10.0)
                    else:
                        # 无鼠标：自动缓慢摆动
                        self.model.SetParameterValue('ParamEyeBallX', 0.0)
                        self.model.SetParameterValue('ParamEyeBallY', 0.0)
                        self.model.SetParameterValue('ParamAngleZ', math.sin(self.t * 1.2) * 8.0)
                        self.model.SetParameterValue('ParamAngleX', math.sin(self.t * 0.8) * 4.0)
                    self.model.SetParameterValue('ParamBodyAngleZ', math.sin(self.t * 0.6) * 4.0)
                    blink = max(0.0, math.sin(self.t * math.pi / 3.0))
                    self.model.SetParameterValue('ParamEyeLOpen', blink)
                    self.model.SetParameterValue('ParamEyeROpen', blink)
                    self.model.SetParameterValue('ParamBreath', math.sin(self.t * 1.5) * 0.5 + 0.5)
                    self.update()  # 关键：每帧请求重绘，否则画面不刷新
                except Exception:
                    pass

            def paintGL(self):
                try:
                    live2d.clearBuffer(0, 0, 0, 0)
                    if self.model:
                        self.model.Update()
                        self.model.Draw()
                except Exception:
                    pass

            def resizeGL(self, w, h):
                if self.model:
                    self.model.Resize(w, h)

            def mouseMoveEvent(self, e):
                if self.model:
                    # 归一化到 -1~1（相对窗口中心），供参数驱动
                    self._look = (
                        (e.position().x() / max(1, self.width()) - 0.5) * 2,
                        (e.position().y() / max(1, self.height()) - 0.5) * 2,
                    )
                    self.update()

            def leaveEvent(self, e):
                self._look = None

            def mousePressEvent(self, e):
                if self.model:
                    self.model.StartRandomMotion('TapBody', 2)

        win = QMainWindow()
        win.setWindowTitle('Live2D Preview' if getattr(self, 'language', 'zh') == 'en' else 'Live2D 预览')
        win.resize(420, 520)
        win.setCentralWidget(L2DWidget(win))
        win.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        win.show()
        self._l2d_win = win

    def _archive_and_clear(self):
        """存档当前对话（带时间戳 txt）并清空，重新开始"""
        is_en = getattr(self, 'language', 'zh') == 'en'
        if not self.chat_history_msgs:
            self._append_chat('桌宠', '没有可存档的对话' if not is_en else 'No conversation to archive')
            return
        try:
            import datetime as _dt
            import re as _rex
            fname = f'聊天存档_{self.current}_{_dt.datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'
            path = os.path.join(BASE_DIR, fname)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(f'角色: {CHARACTERS[self.current]["name"]}  时间: {_dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
                f.write('=' * 40 + '\n')
                for m in self.chat_history_msgs:
                    who = '我' if m.get('role') == 'user' else '桌宠'
                    c = (m.get('content') or '').strip()
                    if c and not c.startswith('（'):
                        c = _rex.sub(r'\[emotion[:=][a-z_]+\]?\s*', '', c)
                        f.write(f'{who}: {c}\n')
            # 清空对话
            self.chat_history_msgs = []
            self._clear_chat_history()
            self._save_chat_memory()
            self._append_chat('桌宠', f'📦 已存档并清空：{fname}' if not is_en else f'📦 Archived and cleared: {fname}')
        except Exception as e:
            self._append_chat('桌宠', f'存档失败：{e}' if not is_en else f'Archive failed: {e}')

    def _open_memory_manager(self):
        """记忆管理窗口：表格视图，支持筛选/搜索/编辑/删除/添加"""
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
                                       QPushButton, QComboBox, QLineEdit, QHeaderView, QInputDialog, QMessageBox)
        is_en = getattr(self, 'language', 'zh') == 'en'
        T = self._t

        dlg = QDialog(self)
        dlg.setWindowTitle(T('memory_menu'))
        dlg.resize(600, 440)
        lay = QVBoxLayout(dlg)

        # 顶部：角色筛选 + 搜索
        top = QHBoxLayout()
        role_box = QComboBox()
        role_box.addItem(T('mem_all'), '')
        role_box.addItem('⚡ Flash', 'flash')
        role_box.addItem('🐋 Pro', 'pro')
        top.addWidget(role_box)
        search_edit = QLineEdit()
        search_edit.setPlaceholderText(T('mem_search'))
        top.addWidget(search_edit, 1)
        lay.addLayout(top)

        # 表格
        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels([T('mem_imp'), T('mem_content'), T('mem_role'), T('mem_time'), ''])
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.setColumnWidth(0, 70)
        table.setColumnWidth(2, 70)
        table.setColumnWidth(3, 110)
        table.setColumnWidth(4, 60)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        lay.addWidget(table, 1)

        def refresh():
            """刷新表格（按筛选+搜索）"""
            rfilter = role_box.currentData()
            kw = search_edit.text().strip().lower()
            active = [f for f in self.memory_facts if f.get('status') == 'active']
            if rfilter:
                active = [f for f in active if f.get('roles', 'both') in (rfilter, 'both')]
            if kw:
                active = [f for f in active if kw in (f.get('content') or '').lower()]
            active.sort(key=lambda x: -x.get('importance', 3))
            self._mem_current_ids = [f.get('id') for f in active]
            table.setRowCount(0)
            for f in active:
                r = table.rowCount()
                table.insertRow(r)
                table.setItem(r, 0, QTableWidgetItem('★' * f.get('importance', 3)))
                table.setItem(r, 1, QTableWidgetItem(f.get('content', '')))
                roles = f.get('roles', 'both')
                table.setItem(r, 2, QTableWidgetItem({'flash': 'Flash', 'pro': 'Pro', 'both': 'Both'}.get(roles, 'Both')))
                table.setItem(r, 3, QTableWidgetItem(f.get('created_at', '')[:16]))
                del_btn = QPushButton(T('mem_edit'))
                del_btn.setFixedWidth(52)
                del_btn.clicked.connect(lambda checked, fid=f.get('id', ''): _edit_row(fid, table.currentRow()))
                table.setCellWidget(r, 4, del_btn)

        def _edit_row(fid, row):
            """编辑单条记忆（内容+重要度）"""
            f = next((x for x in self.memory_facts if x.get('id') == fid), None)
            if not f:
                return
            new_text, ok1 = QInputDialog.getText(dlg, T('mem_edit'), T('mem_content'), text=f.get('content', ''))
            if ok1 and new_text.strip():
                imp, ok2 = QInputDialog.getInt(dlg, T('mem_edit'), T('mem_imp'), f.get('importance', 3), 1, 5)
                if ok2:
                    f['content'] = new_text.strip()
                    f['importance'] = imp
                    f['updated_at'] = __import__('datetime').datetime.now().isoformat(timespec='seconds')
                    self._save_memory()
                    refresh()

        def on_double(row, col):
            item = table.item(row, 1)
            if item:
                fid = self._memory_fid_by_row(row)
                if fid:
                    _edit_row(fid, row)

        def add_memory():
            text, ok = QInputDialog.getText(dlg, T('mem_add'), T('mem_content'))
            if ok and text.strip():
                imp, ok2 = QInputDialog.getInt(dlg, T('mem_add'), T('mem_imp'), 3, 1, 5)
                if ok2:
                    self._remember_fact('add', text.strip(), imp)
                    refresh()

        def delete_selected():
            rows = sorted({i.row() for i in table.selectedIndexes()}, reverse=True)
            if not rows:
                return
            for r in rows:
                fid = self._memory_fid_by_row(r)
                if fid:
                    self._remember_fact('delete', fid=fid)
            refresh()

        # 底部按钮
        bottom = QHBoxLayout()
        btn_add = QPushButton(T('mem_add'))
        btn_add.clicked.connect(add_memory)
        btn_del = QPushButton(T('mem_delete'))
        btn_del.clicked.connect(delete_selected)
        btn_clear = QPushButton(T('clear_memory'))
        btn_clear.clicked.connect(self._clear_memory_confirm)
        btn_close = QPushButton('✕')
        btn_close.clicked.connect(dlg.close)
        bottom.addWidget(btn_add)
        bottom.addWidget(btn_del)
        bottom.addWidget(btn_clear)
        bottom.addStretch(1)
        bottom.addWidget(btn_close)
        lay.addLayout(bottom)

        role_box.currentIndexChanged.connect(refresh)
        search_edit.textChanged.connect(refresh)
        table.cellDoubleClicked.connect(on_double)
        self._mem_current_ids = []
        refresh()
        dlg.exec()

    def _memory_fid_by_row(self, row):
        """辅助：按表格行号取当前筛选列表中的记忆 id"""
        ids = getattr(self, '_mem_current_ids', [])
        if 0 <= row < len(ids):
            return ids[row]
        return None

    # ---------- 定时提醒 ----------
    def _reminders_path(self):
        """提醒持久化文件（关机后重启不丢失）"""
        return os.path.join(BASE_DIR, 'reminders.json')

    def _save_reminders(self):
        try:
            self._atomic_write_json(self._reminders_path(), self.reminders)
        except Exception:
            pass

    def _load_reminders(self):
        """加载持久化提醒：关机期间已到期的 → 补发到聊天面板（用户能看到）；未到期 → 继续计时"""
        try:
            if os.path.exists(self._reminders_path()):
                with open(self._reminders_path(), 'r', encoding='utf-8') as f:
                    data = json.load(f)
                now = time.time()
                missed = [r for r in data if now >= r.get('time', 0)]
                pending = [r for r in data if now < r.get('time', 0)]
                self.reminders = pending
                self._save_reminders()   # 关键：补发过的从文件移除，防重启/重开重复补发
                for r in missed:
                    self._deliver_missed_reminder(r)
        except Exception:
            pass

    def _deliver_missed_reminder(self, r):
        """补发关机期间错过的提醒到聊天面板"""
        import datetime as _dt
        due = _dt.datetime.fromtimestamp(r.get('time', 0)).strftime('%m-%d %H:%M')
        text = r.get('text', '')
        if r.get('type') == 'followup':
            self._append_chat('桌宠', '💗 早安回访：昨晚休息得怎么样？补上早上的问候——记得吃早餐哦 ☀️')
            self.say_plain('早安呀，昨晚休息得怎么样？记得吃早餐哦', immediate=True)
        else:
            self._append_chat('桌宠', f'⏰ 补发提醒（原定 {due}，关机期间错过）：{text}')
            self.say_plain(f'⏰ 补发提醒：{text}', immediate=True)
            self._play_sound('remind')

    def _check_reminders(self):
        """每秒检查提醒是否到期（普通提醒=气泡；回访=触发 AI 主动关心）"""
        now = time.time()
        due = [r for r in self.reminders if now >= r['time']]
        if due:
            self.reminders = [r for r in self.reminders if now < r['time']]
            self._save_reminders()
            for r in due:
                if r.get('type') == 'followup':
                    self._ai_followup(r['text'])
                else:
                    self.say_plain(f'⏰ 提醒：{r["text"]}')
                    self._append_chat('桌宠', f'⏰ 提醒：{r["text"]}')
                    self._play_sound('remind')

    def _add_reminder(self, seconds, text, rtype='normal'):
        self.reminders.append({'time': time.time() + seconds, 'text': text, 'type': rtype})
        self._save_reminders()
        if rtype == 'followup':
            self._append_chat('桌宠', f'好，{seconds} 秒后我再来关心你：{text}')
        else:
            self.say_plain(f'好，{seconds} 秒后提醒你：{text}')
            self._append_chat('桌宠', f'已设置提醒（{seconds}秒后）：{text}')

    # ---------- 提醒管理窗口（v6.22） ----------
    def _open_reminder_manager(self):
        """提醒管理：查看/取消已设提醒"""
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
                                       QPushButton, QHeaderView)
        is_en = getattr(self, 'language', 'zh') == 'en'
        T = self._t
        dlg = QDialog(self)
        dlg.setWindowTitle(T('reminder_menu'))
        dlg.resize(480, 300)
        lay = QVBoxLayout(dlg)

        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels([T('rem_left'), T('mem_content'), T('rem_type')])
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.setColumnWidth(0, 90)
        table.setColumnWidth(2, 80)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        lay.addWidget(table, 1)

        def fmt_left(t):
            d = t - time.time()
            if d <= 0:
                return '0s'
            h, m, s = int(d // 3600), int(d % 3600 // 60), int(d % 60)
            if h:
                return f'{h}h{m}m'
            if m:
                return f'{m}m{s}s'
            return f'{s}s'

        def refresh():
            table.setRowCount(0)
            if not self.reminders:
                return
            for r in sorted(self.reminders, key=lambda x: x['time']):
                row = table.rowCount()
                table.insertRow(row)
                table.setItem(row, 0, QTableWidgetItem(fmt_left(r['time'])))
                table.setItem(row, 1, QTableWidgetItem(r['text']))
                table.setItem(row, 2, QTableWidgetItem(T('rem_followup') if r.get('type') == 'followup' else T('rem_normal')))

        def cancel_selected():
            rows = sorted({i.row() for i in table.selectedIndexes()}, reverse=True)
            if not rows:
                return
            rems = sorted(self.reminders, key=lambda x: x['time'])
            for rr in rows:
                if 0 <= rr < len(rems):
                    r = rems[rr]
                    if r in self.reminders:
                        self.reminders.remove(r)
            self._save_reminders()
            refresh()

        def clear_all():
            if self.reminders:
                self.reminders.clear()
                self._save_reminders()
                refresh()

        bottom = QHBoxLayout()
        b_cancel = QPushButton(T('rem_cancel'))
        b_cancel.clicked.connect(cancel_selected)
        b_clear = QPushButton(T('rem_clear'))
        b_clear.clicked.connect(clear_all)
        b_close = QPushButton('✕')
        b_close.clicked.connect(dlg.close)
        bottom.addWidget(b_cancel)
        bottom.addWidget(b_clear)
        bottom.addStretch(1)
        bottom.addWidget(b_close)
        lay.addLayout(bottom)
        refresh()
        dlg.exec()

    # ---------- 久坐提醒 + 打盹 + 输入感知（v6.22，零依赖） ----------
    def _start_idle_system(self):
        """启动输入感知系统：打盹 / 久坐提醒 / 光标跟随 / 唤醒"""
        self._last_input_tick = 0
        self._idle_warned = False
        self._dozing = False
        self.idle_timer = QTimer(self)
        self.idle_timer.timeout.connect(self._check_idle_state)
        self.idle_timer.start(2000)
        self.cursor_timer = QTimer(self)
        self.cursor_timer.timeout.connect(self._cursor_follow)
        self.cursor_timer.start(100)

    def _get_idle_seconds(self):
        """系统空闲秒数（GetLastInputInfo，零依赖）
        （实现已搬至 pet_anim.idle_seconds）"""
        return anim.idle_seconds()
    def _check_idle_state(self):
        """每 2s：打盹切换 / 久坐提醒 / 输入唤醒"""
        if self.sleeping:
            return
        idle = self._get_idle_seconds()
        if self._edge_side is not None or self._edge_popped or self.dragging:
            return
        # 久坐提醒（默认 50 分钟，可配置）
        limit = getattr(self, 'sedentary_minutes', 50) * 60
        if idle >= limit and not self._idle_warned:
            self._idle_warned = True
            is_en = getattr(self, 'language', 'zh') == 'en'
            msg = (f'😴 你已经连续坐 {int(idle // 60)} 分钟了，起来活动一下、喝口水吧！' if not is_en
                   else f'😴 You have been sitting for {int(idle // 60)} minutes. Time to stretch!')
            self.say_plain(msg)
            self._append_chat('桌宠', msg)
        elif idle < 60 and self._idle_warned:
            self._idle_warned = False
        # 打盹：空闲 3 分钟 → 切换睡眠立绘；有输入 → 唤醒（Live2D 模式跳过，模型自带动画）
        if getattr(self, 'display_mode', 'static') == 'live2d':
            return
        if idle >= 180:
            if not self._dozing and self.state == 'idle':
                sleep_img = self._get_state_img('sleep')
                if sleep_img is not None:
                    self._dozing = True
                    self._render_frame(sleep_img)
        elif self._dozing:
            self._dozing = False
            if self.state == 'idle':
                self._show_idle()

    def _cursor_follow(self):
        """光标跟随：立绘轻微侧倾（左右 ±4px），仅待机态"""
        if self.sleeping or self.state != 'idle' or self._edge_side is not None or self._edge_popped or getattr(self, '_dozing', False):
            return
        try:
            center_x = self.geometry().center().x()
            dx = (QCursor.pos().x() - center_x)
            dx = max(-400, min(400, dx)) // 100  # -4 ~ 4
            if dx != getattr(self, '_last_follow_dx', 99):
                self._last_follow_dx = dx
                if dx == 0:
                    if self.state == 'idle':
                        self._show_idle()
                else:
                    self._render_idle_offset(dx)
        except Exception:
            pass

    def _render_idle_offset(self, dx):
        """渲染待机图带水平偏移（光标跟随用）"""
        src = self.full_idle
        if src is None or src.isNull():
            return
        size = self.pet_size
        canvas = QPixmap(size, size)
        canvas.fill(Qt.transparent)
        p = QPainter(canvas)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        scaled = src.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        p.drawPixmap(int((size - scaled.width()) / 2) + dx, int((size - scaled.height()) / 2), scaled)
        p.end()
        self.pet_label.setPixmap(canvas)

    # ---------- 早安日报（v6.22） ----------
    def _start_morning_report(self):
        """每天 08:30 早安日报：问候 + 天气 + 提醒概况"""
        self.morning_timer = QTimer(self)
        self.morning_timer.timeout.connect(self._morning_report)
        self._schedule_morning()

    def _schedule_morning(self):
        now = time.localtime()
        target = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, 8, 30, 0, 0, 0, -1))
        if target <= time.time():
            target += 86400
        self.morning_timer.start(int((target - time.time()) * 1000))

    def _morning_report(self):
        """生成早安日报（天气异步查询，不卡 UI）"""
        self._schedule_morning()
        is_en = getattr(self, 'language', 'zh') == 'en'
        import datetime as _dt
        week = ['一', '二', '三', '四', '五', '六', '日'][_dt.datetime.now().weekday()]
        n_rem = len(self.reminders)
        if is_en:
            base = (f'☀️ Good morning! Today is {_dt.datetime.now().strftime("%m/%d")}. '
                    f'You have {n_rem} reminder(s) set.')
        else:
            base = (f'☀️ 早上好！今天是 {_dt.datetime.now().month}月{_dt.datetime.now().day}日 星期{week}。'
                    f'当前设置了 {n_rem} 条提醒。')
        self.say_plain(base)
        self._append_chat('桌宠', base)
        # 异步查天气（线程 → weather_signal 回主线程）
        city = self.pet_city
        def fetch():
            try:
                import urllib.request, urllib.parse
                url = f'https://wttr.in/{urllib.parse.quote(city)}?format=3&lang=zh'
                req = urllib.request.Request(url, headers={'User-Agent': 'curl/8.0'})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    return resp.read().decode('utf-8').strip()
            except Exception:
                return None
        import threading
        def worker():
            r = fetch()
            if r:
                self.weather_signal.emit(r)
        threading.Thread(target=worker, daemon=True).start()

    def _on_weather_result(self, result):
        """早安日报天气结果（主线程）"""
        if not result:
            return
        is_en = getattr(self, 'language', 'zh') == 'en'
        wmsg = f'🌤 天气：{self.pet_city} {result}' if not is_en else f'🌤 Weather: {result}'
        self.say_plain(wmsg)
        self._append_chat('桌宠', wmsg)

    # ---------- 记忆备份/导入（v6.22） ----------
    def _export_memory_backup(self):
        """导出全部记忆为 JSON 备份"""
        import datetime as _dt
        is_en = getattr(self, 'language', 'zh') == 'en'
        try:
            path = os.path.join(BASE_DIR, f'记忆备份_{_dt.datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self.memory_facts, f, ensure_ascii=False, indent=2)
            self._append_chat('桌宠', f'💾 记忆已备份：{path}' if not is_en else f'💾 Memory backed up: {path}')
        except Exception as e:
            self._append_chat('桌宠', f'备份失败：{e}' if not is_en else f'Backup failed: {e}')

    def _import_memory_backup(self):
        """导入记忆备份（JSON，按 id 去重合并）"""
        from PySide6.QtWidgets import QFileDialog
        is_en = getattr(self, 'language', 'zh') == 'en'
        path, _ = QFileDialog.getOpenFileName(self, '选择备份文件' if not is_en else 'Select backup file', BASE_DIR, 'JSON (*.json)')
        if not path:
            return
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, list):
                raise ValueError('bad format')
            exist = {f.get('id') for f in self.memory_facts}
            added = 0
            for item in data:
                if isinstance(item, dict) and item.get('id') and item.get('content') and item['id'] not in exist:
                    item.setdefault('status', 'active')
                    item.setdefault('importance', 3)
                    self.memory_facts.append(item)
                    added += 1
            self._save_memory()
            self._append_chat('桌宠', f'📥 已导入 {added} 条记忆' if not is_en else f'📥 Imported {added} memories')
        except Exception as e:
            self._append_chat('桌宠', f'导入失败：{e}' if not is_en else f'Import failed: {e}')

    # ---------- 立绘加载与显示 ----------
    def load_character(self, key):
        """加载角色全部立绘（待机/眨眼/扒边/状态/场景）"""
        self.current = key
        self.setWindowTitle(CHARACTERS[key]['name'])
        # 待机整图
        self.full_idle = QPixmap(asset(key, 'idle')) if os.path.exists(asset(key, 'idle')) else None
        # 眨眼图（与 idle 同尺寸画布对齐）
        self.blink_aligned = None
        blink_p = asset(key, 'blink')
        if os.path.exists(blink_p) and self.full_idle is not None:
            b = QPixmap(blink_p)
            canvas = QPixmap(self.full_idle.size())
            canvas.fill(Qt.transparent)
            p = QPainter(canvas)
            off = BLINK_OFFSETS.get(key, (0, 0))
            p.drawPixmap(off[0], off[1], b)
            p.end()
            self.blink_aligned = canvas
        # 扒边立绘（左/右竖条 + 上/下横条）+ 闭眼贴边版（睡觉时用）
        peek_p = asset(key, 'peek')
        self.peek_pixmap = QPixmap(peek_p) if os.path.exists(peek_p) else None
        peek_t = asset(key, 'peek_top')
        self.peek_top_pixmap = QPixmap(peek_t) if os.path.exists(peek_t) else None
        peek_b = asset(key, 'peek_bottom')
        self.peek_bottom_pixmap = QPixmap(peek_b) if os.path.exists(peek_b) else None
        # 闭眼贴边图（睡觉贴边专用；不存在则用完整睡姿兜底）
        ps = asset(key, 'peek_sleep')
        self.peek_sleep_pixmap = QPixmap(ps) if os.path.exists(ps) else None
        pbs = asset(key, 'peek_bottom_sleep')
        self.peek_bottom_sleep_pixmap = QPixmap(pbs) if os.path.exists(pbs) else None
        # 状态/场景立绘：懒加载（首次用到才读盘，加速启动）
        self.state_imgs = {}
        self.scene_imgs = {}
        self._scaled_cache = {}  # 缩放结果缓存（id(pixmap) → 已缩放小图）
        self._restore_display_state()  # 睡觉时显示睡眠立绘，否则待机（切角色不丢睡眠状态）

    def _get_state_img(self, st):
        """懒加载状态立绘（sleep/happy/thinking 等，首次用到才读盘）"""
        if st not in self.state_imgs:
            pth = asset(self.current, st)
            if os.path.exists(pth):
                self.state_imgs[st] = QPixmap(pth)
        return self.state_imgs.get(st)

    def _get_scene_img(self, key):
        """懒加载场景立绘（吃饭/阅读/音乐等，首次用到才读盘）"""
        if key not in self.scene_imgs:
            pth = asset(self.current, key)
            if os.path.exists(pth):
                self.scene_imgs[key] = QPixmap(pth)
        return self.scene_imgs.get(key)

    def _render_frame(self, pixmap=None):
        """渲染一帧到 pet_label（默认待机图，等比缩放居中；缩放结果缓存复用）"""
        src = pixmap if pixmap is not None else self.full_idle
        if src is None or src.isNull():
            return
        size = self.pet_size
        key = id(src)
        if key not in self._scaled_cache:
            self._scaled_cache[key] = src.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        scaled = self._scaled_cache[key]
        canvas = QPixmap(size, size)
        canvas.fill(Qt.transparent)
        p = QPainter(canvas)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawPixmap(int((size - scaled.width()) / 2), int((size - scaled.height()) / 2), scaled)
        p.end()
        self.pet_label.setPixmap(canvas)

    def _show_idle(self):
        """待机显示（贴边未弹出 → 扒边立绘；Live2D 模式由模型代替）"""
        if self.sleeping:
            return  # 睡眠时不切回待机（防光标跟随/眨眼等 timer 覆盖睡眠立绘）
        if getattr(self, 'display_mode', 'static') == 'live2d':
            return
        if self._edge_side is not None and not self._edge_popped:
            if self._edge_side in ('left', 'right') and self.peek_pixmap is not None:
                self._show_peek()
                return
            if self._edge_side in ('top', 'bottom'):
                self._show_peek()
                return
        # 恢复正常 pet_label 尺寸
        if self.pet_label.width() != self.pet_size or self.pet_label.height() != self.pet_size:
            self.pet_label.setFixedSize(self.pet_size, self.pet_size)
        self._render_frame(self.full_idle)

    def _restore_display_state(self):
        """恢复显示状态：睡眠→睡眠立绘，否则→待机（贴边拖出/弹出后用）
        （实现已搬至 pet_anim.restore_display_state）"""
        return anim.restore_display_state(self)
    def _show_peek(self):
        """扒边立绘（四方向：左右竖条镜像对齐，上下横条；Live2D 模式由模型代替）"""
        if getattr(self, 'display_mode', 'static') == 'live2d':
            return
        size = self.pet_size
        side = self._edge_side
        if side in ('left', 'right'):
            if self.sleeping:
                # 睡觉贴边：优先用专业闭眼贴边图；无则完整睡姿（左靠左缘，右翻转靠右缘）
                if self.peek_sleep_pixmap is not None and not self.peek_sleep_pixmap.isNull():
                    src = self.peek_sleep_pixmap
                    if side == 'right':
                        src = src.transformed(QTransform().scale(-1, 1))
                    canvas = QPixmap(size, size)
                    canvas.fill(Qt.transparent)
                    p = QPainter(canvas)
                    p.setRenderHint(QPainter.SmoothPixmapTransform)
                    scaled = src.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    draw_x = 0 if side == 'left' else size - scaled.width()
                    p.drawPixmap(draw_x, int((size - scaled.height()) / 2), scaled)
                    p.end()
                    self.pet_label.setPixmap(canvas)
                    return
                img = self._get_state_img('sleep')
                if img is None or img.isNull():
                    return
                src = img
                if side == 'right':
                    src = src.transformed(QTransform().scale(-1, 1))
                canvas = QPixmap(size, size)
                canvas.fill(Qt.transparent)
                p = QPainter(canvas)
                p.setRenderHint(QPainter.SmoothPixmapTransform)
                scaled = src.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                draw_x = 0 if side == 'left' else size - scaled.width()
                p.drawPixmap(draw_x, int((size - scaled.height()) / 2), scaled)
                p.end()
                self.pet_label.setPixmap(canvas)
                return
            if self.peek_pixmap is None or self.peek_pixmap.isNull():
                return
            src = self.peek_pixmap
            if side == 'right':
                src = src.transformed(QTransform().scale(-1, 1))
            canvas = QPixmap(size, size)
            canvas.fill(Qt.transparent)
            p = QPainter(canvas)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            scaled = src.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            draw_x = 0 if side == 'left' else size - scaled.width()
            p.drawPixmap(draw_x, int((size - scaled.height()) / 2), scaled)
            p.end()
            self.pet_label.setPixmap(canvas)
        else:
            # 上下：横构图立绘
            if self.sleeping:
                # 睡觉贴边：优先用专业闭眼贴边图；无则完整睡姿底部对齐
                if self.peek_bottom_sleep_pixmap is not None and not self.peek_bottom_sleep_pixmap.isNull():
                    img = self.peek_bottom_sleep_pixmap
                else:
                    img = self._get_state_img('sleep')
            elif side == 'top':
                img = self.peek_top_pixmap
            else:
                img = self.peek_bottom_pixmap
            if img is None or img.isNull():
                return
            # 上下贴边时 pet_label 放大为窗口尺寸
            self.pet_label.setFixedSize(self.width(), self.height())
            canvas = QPixmap(self.width(), self.height())
            canvas.fill(Qt.transparent)
            p = QPainter(canvas)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            scaled = img.scaled(self.width(), self.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            # 缩小到 65%，避免过大压迫感
            scaled = scaled.scaled(int(scaled.width() * 0.65), int(scaled.height() * 0.65),
                                   Qt.KeepAspectRatio, Qt.SmoothTransformation)
            # 对齐：top 立绘手在图片上边缘 → 顶部对齐（手贴屏幕顶缘）
            #      bottom 立绘手在图片下边缘 → 底部对齐（手贴屏幕底缘）
            if side == 'top':
                draw_y = 0
            else:
                draw_y = self.height() - scaled.height()
            p.drawPixmap(int((self.width() - scaled.width()) / 2), draw_y, scaled)
            p.end()
            self.pet_label.setPixmap(canvas)

    def _show_state_image(self, st):
        """显示状态立绘（sleep/happy/thinking/scared/...；Live2D 模式由模型代替）
        （实现已搬至 pet_anim.show_state_image）"""
        return anim.show_state_image(self, st)
    # ---------- 气泡（预设短台词 ≤20 字，不挡脸） ----------
    def _place_bubble(self):
        """气泡悬浮在窗口顶部（pet_label 上方区域）"""
        self.bubble.raise_()  # 置顶：防止被 pet_label（后创建，z-order 更高）遮挡
        # v6.51：气泡是窗口的子控件，而扒边/隐藏模式会把窗口缩窄（左右扒边缩到 pet_size 宽），
        # 原先只做居中、不缩气泡宽度 → 长句被窗口硬裁掉半截。这里按窗口实际宽度夹一下。
        avail = max(40, self.width() - 8)
        bw = min(max(self.bubble.sizeHint().width(), 40), 380, avail)
        bh = self.bubble.sizeHint().height()
        bx = max(0, (self.width() - bw) // 2)
        by = 6
        self.bubble.setGeometry(bx, by, bw, bh)

    def say_plain(self, text, immediate=False):
        """气泡显示短文本。immediate=True 时直接完整显示（状态提示用，避免打字机卡顿误导）
        v6.25.1 非主线程调用自动转发主线程（防 Qt 跨线程崩溃）"""
        text = self._strip_emotion_tags(str(text))[0]  # v6.40 出口统一剥 emotion 标签
        if not text:
            return
        if threading.current_thread() is not threading.main_thread():
            QTimer.singleShot(0, lambda t=text, i=immediate: self.say_plain(t, i))
            return
        if immediate:
            self.type_timer.stop()
            self.type_buffer = str(text)
            self.type_index = len(self.type_buffer)
            self.bubble.setText(str(text))
            self.bubble.show()
            self._place_bubble()
            self.bubble_hide_timer.start(max(1500, len(self.type_buffer) * 80 + 1000))
            return
        self.type_buffer = str(text)
        self.type_index = 0
        self.bubble.setText('')
        self.bubble.show()
        self._place_bubble()
        self.type_timer.start(40)
        self.bubble_hide_timer.start(max(1500, len(self.type_buffer) * 80 + 1000))

    def _type_next(self):
        """打字机：逐字显示"""
        if self.type_index < len(self.type_buffer):
            self.type_index += 1
            self.bubble.setText(self.type_buffer[:self.type_index])
            self._place_bubble()
        else:
            self.type_timer.stop()

    def _hide_bubble(self):
        self.bubble.hide()
        self.type_timer.stop()

    def show_emotion(self, emoji, ms=2000):
        """头顶 emoji 气泡（情绪表达，不挡脸）"""
        self.bubble.setText(str(emoji))
        self.bubble.show()
        self._place_bubble()
        self.bubble_hide_timer.start(ms)

    # ---------- 说话/思考 ----------
    def _char_lines(self, key):
        """按当前语言取角色台词（greetings/think_lines/happy_lines/scared_lines）"""
        conf = CHARACTERS[self.current]
        if getattr(self, 'language', 'zh') == 'en':
            return conf.get(key + '_en') or conf.get(key) or []
        return conf.get(key) or []

    def say_random(self):
        """随机说一句问候（实现已搬至 pet_anim.say_random）"""
        return anim.say_random(self)
    def do_thinking(self):
        """思考状态（3 秒后恢复）"""
        if self.sleeping:
            return
        self.state = 'thinking'
        self.phase = 0
        lines = self._char_lines('think_lines')
        text = random.choice(lines) if lines else 'Hmm…'
        self.say_plain(text)
        self._append_chat('桌宠', text)
        self._show_state_image('thinking')
        if self.thinking_timer is not None:
            self.thinking_timer.stop()
        self.thinking_timer = QTimer(self)
        self.thinking_timer.setSingleShot(True)
        self.thinking_timer.timeout.connect(self._end_thinking)
        self.thinking_timer.start(3000)

    def _end_thinking(self):
        if not self.sleeping and self.state == 'thinking':
            self.state = 'idle'
            self._show_idle()

    def _restore_state_after_emotion(self):
        """情绪立绘结束后恢复待机（实现已搬至 pet_anim.restore_after_emotion）"""
        return anim.restore_after_emotion(self)
    # ---------- 场景动作 ----------
    def play_scene(self, key):
        """播放场景动作立绘（6 秒后恢复待机）
        （实现已搬至 pet_anim.play_scene）"""
        return anim.play_scene(self, key)
    def _end_scene(self):
        """场景动作结束：恢复待机（实现已搬至 pet_anim.end_scene）"""
        return anim.end_scene(self)
    # ---------- 眨眼 ----------
    def _do_blink(self):
        """眨眼定时器回调（实现已搬至 pet_anim.blink_tick）"""
        return anim.blink_tick(self)
    def _blend_end(self):
        """眨眼结束收尾（实现已搬至 pet_anim.blend_end）"""
        return anim.blend_end(self)
    # ---------- 聊天窗口 ----------
    def _record_api_usage(self, resp, fallback_model=''):
        """从 API 响应解析 usage 并记录（v6.18 自监控）

        fallback_model：流式响应体不带 model 字段时，用本次实际请求的模型补上
        （原先流式只传 usage → model 为空串 → 费用一律按兜底价算）"""
        try:
            dbg = os.path.join(BASE_DIR, '_apistats_debug.log')
            with open(dbg, 'a', encoding='utf-8') as _f:
                _f.write(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] "
                         f"type={type(resp).__name__} keys={list(resp.keys())[:6] if isinstance(resp, dict) else '-'} "
                         f"usage={'有' if isinstance(resp, dict) and resp.get('usage') else '无'}\n")
        except Exception:
            pass
        try:
            if not isinstance(resp, dict):
                return
            usage = resp.get('usage')
            if not usage:
                return
            model = resp.get('model') or fallback_model or ''
            cost = self.api_stats.record(usage, model)
            if cost:
                self.cost_bubble_signal.emit(cost)  # v6.30 费用气泡
        except Exception:
            pass

    def _show_api_stats_history(self):
        """显示最近 API 调用历史（消息框）"""
        from PySide6.QtWidgets import QMessageBox
        st = self.api_stats
        with st.lock:
            calls = list(reversed(st.calls[-20:]))
            today = dict(st.today)
            total = dict(st.total)
        lines = [f"今日 {today.get('count',0)}次/{today.get('total',0)}tok/{today.get('cost',0):.3f}元 · 累计 {total.get('count',0)}次/{total.get('total',0)}tok/{total.get('cost',0):.3f}元", '']
        if not calls:
            lines.append('（暂无调用记录——发消息后自动统计）')
        for c in calls:
            flag = ' ⚠价格未知' if c.get('price_unknown') else ''
            lines.append(f"{c['time']} {c['model']} in{c['prompt']} out{c['completion']} 缓存{c['cache_hit']}hit {c['cost']:.4f}元{flag}")
        QMessageBox.information(self, 'API 统计历史', '\n'.join(lines))

    def _show_model_stats(self):
        """按模型汇总用量与费用（含价格未知提示）——看清钱花在哪个模型上"""
        from PySide6.QtWidgets import QMessageBox
        rows = self.api_stats.model_breakdown()
        if not rows:
            QMessageBox.information(self, '按模型统计', '（暂无调用记录——发消息后自动统计）')
            return
        lines = ['按模型汇总（终身口径）', '']
        for r in rows:
            lines.append('· %s' % r.get('model', '?'))
            lines.append('    %d 次 · 输入 %s / 输出 %s · 费用 %.4f 元'
                         % (r.get('count', 0), format(r.get('prompt', 0), ','),
                            format(r.get('completion', 0), ','), float(r.get('cost') or 0)))
            if r.get('unknown'):
                lines.append('    ⚠ 其中 %d 次价格未知（按兜底价估算，去「模型管理」把价格补上）'
                             % r['unknown'])
        tot = sum(float(r.get('cost') or 0) for r in rows)
        unk = sum(int(r.get('unknown') or 0) for r in rows)
        lines.append('')
        lines.append('合计 %.4f 元' % tot
                     + ('；其中 %d 次是价格未知的估算' % unk if unk else ''))
        QMessageBox.information(self, '按模型统计', '\n'.join(lines))

    def _toggle_api_stats_window(self):
        """开关 API 统计悬浮窗（透明置顶小窗，实时刷新 + 缓存命中率图表）"""
        if self._api_stats_win is not None:
            try:
                self._api_stats_win.close()
            except Exception:
                pass
            self._api_stats_win = None
            return
        from PySide6.QtWidgets import QVBoxLayout as _VL, QProgressBar
        win = QWidget()
        win.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                           Qt.Tool | Qt.NoDropShadowWindowHint)
        win.setAttribute(Qt.WA_TranslucentBackground)
        win.setStyleSheet("""
            QWidget#ap { background: rgba(15,20,32,0.92); border: 1px solid #2c3a52;
                         border-radius: 10px; }
            QLabel { color: #dce3f0; font-size: 11px; background: transparent; }
            QLabel#t { color: #7fb2ff; font-size: 12px; font-weight: bold; }
            QLabel#v { color: #6ecb7a; font-size: 11px; }
            QLabel#d { color: #8aa; font-size: 10px; }
            QProgressBar { background: rgba(255,255,255,0.08); border: none; border-radius: 4px;
                           text-align: center; color: #dce3f0; font-size: 10px; }
            QProgressBar::chunk { background: #6ecb7a; border-radius: 4px; }
        """)
        panel = QWidget(win)
        panel.setObjectName('ap')
        v = _VL(panel)
        v.setContentsMargins(10, 6, 10, 6)
        v.setSpacing(3)
        title = QLabel('\U0001F4CA API 统计')
        title.setObjectName('t')
        v.addWidget(title)

        def _fmt(n):
            try:
                n = float(n or 0)
            except Exception:
                return '0'
            if n >= 1e8:
                return f'{n/1e8:.1f}亿'
            if n >= 1e4:
                return f'{n/1e4:.1f}万'
            if n >= 1e3:
                return f'{n/1e3:.1f}k'
            return f'{int(n)}'

        l_last = QLabel('最近: —'); l_last.setObjectName('v')
        l_cache = QLabel('缓存: —'); l_cache.setObjectName('d')
        cache_bar = QProgressBar()
        cache_bar.setRange(0, 100)
        cache_bar.setValue(0)
        cache_bar.setFixedHeight(10)
        l_today = QLabel('今日: —'); l_today.setObjectName('v')
        l_total = QLabel('累计: —'); l_total.setObjectName('v')
        l_app = QLabel('来源: —'); l_app.setObjectName('d')
        v.addWidget(l_last); v.addWidget(l_cache); v.addWidget(cache_bar)
        v.addWidget(l_today); v.addWidget(l_total); v.addWidget(l_app)

        def refresh():
            st = self.api_stats
            with st.lock:
                last = st.last
                today = dict(st.today)
                total = dict(st.total)
            if last:
                warn = '  ⚠ 价格未知（按兜底价估算）' if last.get('price_unknown') else ''
                l_last.setText(f"最近: {last['model']} {_fmt(last['prompt'])}in/{_fmt(last['completion'])}out "
                               f"{last['cost']:.4f}元{warn}")
            hit = today.get('cache_hit', 0) or 0
            miss = today.get('cache_miss', 0) or 0
            l_cache.setText(f"缓存: {_fmt(hit)} 命中 / {_fmt(miss)} 未命中")
            total_in = hit + miss
            rate = int(hit / total_in * 100) if total_in else 0
            cache_bar.setValue(rate)
            cache_bar.setFormat(f'缓存命中率 {rate}%')
            l_today.setText(f"今日: {today.get('count',0)}次 · {_fmt(today.get('total',0))} tok · {today.get('cost',0):.4f}元")
            l_total.setText(f"累计: {total.get('count',0)}次 · {_fmt(total.get('total',0))} tok · {total.get('cost',0):.4f}元")
            by_app = today.get('by_app', {})
            if by_app:
                parts = [f"{k} {v['count']}次/{_fmt(v['total'])}tok" for k, v in by_app.items()]
                l_app.setText('来源: ' + ' · '.join(parts))
            else:
                l_app.setText('来源: —')

        timer = QTimer(win)  # 父对象 win，防止被 GC 导致悬浮窗不刷新
        timer.timeout.connect(refresh)
        timer.start(1000)

        _drag = {'on': False, 'x': 0, 'y': 0}
        def _press(e):
            if e.button() == Qt.LeftButton:
                _drag['on'] = True
                _drag['x'] = int(e.globalPosition().x() - win.x())
                _drag['y'] = int(e.globalPosition().y() - win.y())
        def _move(e):
            if _drag['on']:
                win.move(int(e.globalPosition().x() - _drag['x']),
                         int(e.globalPosition().y() - _drag['y']))
        def _release(e):
            _drag['on'] = False
        panel.mousePressEvent = _press
        panel.mouseMoveEvent = _move
        panel.mouseReleaseEvent = _release

        win.setContextMenuPolicy(Qt.CustomContextMenu)
        def _menu(pos):
            m = QMenu(win)
            a = m.addAction('关闭统计')
            a.triggered.connect(lambda: self._toggle_api_stats_window())
            m.exec(win.mapToGlobal(pos))
        win.customContextMenuRequested.connect(_menu)

        panel.setFixedWidth(320)
        win.setFixedSize(320, 142)
        win.move(40, 40)
        win.show()
        refresh()
        self._api_stats_win = win

    def _new_bubble(self, who, ts, is_user=False, text=''):
        """创建消息气泡（头部名字+时间+操作按钮 + 空内容区），追加到消息流（v6.19 微信式左右布局）
        is_user=True 时名字靠右（用户消息），False 时靠左（桌宠/AI 消息）"""
        bubble = QFrame()
        v = QVBoxLayout(bubble)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(6)
        name = QLabel(who)
        name_color = self.theme.get('name_user') if is_user else self.theme.get('name_ai')
        name.setStyleSheet(f'color:{name_color};font-size:11px;font-weight:bold;background:transparent;')
        tl = QLabel(ts)
        tl.setStyleSheet('color:#667;font-size:10px;background:transparent;')
        if is_user:
            head.addStretch(1)
            head.addWidget(name)
            head.addWidget(tl)
        else:
            head.addWidget(name)
            head.addWidget(tl)
            head.addStretch(1)
        # 操作按钮：一键复制 / 存为图片（hover 消息才显示，v6.19e；不污染对话历史）
        self._attach_bubble_actions(bubble, text)
        v.addLayout(head)
        content = QVBoxLayout()
        content.setSpacing(4)
        v.addLayout(content)
        self.chat_history_layout.insertWidget(self.chat_history_layout.count() - 1, bubble)
        return bubble, content

    def _bubble_text_label(self, html_text, is_user=False):
        """消息文本标签：富文本（<b>/<i>/<br> 等），自动换行，可选中复制；
        用户/AI 不同背景色+对齐（v6.19 对比度增强 + v6.23 主题变量）
        （实现已搬至 pet_bubble.bubble_text_label）"""
        return pb.bubble_text_label(html_text, self.theme, is_user=is_user)
    def _copy_message_text(self, text):
        """复制单条消息文本到剪贴板（用气泡提示，不污染对话历史）"""
        try:
            if _write_clipboard_text(str(text)):
                self.say_plain('✅ 已复制该消息', immediate=True)
            else:
                self.say_plain('复制失败', immediate=True)
        except Exception:
            self.say_plain('复制失败', immediate=True)

    def _save_bubble_image(self, bubble):
        """把消息气泡渲染成 PNG 图片保存（合成深色背景，与聊天面板风格一致）"""
        from PySide6.QtWidgets import QFileDialog
        try:
            default = os.path.join(os.path.expanduser('~'), 'Desktop', '桌宠消息.png')
            path, _ = QFileDialog.getSaveFileName(self, '保存消息为图片', default, 'PNG 图片 (*.png)')
            if not path:
                return
            pm = bubble.grab()
            if pm.isNull():
                self.say_plain('截图失败', immediate=True)
                return
            bg = QPixmap(pm.size())
            bg.fill(QColor(20, 20, 30))
            p = QPainter(bg)
            p.drawPixmap(0, 0, pm)
            p.end()
            if bg.save(path):
                self.say_plain(f'✅ 已保存：{os.path.basename(path)}', immediate=True)
            else:
                self.say_plain('保存失败', immediate=True)
        except Exception as e:
            self.say_plain(f'保存失败：{e}', immediate=True)

    def _check_code_blocks(self, text):
        """自动检查回复中 Python 代码块语法（拆至 code_checker.check_python_blocks）
        （实现已搬至 pet_bubble.check_code_blocks）"""
        return pb.check_code_blocks(text)
    def _maybe_append_code_warning(self):
        """回复渲染完成后，若有语法错误的代码块，追加黄色提示（不阻止显示，仅提醒）"""
        warns = getattr(self, '_code_check_warning', None)
        if not warns:
            return
        parts = '；'.join(f'第{n}个: {m}' for n, m in warns[:3])
        if len(warns) > 3:
            parts += f'…（共{len(warns)}处）'
        warn = QLabel(f'⚠️ 自动检查：上述回复有 {len(warns)} 处 Python 代码块语法错误（{parts}），建议让我重新生成。')
        warn.setWordWrap(True)
        warn.setStyleSheet('color:#e8c76a; font-size:11px; background:transparent; padding:2px 0;')
        self._chat_type_content.addWidget(warn)
        self._chat_scroll_bottom()

    def _render_md_into(self, content_layout, text):
        """把 markdown 文本分块渲染进内容区：代码/表格成卡片，连续文本合为一个段落（v6.17）
        （实现已搬至 pet_bubble.render_md_into）"""
        return pb.render_md_into(content_layout, text, self.theme)
    @staticmethod
    def _split_rich_blocks(text):
        """把 markdown 拆成渲染块（拆至 chat_render.split_rich_blocks）
        （实现已搬至 pet_bubble.split_blocks）"""
        return pb.split_blocks(text)
    def _render_one_block(self, content_layout, kind, content):
        """渲染单个块到内容区（文本/代码卡片/表格卡片）
        （实现已搬至 pet_bubble.render_one_block）"""
        return pb.render_one_block(content_layout, kind, content, self.theme)
    @staticmethod
    def _md_table_from_text(text):
        """把纯文本表格块转 HTML（供 _TableCard 使用）
        （实现已搬至 pet_bubble.md_table_from_text）"""
        return pb.md_table_from_text(text)
    def _chat_scroll_bottom(self):
        """消息流滚动到底部"""
        sb = self.chat_history_scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _clear_chat_history(self):
        """清空消息流（保留底部弹簧）"""
        while self.chat_history_layout.count() > 1:
            item = self.chat_history_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._status_widget = None

    def _update_more_button(self):
        """有更早历史时显示'显示更多'按钮"""
        if hasattr(self, 'chat_more_btn'):
            self.chat_more_btn.setVisible(self._display_offset > 0)

    def _load_more_history(self):
        """加载更早的显示历史（每次 50 条，插入到面板顶部）"""
        if self._display_offset <= 0:
            self._update_more_button()
            return
        start = max(0, self._display_offset - 50)
        chunk = self.display_msgs[start:self._display_offset]
        self._display_offset = start
        sb = self.chat_history_scroll.verticalScrollBar()
        prev = sb.value()
        new_bubbles = []
        for m in chunk:
            ts = m.get('ts', '')
            who = m.get('who', '桌宠')
            bubble, content = self._new_bubble_at_top(who, ts, is_user=(who == '我'), text=str(m.get('text', '')))
            self._render_md_into(content, str(m.get('text', '')))
            new_bubbles.append(bubble)
        self._update_more_button()
        # 保持滚动位置（顶部插入后原内容下移，滚动条值加上新插入高度）
        added = sum(b.sizeHint().height() for b in new_bubbles) + 8 * len(new_bubbles)
        sb.setValue(prev + added)

    def _new_bubble_at_top(self, who, ts, is_user=False, text=''):
        """在消息流顶部插入气泡（历史加载用，v6.19 与 _new_bubble 同构：左右布局+操作按钮）"""
        bubble = QFrame()
        v = QVBoxLayout(bubble)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(6)
        name = QLabel(who)
        name_color = self.theme.get('name_user') if is_user else self.theme.get('name_ai')
        name.setStyleSheet(f'color:{name_color};font-size:11px;font-weight:bold;background:transparent;')
        tl = QLabel(ts)
        tl.setStyleSheet('color:#667;font-size:10px;background:transparent;')
        if is_user:
            head.addStretch(1)
            head.addWidget(name)
            head.addWidget(tl)
        else:
            head.addWidget(name)
            head.addWidget(tl)
            head.addStretch(1)
        if text:
            cp = QLabel('⧉')
            cp.setStyleSheet('color:#8aa;font-size:11px;background:transparent;padding:0 2px;')
            cp.setCursor(Qt.PointingHandCursor)
            cp.setToolTip('复制该消息')
            cp.mousePressEvent = lambda e, t=text: self._copy_message_text(t)
            cp.hide()
            head.addWidget(cp)
            sv = QLabel('🖼')
            sv.setStyleSheet('color:#8aa;font-size:11px;background:transparent;padding:0 2px;')
            sv.setCursor(Qt.PointingHandCursor)
            sv.setToolTip('存为图片')
            sv.mousePressEvent = lambda e, b=bubble: self._save_bubble_image(b)
            sv.hide()
            head.addWidget(sv)
            bubble._action_btns = [cp, sv]
            bubble.enterEvent = lambda e, b=bubble: [x.show() for x in getattr(b, '_action_btns', [])]
            bubble.leaveEvent = lambda e, b=bubble: [x.hide() for x in getattr(b, '_action_btns', [])]
        v.addLayout(head)
        content = QVBoxLayout()
        content.setSpacing(4)
        v.addLayout(content)
        self.chat_history_layout.insertWidget(0, bubble)
        return bubble, content

    def _append_chat(self, who, text):
        """追加一条聊天记录（纯文本路径：系统提示/用户消息，不解析 markdown；多行自动换行）
        v6.25.1 非主线程调用自动转发主线程——修复 AI 后台线程直接操作 Qt 控件导致的崩溃（Qt6Gui.dll 访问违规）"""
        text = self._strip_emotion_tags(str(text))[0]  # v6.40 出口统一剥 emotion 标签
        if threading.current_thread() is not threading.main_thread():
            QTimer.singleShot(0, lambda w=who, t=text: self._append_chat(w, t))
            return
        import datetime as _dt
        ts = _dt.datetime.now().strftime('%m-%d %H:%M')
        self.display_msgs.append({'who': who, 'text': str(text), 'ts': ts})
        if len(self.display_msgs) > 300:
            self.display_msgs = self.display_msgs[-300:]
        safe = str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br>')
        bubble, content = self._new_bubble(who, ts, is_user=(who == '我'), text=str(text))
        content.addWidget(self._bubble_text_label(safe, is_user=(who == '我')))
        self._chat_scroll_bottom()

    def _append_chat_md(self, who, text):
        """追加一条聊天记录（AI 回复用，markdown 分块渲染：代码/表格成卡片）
        v6.25.1 非主线程调用自动转发主线程（防 Qt 跨线程崩溃）"""
        if threading.current_thread() is not threading.main_thread():
            QTimer.singleShot(0, lambda w=who, t=text: self._append_chat_md(w, t))
            return
        import datetime as _dt
        ts = _dt.datetime.now().strftime('%m-%d %H:%M')
        self.display_msgs.append({'who': who, 'text': str(text), 'ts': ts})
        if len(self.display_msgs) > 300:
            self.display_msgs = self.display_msgs[-300:]
        bubble, content = self._new_bubble(who, ts, is_user=False, text=str(text))
        self._render_md_into(content, str(text))
        self._chat_scroll_bottom()

    def _attach_bubble_actions(self, bubble, text):
        """给消息气泡补复制/存图按钮（hover 显示）。v6.40：流式气泡创建时 text 为空，流式结束后补上"""
        if not text or getattr(bubble, '_action_btns', None):
            return
        v = bubble.layout()
        if v is None or v.count() == 0:
            return
        head = v.itemAt(0).layout()
        if head is None:
            return
        cp = QLabel('⧉')
        cp.setStyleSheet('color:#8aa;font-size:11px;background:transparent;padding:0 2px;')
        cp.setCursor(Qt.PointingHandCursor)
        cp.setToolTip('复制该消息')
        cp.mousePressEvent = lambda e, t=text: self._copy_message_text(t)
        cp.hide()
        head.addWidget(cp)
        sv = QLabel('🖼')
        sv.setStyleSheet('color:#8aa;font-size:11px;background:transparent;padding:0 2px;')
        sv.setCursor(Qt.PointingHandCursor)
        sv.setToolTip('存为图片')
        sv.mousePressEvent = lambda e, b=bubble: self._save_bubble_image(b)
        sv.hide()
        head.addWidget(sv)
        bubble._action_btns = [cp, sv]
        bubble.enterEvent = lambda e, b=bubble: [x.show() for x in getattr(b, '_action_btns', [])]
        bubble.leaveEvent = lambda e, b=bubble: [x.hide() for x in getattr(b, '_action_btns', [])]

    @staticmethod
    def _md_to_html(text):
        """轻量 Markdown → HTML（拆至 chat_render.md_to_html）
        （实现已搬至 pet_bubble.to_html）"""
        return pb.to_html(text)
    @staticmethod
    def _md_table(m):
        """Markdown 表格块 → HTML table（拆至 chat_render.md_table）
        （实现已搬至 pet_bubble.to_table_html）"""
        return pb.to_table_html(m)
    def _remove_status_line(self):
        """删除状态行 widget（⏳/思考中）"""
        if self._status_widget is not None:
            try:
                self.chat_history_layout.removeWidget(self._status_widget)
                self._status_widget.deleteLater()
            except Exception:
                pass
            self._status_widget = None
            return True
        return False

    def _update_ai_status(self, text):
        """更新 AI 处理状态（删旧状态行 + 追加新状态行，不残留）"""
        self._remove_status_line()
        self._status_widget = QLabel(f'⏳ {text}')
        self._status_widget.setWordWrap(True)
        self._status_widget.setStyleSheet('color:#8aa; font-size:11px; background:transparent; padding:2px 0;')
        self.chat_history_layout.insertWidget(self.chat_history_layout.count() - 1, self._status_widget)
        self._chat_scroll_bottom()

    def _panel_qss(self):
        """按当前主题变量生成聊天面板样式（v6.23 主题系统）"""
        t = self.theme
        return f"""
            QFrame {{ background-color: {t['panel_bg']}; border-radius: 12px; }}
            QTextBrowser {{ background: transparent; color: {t['text']}; border: none; font-size: 12px; padding: 6px; }}
            QTextEdit {{ background: {t['input_bg']}; color: #fff; border: none; border-radius: 8px; padding: 6px 10px; font-size: 12px; }}
            QTextEdit:focus {{ background: {t['input_focus']}; }}
            QTextEdit viewport {{ background: transparent; }}
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{ background: {t['scroll_bg']}; width: 8px; border-radius: 4px; margin: 0; }}
            QScrollBar::handle:vertical {{ background: {t['scroll_handle']}; border-radius: 4px; min-height: 20px; }}
            QScrollBar::handle:vertical:hover {{ background: {t['scroll_handle_hover']}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """

    def _set_theme_data(self, tname):
        """只更新主题数据（不碰 GUI）——可在后台线程调用，与 apply_theme_named 共用"""
        self.current_theme = tname
        self.theme = dict(DEFAULT_THEME)
        if tname != 'default':
            self.theme.update(self.plugin_mgr.theme_vars(tname))

    def apply_theme_named(self, tname):
        """切换主题（右键菜单「形象 → 主题」入口；AI 工具 set_theme 共用数据逻辑）。

        v6.51：此前只有 AI 工具能切主题，右键菜单与设置窗口都没入口——装了主题插件的
        用户自己反而用不上。这里补上入口，并让气泡一起跟随主题。
        """
        try:
            available = ['default'] + [str(x) for x in self.plugin_mgr.theme_names()]
        except Exception:
            available = ['default']
        if tname not in available:
            return False
        self._set_theme_data(tname)
        self._apply_theme()
        self._save_cfg_value('theme', tname)
        self.say_plain(('已切换主题：%s' % tname) if tname != 'default' else '已切回默认主题')
        return True

    def _apply_bubble_theme(self):
        """说话气泡跟随主题（v6.51）：颜色取自主题，缺键时回退原来的浅色外观
        （实现已搬至 pet_bubble.apply_say_bubble_theme）"""
        try:
            pb.apply_say_bubble_theme(self.bubble, self.theme)
        except Exception as e:
            log.debug('气泡主题应用失败：%s', e)
    def _apply_theme(self):
        """把当前主题应用到面板与气泡（v6.25.1 必须主线程调用——修复 AI 后台线程跨线程 setStyleSheet 崩溃）"""
        try:
            self.chat_panel.setStyleSheet(self._panel_qss())
        except Exception as e:
            log.warning('主题样式应用失败：%s', e)
        self._apply_bubble_theme()

    def _sync_window_to_panel(self):
        """窗口尺寸跟随面板（保持立绘+空隙差值 320），并钳制在屏幕工作区内——
        修复：面板被拖大后重新显示，窗口 440x560 装不下导致下半部分（输入框）被截断（v6.19c）"""
        try:
            scr = self.screen() or QApplication.primaryScreen()
            avail = scr.availableGeometry()
            pw = max(300, self.chat_panel.width())
            ph = max(120, self.chat_panel.height())
            win_w = pw + 20    # 水平：面板居中 + 左右边距各 10
            win_h = ph + 320   # 垂直：立绘 260 + 底部空隙 60（初始窗口 560 - 面板 240）
            # 屏幕放不下时：压缩面板高度（优先保证窗口不超屏、不截断）
            max_ph = avail.height() - 320
            if max_ph >= 120 and ph > max_ph:
                ph = int(max_ph)
                self.chat_panel.setFixedHeight(ph)
                win_h = ph + 320
            win_w = min(win_w, avail.width())
            win_h = min(win_h, avail.height())
            self.setFixedSize(win_w, win_h)
            nx = max(avail.left(), min(self.x(), avail.right() - win_w))
            ny = max(avail.top(), min(self.y(), avail.bottom() - win_h))
            self.move(nx, ny)
        except Exception:
            pass

    def toggle_chat_panel(self):
        """显示/隐藏聊天面板（v6.19c 显示时窗口跟随面板尺寸，不再截断）"""
        if self.chat_panel.isVisible():
            self.chat_panel.hide()
            self.setFixedSize(440, 340)
        else:
            self.chat_panel.show()
            self._sync_window_to_panel()

    def _chat_panel_press(self, event):
        """聊天面板按下：下两角（同时改宽高）+ 左/右/下边拖拽（v6.19c 恢复下方两角，上边禁用）"""
        x = event.position().x()
        y = event.position().y()
        w = self.chat_panel.width()
        h = self.chat_panel.height()
        edge = 14
        self._chat_drag_start_x = event.globalPosition().x()
        self._chat_drag_start_y = event.globalPosition().y()
        self._chat_drag_start_w = w
        self._chat_drag_start_h = h
        self._chat_drag_side = None
        left, right = x < edge, x > w - edge
        bottom = y > h - edge
        if left and bottom:
            self._chat_drag_mode = 'corner_bl'   # 左下角：向左+向下延伸
        elif right and bottom:
            self._chat_drag_mode = 'corner_br'   # 右下角：向右+向下延伸
        elif left:
            self._chat_drag_mode = 'h'
            self._chat_drag_side = 'left'        # 拖左边 → 左边界向左延伸
        elif right:
            self._chat_drag_mode = 'h'
            self._chat_drag_side = 'right'       # 拖右边 → 右边界向右延伸
        elif bottom:
            self._chat_drag_mode = 'v_bottom'    # 拖下边 → 下边界向下延伸
        else:
            self._chat_drag_mode = None
        event.accept()

    def _chat_panel_move(self, event):
        """面板鼠标移动：拖左→左延伸（窗口左移），拖右→右延伸，拖下→下延伸；悬停边缘显示光标（v6.19b）"""
        mode = self._chat_drag_mode
        if mode:
            dx = event.globalPosition().x() - self._chat_drag_start_x
            dy = event.globalPosition().y() - self._chat_drag_start_y
            old_w = self.chat_panel.width()
            old_h = self.chat_panel.height()
            # 屏幕工作区上限（防止拖大后面板超出屏幕）
            try:
                scr = self.screen() or QApplication.primaryScreen()
                avail = scr.availableGeometry()
                max_win_w = max(300, avail.width() - 24)
                max_win_h = max(240, avail.height() - 24)
                max_panel_w = max(300, max_win_w - (self.width() - old_w))
                max_panel_h = max(120, max_win_h - (self.height() - old_h))
            except Exception:
                max_panel_w, max_panel_h = 700, 900
            new_w = old_w
            new_h = old_h
            move_x = 0  # 窗口 x 位移（左延伸时左移）
            if mode == 'h':
                if self._chat_drag_side == 'left':
                    # 拖左边：向左拖（dx<0）→ 变宽，窗口左移（左边界向左延伸，右边界不动）
                    new_w = int(max(300, min(self._chat_drag_start_w - dx, 700, max_panel_w)))
                    move_x = -(new_w - old_w)
                else:
                    # 拖右边：向右拖（dx>0）→ 变宽，窗口位置不动（右边界向右延伸）
                    new_w = int(max(300, min(self._chat_drag_start_w + dx, 700, max_panel_w)))
            elif mode == 'v_bottom':
                # 拖下边：下拉（dy>0）→ 变高，窗口位置不动（下边界向下延伸）
                new_h = int(max(120, min(self._chat_drag_start_h + dy, 900, max_panel_h)))
            elif mode == 'corner_bl':
                # 左下角：向左+向下同时延伸（v6.19c 恢复下两角双维拖拽）
                new_w = int(max(300, min(self._chat_drag_start_w - dx, 700, max_panel_w)))
                move_x = -(new_w - old_w)
                new_h = int(max(120, min(self._chat_drag_start_h + dy, 900, max_panel_h)))
            elif mode == 'corner_br':
                # 右下角：向右+向下同时延伸
                new_w = int(max(300, min(self._chat_drag_start_w + dx, 700, max_panel_w)))
                new_h = int(max(120, min(self._chat_drag_start_h + dy, 900, max_panel_h)))
            # 基于窗口位置的底部限制：窗口底部不超屏幕底（防止输入框被屏幕/窗口截断）
            if mode in ('v_bottom', 'corner_bl', 'corner_br'):
                try:
                    avail_bottom = (self.screen() or QApplication.primaryScreen()).availableGeometry().bottom()
                    max_h_by_pos = max(120, avail_bottom - (self.y() + self.height() - old_h))
                    new_h = min(new_h, max_h_by_pos)
                except Exception:
                    pass
            delta_w = new_w - old_w
            delta_h = new_h - old_h
            if delta_w or delta_h:
                self.chat_panel.setFixedSize(new_w, new_h)
                self.setFixedSize(self.width() + delta_w, self.height() + delta_h)
                # 屏幕边界保护：窗口完整落在工作区内（左缘/底缘）
                try:
                    avail = (self.screen() or QApplication.primaryScreen()).availableGeometry()
                    nx = self.x() + move_x
                    nx = max(avail.left(), min(nx, avail.right() - self.width()))
                    ny = max(avail.top(), min(self.y(), avail.bottom() - self.height()))
                    if nx != self.x() or ny != self.y():
                        self.move(nx, ny)
                except Exception:
                    pass
        else:
            # 悬停光标提示（边缘可拖拽）——鼠标在子控件上（文本/卡片/输入框）时不干预光标，
            # 否则会把文本的选择光标盖成边缘拖拽图标（v6.17 修复）
            child = self.chat_panel.childAt(event.position().toPoint())
            if child is not None and child is not self.chat_panel:
                self.chat_panel.setCursor(Qt.ArrowCursor)
                event.accept()
                return
            x = event.position().x()
            y = event.position().y()
            w = self.chat_panel.width()
            h = self.chat_panel.height()
            edge = 14
            left, right = x < edge, x > w - edge
            bottom = y > h - edge
            if left and bottom:
                cur = Qt.SizeBDiagCursor   # 左下角（\ 方向）
            elif right and bottom:
                cur = Qt.SizeFDiagCursor   # 右下角（/ 方向）
            elif left or right:
                cur = Qt.SizeHorCursor
            elif bottom:
                cur = Qt.SizeVerCursor
            else:
                cur = Qt.ArrowCursor
            self.chat_panel.setCursor(cur)
        event.accept()

    def _chat_panel_release(self, event):
        self._chat_drag_mode = None
        event.accept()

    def _auto_resize_input(self):
        """输入框高度自适应：内容多自动增高（单行 34px ~ 上限 120px），超上限内部滚动"""
        try:
            doc = self.chat_input.document()
            content_h = int(doc.size().height()) + 10  # 内容高度 + 上下 padding
            new_h = max(34, min(content_h, 120))
            if self.chat_input.height() != new_h:
                self.chat_input.setFixedHeight(new_h)
        except Exception:
            pass

    def eventFilter(self, obj, event):
        """输入框事件：Enter 发送（Shift+Enter 换行）；Ctrl+V 粘贴截图自动 OCR"""
        from PySide6.QtCore import QEvent
        if obj is self.chat_input and event.type() == QEvent.Type.KeyPress:
            # 截图粘贴：剪贴板有图片 → OCR 流程；无图 → 正常文本粘贴
            if event.key() == Qt.Key_V and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                if self._handle_pasted_image():
                    return True
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                    self._on_chat_input()
                    return True
        return super().eventFilter(obj, event)

    def _handle_pasted_image(self):
        """检测剪贴板内容：①文件（粘贴文件→附件卡片）②图片（暂存待发送）；都没有放行文本"""
        # ① 剪贴板是文件 → 统一暂存（附件卡片）
        try:
            md = QApplication.clipboard().mimeData()
            if md and md.hasUrls():
                urls = [u for u in md.urls() if u.isLocalFile()]
                if urls:
                    for u in urls:
                        self._add_attachment(u.toLocalFile())
                    return True
        except Exception:
            pass
        # ② 剪贴板是图片 → 统一暂存（附件卡片）
        try:
            img = QApplication.clipboard().image()
            if img.isNull():
                return False
        except Exception:
            return False
        # v6.51：文件名带毫秒时间戳——原先固定名 _pasted_ocr.png，连粘两张图时
        # 两个附件卡片会指向同一文件，先粘的那张内容被覆盖（OCR/送模型全错）
        path = os.path.join(BASE_DIR, '_pasted_ocr_%d.png' % int(time.time() * 1000))
        try:
            img.save(path, 'PNG')
        except Exception:
            return False
        self._add_attachment(path)
        return True

    def _insert_dropped_paths(self, urls):
        """拖放文件 → 路径插入输入框（用户可继续输入需求）"""
        from PySide6.QtCore import QUrl
        paths = []
        for u in urls:
            try:
                p = u.toLocalFile() if isinstance(u, QUrl) else str(u)
            except Exception:
                p = str(u)
            if p:
                paths.append(p)
        if not paths:
            return
        cur = self.chat_input.toPlainText()
        sep = ' ' if cur and not cur.endswith(' ') else ''
        self.chat_input.setPlainText(cur + sep + ' '.join(paths))

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            self._insert_dropped_paths(e.mimeData().urls())
            e.accept()
        else:
            super().dropEvent(e)





    def _add_attachment(self, path):
        """加入待发附件（统一暂存，显示卡片）"""
        if not path or not os.path.isfile(path):
            return
        ext = os.path.splitext(path)[1].lower()
        TEXT_EXTS = ('.txt', '.md', '.log', '.json', '.csv', '.py', '.ps1', '.bat', '.ini', '.cfg',
                     '.yml', '.yaml', '.xml', '.svg', '.html', '.htm', '.css', '.js', '.ts', '.java',
                     '.c', '.cpp', '.h', '.go', '.rs', '.sh', '.sql', '.toml', '.properties')
        if ext in ('.png', '.jpg', '.jpeg', '.bmp', '.webp', '.gif'):
            kind, icon = 'image', '🖼'
        elif ext in TEXT_EXTS:
            kind, icon = 'text', '📄'
        elif ext in ('.docx', '.doc'):
            kind, icon = 'docx', '📘'
        elif ext == '.pdf':
            kind, icon = 'pdf', '📕'
        elif ext in ('.xlsx', '.xls'):
            kind, icon = 'xlsx', '📗'
        elif ext in ('.pptx', '.ppt'):
            kind, icon = 'pptx', '📙'
        else:
            kind, icon = 'other', '📎'
        try:
            size = os.path.getsize(path)
            size_txt = f'{size / 1024:.0f}KB' if size < 1024 * 1024 else f'{size / 1024 / 1024:.1f}MB'
        except Exception:
            size_txt = '?'
        att = {'path': path, 'kind': kind, 'icon': icon, 'name': os.path.basename(path), 'size': size_txt}
        if att not in self._pending_attachments:
            self._pending_attachments.append(att)
        self._refresh_attach_bar()

    def _remove_attachment(self, att):
        if att in self._pending_attachments:
            self._pending_attachments.remove(att)
        self._refresh_attach_bar()

    def _refresh_attach_bar(self):
        """重建附件卡片栏"""
        lay = self.attach_bar_layout
        while lay.count() > 1:  # 保留末尾 stretch
            item = lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for att in self._pending_attachments:
            lay.insertWidget(lay.count() - 1, self._make_attach_card(att))
        self.attach_bar.setVisible(bool(self._pending_attachments))

    def _make_attach_card(self, att):
        """附件卡片：图标 + 文件名 + 大小 + ✕"""
        card = QFrame(self.attach_bar)
        card.setStyleSheet('QFrame{background:#2b3245;border:1px solid #3a4158;border-radius:6px;}')
        hl = QHBoxLayout(card)
        hl.setContentsMargins(8, 3, 6, 3)
        hl.setSpacing(5)
        icon = QLabel(att['icon'], card)
        icon.setStyleSheet('background:transparent;border:none;font-size:13px;')
        hl.addWidget(icon)
        nm = QLabel(att['name'], card)
        nm.setStyleSheet('background:transparent;border:none;color:#cfd6e6;font-size:11px;')
        nm.setMaximumWidth(130)
        nm.setToolTip(att['path'])
        hl.addWidget(nm)
        sz = QLabel(att['size'], card)
        sz.setStyleSheet('background:transparent;border:none;color:#7a8299;font-size:10px;')
        hl.addWidget(sz)
        xb = QPushButton('✕', card)
        xb.setFixedSize(16, 16)
        xb.setStyleSheet('QPushButton{background:transparent;border:none;color:#9aa2b8;font-size:10px;}'
                         'QPushButton:hover{color:#ff6b6b;}')
        xb.clicked.connect(lambda: self._remove_attachment(att))
        hl.addWidget(xb)
        return card

    def _pick_attach_files(self):
        """📎 附加文件：打开文件选择器，多选后逐个处理"""
        from PySide6.QtWidgets import QFileDialog
        files, _ = QFileDialog.getOpenFileNames(
            self, self._t('attach_tip') if hasattr(self, '_t') else '附加文件',
            '', '所有文件 (*.*)')
        for f in files[:5]:
            self._add_attachment(f)
        if len(files) > 5:
            self._append_chat('桌宠', '一次最多处理 5 个文件，已忽略其余')

    def _handle_dropped_files(self, urls):
        """处理拖入的文件列表"""
        from PySide6.QtCore import QUrl
        paths = []
        for u in urls:
            try:
                p = u.toLocalFile() if isinstance(u, QUrl) else str(u)
            except Exception:
                p = str(u)
            if p and os.path.isfile(p):
                paths.append(p)
        if paths:
            for p in paths[:5]:
                self._attach_file(p)
            if len(paths) > 5:
                self._append_chat('桌宠', '一次最多处理 5 个文件，已忽略其余')

    def _attach_file(self, path):
        """按类型处理拖入文件：图片→OCR，文本→读内容发AI，其他→路径"""
        ext = os.path.splitext(path)[1].lower()
        is_en = getattr(self, 'language', 'zh') == 'en'
        base = os.path.basename(path)
        try:
            size = os.path.getsize(path)
        except Exception:
            size = 0
        size_txt = f'{size / 1024:.0f}KB' if size < 1024 * 1024 else f'{size / 1024 / 1024:.1f}MB'
        if ext in ('.png', '.jpg', '.jpeg', '.bmp', '.webp'):
            self._append_chat('我', f'🖼 [{base}]（{size_txt}·图片）')
            dst = os.path.join(BASE_DIR, '_dropped_img.png')
            try:
                from PIL import Image
                Image.open(path).convert('RGB').save(dst, 'PNG')
                self._append_chat('桌宠', '🔍 正在识别图片文字…' if not is_en else '🔍 Recognizing text…')
                import threading
                threading.Thread(target=lambda: self.ocr_signal.emit(ocr_image(dst, OCR_PS1)), daemon=True).start()
            except Exception as e:
                self._append_chat('桌宠', f'图片处理失败：{e}' if not is_en else f'Image error: {e}')
        elif ext in ('.txt', '.md', '.log', '.json', '.csv', '.py', '.ps1', '.bat', '.ini', '.cfg', '.yml', '.yaml'):
            try:
                with open(path, encoding='utf-8', errors='ignore') as f:
                    content = f.read(2500)
                self._append_chat('我', f'📄 [{base}]（{size_txt}·文本 {len(content)} 字）')
                self.ask_ai(f'（用户放入文件：{base}，内容如下，请分析/回答）\n{content}')
            except Exception as e:
                self._append_chat('桌宠', f'文件读取失败：{e}' if not is_en else f'Read error: {e}')
        else:
            self._append_chat('我', f'📎 [{base}]（{size_txt}·{ext[1:] or "未知"}）')
            self.ask_ai(f'（用户放入文件：{path}。若需要读取内容请提示用户配合，或根据文件名/路径回应）')

    def _on_ocr_result(self, text):
        """OCR 完成：识别内容显示为消息并发送给 AI"""
        # v6.51：粘贴图文件名带时间戳了，这里用通配清理（旧固定名也一并清掉）
        import glob as _glob
        for p in (_glob.glob(os.path.join(BASE_DIR, '_pasted_ocr*.png')) +
                  _glob.glob(os.path.join(BASE_DIR, '_dropped_img*.png'))):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
        is_en = getattr(self, 'language', 'zh') == 'en'
        if not text.strip():
            self._append_chat('桌宠', '😕 没识别到文字（可能是纯图片或截图太糊）' if not is_en else '😕 No text recognized')
            return
        self._chat_type_finish()
        self._append_chat('我', f'📷 截图识别（{len(text)} 字）→ 已发送分析')
        self.ask_ai((f'（用户发来一张截图，OCR 识别内容如下，请根据内容回答或处理）\n{text}'
                    if not is_en else f'(User sent a screenshot. OCR result below; answer or act on it.)\n{text}'))

    def _on_screenshot_hotkey(self):
        """全局快捷键 Ctrl+Alt+S：截全屏 → OCR → 发给 AI 分析"""
        try:
            from PIL import ImageGrab
            is_en = getattr(self, 'language', 'zh') == 'en'
            self._append_chat('桌宠', '📸 截屏中…' if not is_en else '📸 Capturing…')
            img = ImageGrab.grab()
            path = os.path.join(BASE_DIR, '_screenshot_ocr.png')
            img.save(path, 'PNG')
            import threading
            def worker():
                try:
                    self.ocr_signal.emit(ocr_image(path, OCR_PS1))
                except Exception:
                    pass
            threading.Thread(target=worker, daemon=True).start()
        except Exception as e:
            self._append_chat('桌宠', f'截图失败：{e}' if not is_en else f'Capture failed: {e}')

    def _on_chat_input(self):
        """处理聊天输入：本地指令 / AI 对话（含暂存图片：OCR 后连同文字要求一起发）"""
        if self._pending_attachments:
            atts = list(self._pending_attachments)
            self._pending_attachments = []
            self._refresh_attach_bar()
            text = self.chat_input.toPlainText().strip()
            is_en = getattr(self, 'language', 'zh') == 'en'
            self.chat_input.clear()
            names = '、'.join(a['name'] for a in atts[:3])
            if len(atts) > 3:
                names += f' 等{len(atts)}个'
            self._append_chat('我', f'{atts[0]["icon"]} [{names}]' + (f'：{text}' if text else ''))
            import threading

            def atts_ask():
                try:
                    parts = []
                    images = [a for a in atts if a['kind'] == 'image']
                    for a in atts:
                        if a['kind'] == 'image':
                            continue
                        if a['kind'] == 'text':
                            try:
                                with open(a['path'], encoding='utf-8', errors='ignore') as fp:
                                    content = fp.read()
                                if len(content) > 8000:
                                    parts.append(f'【{a["name"]}】（共 {len(content)} 字符，仅读取前 8000 字符，如需完整内容请让用户分段提供）\n{content[:8000]}')
                                else:
                                    parts.append(f'【{a["name"]}】\n{content}')
                            except Exception:
                                parts.append(f'【{a["name"]}】（读取失败）')
                        elif a['kind'] == 'docx':
                            content = read_docx_text(a['path'])
                            if len(content) > 8000:
                                parts.append(f'【{a["name"]}】（共 {len(content)} 字符，仅读取前 8000 字符）\n{content[:8000]}')
                            else:
                                parts.append(f'【{a["name"]}】\n{content}')
                        elif a['kind'] == 'pdf':
                            content = read_pdf_text(a['path'])
                            if len(content) > 8000:
                                parts.append(f'【{a["name"]}】（共 {len(content)} 字符，仅读取前 8000 字符）\n{content[:8000]}')
                            else:
                                parts.append(f'【{a["name"]}】\n{content}')
                        elif a['kind'] == 'xlsx':
                            content = read_xlsx_text(a['path'])
                            if len(content) > 8000:
                                parts.append(f'【{a["name"]}】（共 {len(content)} 字符，仅读取前 8000 字符）\n{content[:8000]}')
                            else:
                                parts.append(f'【{a["name"]}】\n{content}')
                        elif a['kind'] == 'pptx':
                            content = read_pptx_text(a['path'])
                            if len(content) > 8000:
                                parts.append(f'【{a["name"]}】（共 {len(content)} 字符，仅读取前 8000 字符）\n{content[:8000]}')
                            else:
                                parts.append(f'【{a["name"]}】\n{content}')
                        else:
                            parts.append(f'【{a["name"]}】路径：{a["path"]}')
                    if images:
                        for a in images:
                            try:
                                ocr_text = ocr_image(a['path'], OCR_PS1)
                                parts.append(f'【图片 {a["name"]} OCR】\n{ocr_text}')
                            except Exception:
                                parts.append(f'【图片 {a["name"]}】（OCR 失败）')
                    body = '\n\n'.join(parts) if parts else '（无内容）'
                    req = text or '请查看这些文件并简要说明内容'
                    self.ask_ai(f'（用户放入 {len(atts)} 个附件，内容如下）\n{body}\n\n用户要求：{req}')
                except Exception:
                    pass
            threading.Thread(target=atts_ask, daemon=True).start()
            return
        raw = self.chat_input.toPlainText().strip()
        if not raw:
            self.chat_input.clear()
            return
        # 剥离用户消息的情绪标签并触发立绘
        text, u_emotion = self._strip_emotion_tag(raw)
        if not text:
            text = raw
        if u_emotion:
            self._apply_emotion(u_emotion)
        # 打字机进行中 → 先立即完成（避免两条消息交错）
        self._chat_type_finish()
        self.chat_input.clear()
        self._append_chat('我', text)
        low = text.lower()

        if low == '/stop':
            self._stop_ai()
            self._append_chat('桌宠', '⏹ 已停止当前任务并取消未完成任务')
            return
        if low == '/clear':
            self._clear_chat_memory()
            self._append_chat('桌宠', '聊天记录已清空')
            return
        if low == '/help':
            self._append_chat('桌宠', '指令：/clear 清空 · /time 时间 · /calc 算式 · /weather 天气 · /person 性格 · /run 程序 · /remind 秒 内容 · /pomo 番茄钟 · /lock 锁屏 · /sound 音效 · /todo 待办清单；直接聊天即可，Ctrl+V 可粘贴截图识别')
            return
        if low == '/todo':
            self._append_chat('桌宠', self._manage_todo('list'))
            return
        if low == '/time':
            import datetime
            self._append_chat('桌宠', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            return
        if low.startswith('/calc '):
            # 复用 tools_executor.calculate_expr（AST 白名单，不再用 eval）
            self._append_chat('桌宠', calculate_expr(low[6:]))
            return
        if low == '/weather':
            self.ask_ai(f'帮我查一下{self.pet_city}现在的天气')
            return
        if low.startswith('/person'):
            parts = text.split()
            p = parts[1] if len(parts) > 1 else '温柔'
            self._set_personality(p)
            return
        if low.startswith('/run '):
            self._append_chat('桌宠', self._smart_open(low[5:].strip()))
            return
        if low == '/lock':
            try:
                ctypes.windll.user32.LockWorkStation()
            except Exception:
                self._append_chat('桌宠', '锁屏失败')
            return
        if low.startswith('/remind '):
            parts = text[8:].split(' ', 1)
            try:
                sec = int(parts[0].strip())
                msg = parts[1].strip() if len(parts) > 1 else '该做事啦'
                self._add_reminder(sec, msg)
            except Exception:
                self._append_chat('桌宠', '用法：/remind 60 喝水')
            return
        if low == '/pomo':
            self._add_reminder(25 * 60, '番茄钟结束，休息一下！')
            self._append_chat('桌宠', '🍅 25 分钟番茄钟已开始，到点提醒')
            return
        if low == '/sound':
            self._play_sound('msg')
            self._append_chat('桌宠', '🔔 测试音效')
            return
        # 其他走 AI
        self.ask_ai(text)

    def _save_cfg_value(self, key, value):
        """写 config.json 并热加载（改配置立即生效）"""
        try:
            cfg = {}
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
            cfg[key] = value
            self._atomic_write_json(CONFIG_PATH, cfg)
            self._load_ai_config()
            return True
        except Exception as e:
            self._append_chat('桌宠', f'配置保存失败：{e}')
            return False

    def _set_reply_style(self, val, label):
        """设置回复风格（short/normal/detailed）"""
        if self._save_cfg_value('reply_style', val):
            self._append_chat('桌宠', f'回复风格：{label}')

    def _set_max_tokens(self, val, label):
        """设置回复 token 上限"""
        if self._save_cfg_value('max_tokens', val):
            self._append_chat('桌宠', f'回复长度上限：{label}')

    def _set_max_tokens_dialog(self):
        """弹窗自定义 token 上限（对齐 DeepSeek API：输出上限 384K，给到 128K 足够日常）"""
        from PySide6.QtWidgets import QInputDialog
        is_en = getattr(self, 'language', 'zh') == 'en'
        text, ok = QInputDialog.getText(self, self._t('dlg_tokens'),
            f'输入 token 上限（{MIN_OUTPUT_TOKENS}-{MAX_OUTPUT_TOKENS}，越大回复越长）：' if not is_en
            else f'Enter token limit ({MIN_OUTPUT_TOKENS}-{MAX_OUTPUT_TOKENS}, higher = longer replies):',
            text=str(getattr(self, 'max_tokens', 1000)))
        if ok and text.strip().isdigit():
            val = clamp_tokens(text.strip())
            if self._save_cfg_value('max_tokens', val):
                self._append_chat('桌宠', f'回复长度上限：{val} token' if not is_en else f'Reply length limit: {val} tokens')

    def _set_city_dialog(self):
        """弹窗设置默认城市"""
        from PySide6.QtWidgets import QInputDialog
        is_en = getattr(self, 'language', 'zh') == 'en'
        text, ok = QInputDialog.getText(self, self._t('dlg_city'),
            '输入默认天气城市：' if not is_en else 'Enter default weather city:', text=self.pet_city)
        if ok and text.strip():
            if self._save_cfg_value('city', text.strip()):
                self._append_chat('桌宠', f'默认城市：{text.strip()}' if not is_en else f'Default city: {text.strip()}')

    def _set_api_key_dialog(self):
        """弹窗设置 DeepSeek API Key（保存后热加载生效）"""
        from PySide6.QtWidgets import QInputDialog, QLineEdit
        is_en = getattr(self, 'language', 'zh') == 'en'
        cur = getattr(self, 'ai_key', '') or ''
        if len(cur) > 12:
            masked = cur[:6] + '…' + cur[-4:]
        elif cur:
            masked = cur
        else:
            masked = '（未配置）' if not is_en else '(not set)'
        text, ok = QInputDialog.getText(self, self._t('dlg_api'),
            (f'输入 DeepSeek API Key（留空取消）：\n当前：{masked}' if not is_en else f'Enter DeepSeek API key (leave empty to cancel):\nCurrent: {masked}'),
            QLineEdit.Password, cur)
        if ok and text.strip():
            if self._save_cfg_value('deepseek_api_key', text.strip()):
                self._append_chat('桌宠', '✅ API Key 已更新，AI 立即生效' if not is_en else '✅ API key updated, AI takes effect immediately')

    def _set_search_key_dialog(self):
        """弹窗设置 Tavily 联网搜索 API Key（可选，配置后 AI 可联网查最新信息）"""
        from PySide6.QtWidgets import QInputDialog, QLineEdit
        is_en = getattr(self, 'language', 'zh') == 'en'
        cur = getattr(self, 'search_api_key', '') or ''
        if len(cur) > 12:
            masked = cur[:6] + '…' + cur[-4:]
        elif cur:
            masked = cur
        else:
            masked = '（未配置）' if not is_en else '(not set)'
        text, ok = QInputDialog.getText(self, self._t('dlg_search'),
            (f'输入 Tavily 联网搜索 API Key（留空取消；https://tavily.com 免费注册，每月 1000 次）：\n当前：{masked}'
             if not is_en else f'Enter Tavily search API key (leave empty to cancel; free 1000/mo at tavily.com):\nCurrent: {masked}'),
            QLineEdit.Password, cur)
        if ok and text.strip():
            if self._save_cfg_value('search_api_key', text.strip()):
                self.search_api_key = text.strip()
                self._append_chat('桌宠', '✅ 联网搜索已配置，AI 可查询最新信息' if not is_en else '✅ Search configured, AI can browse for latest info')

    def _save_profile_param(self, name, value):
        """写当前角色的档案参数并落盘（思考开关 / 采样温度等）"""
        prof = self._current_profile()
        if prof is None:
            return False
        if not MODEL_REGISTRY.set_param(prof.key, name, value):
            return False
        MODEL_REGISTRY.save()
        self._load_ai_config()      # 热加载：参数立即生效 + 菜单勾选态刷新
        return True

    def _toggle_reasoning(self):
        """切换思考模式（写进当前角色的模型档案）"""
        is_en = getattr(self, 'language', 'zh') == 'en'
        want = not getattr(self, 'reasoning_enabled', True)
        if not self._save_profile_param('reasoning', want):
            return
        msg = ('思考模式已开启' if want else '思考模式已关闭') if not is_en else \
              ('Thinking on' if want else 'Thinking off')
        self._append_chat('桌宠', msg + ('（已写入模型档案）' if not is_en else ' (saved to model profile)'))

    def _set_temperature(self, val):
        """设置采样温度（写进当前角色的模型档案）"""
        is_en = getattr(self, 'language', 'zh') == 'en'
        if not self._save_profile_param('temperature', val):
            return
        self._append_chat('桌宠', (f'采样温度：{val}' if not is_en else f'Temperature: {val}')
                          + ('（已写入模型档案）' if not is_en else ' (saved to model profile)'))

    def _set_temperature_dialog(self):
        """自定义采样温度"""
        from PySide6.QtWidgets import QInputDialog
        is_en = getattr(self, 'language', 'zh') == 'en'
        text, ok = QInputDialog.getText(self, self._t('temperature'),
            ('输入 0.0 ~ 2.0（越小越稳，越大越发散）：' if not is_en
             else 'Enter 0.0 ~ 2.0 (lower = steadier):'),
            text=str(getattr(self, 'temperature', 1.0)))
        if ok and text.strip():
            try:
                self._set_temperature(max(0.0, min(float(text.strip()), 2.0)))
            except ValueError:
                self._append_chat('桌宠', '请输入数字。' if not is_en else 'Please enter a number.')

    def _on_models_saved(self):
        """模型档案落盘后热加载：刷新角色表 / 模型 ID / 参数"""
        self._load_ai_config()

    def _open_model_manager(self):
        """打开模型管理对话框：增删档案 / 改显示名与模型 ID / 拉官方列表 / 连通性自检"""
        dlg = ModelManagerDialog(MODEL_REGISTRY,
                                 key_resolver=self._api_key_for_field,
                                 parent=self)
        dlg.saved.connect(self._on_models_saved)
        dlg.exec()
        self._load_ai_config()      # 关闭后再刷一次（覆盖新增/删除档案的情况）

    def _set_personality_dialog(self):
        """弹窗自定义性格"""
        from PySide6.QtWidgets import QInputDialog
        is_en = getattr(self, 'language', 'zh') == 'en'
        text, ok = QInputDialog.getText(self, self._t('dlg_personality'),
            '输入性格描述（如：傲娇毒舌的学姐）：' if not is_en else 'Enter personality description (e.g. sarcastic senior):', text=self.personality)
        if ok and text.strip():
            if self._save_cfg_value('personality', text.strip()):
                self._append_chat('桌宠', f'性格设置为：{text.strip()}' if not is_en else f'Personality set to: {text.strip()}')

    def _set_personality(self, p):
        """切换性格（预设，写入配置持久保存）"""
        p = p.strip()
        if p in ['温柔', '傲娇', '吐槽', '元气', '高冷']:
            self._save_cfg_value('personality', p)
            self._append_chat('桌宠', f'性格切换为：{p}（已保存）')
        else:
            self._append_chat('桌宠', '可选性格：温柔/傲娇/吐槽/元气/高冷')

    def switch_char(self, key):
        """切换角色（每个角色独立的对话历史 + 独立模型）"""
        if key not in CHARACTERS or key == self.current:
            return
        # 保存当前角色的对话历史
        self._save_chat_memory()
        self.load_character(key)
        self.ai_model = self._current_model()
        # 加载新角色的独立历史，刷新面板
        self.chat_history_msgs = []
        self._clear_chat_history()
        self._load_chat_memory()
        self._append_chat('桌宠', f'已切换到 {CHARACTERS[key]["name"]}（模型：{self.ai_model}）——这是 {CHARACTERS[key]["name"]} 的独立对话')

    def toggle_edge_mode(self):
        """切换贴边模式：扒边 ↔ 完全消失"""
        self._edge_mode = 'hidden' if self._edge_mode == 'peek' else 'peek'
        mode_name = '完全消失' if self._edge_mode == 'hidden' else '扒边'
        self._append_chat('桌宠', f'贴边模式切换为：{mode_name}')
        if self._edge_side is not None:
            self._edge_popped = False
            self._enter_dock(self._edge_side, self._popup_y)

    # ---------- 音效 ----------
    def _play_sound(self, kind):
        """播放提示音（winsound）"""
        try:
            if kind == 'msg':
                winsound.Beep(880, 80)
                winsound.Beep(1320, 80)
            elif kind == 'remind':
                winsound.Beep(660, 200)
                winsound.Beep(990, 200)
            else:
                winsound.Beep(660, 100)
        except Exception:
            pass

    # ---------- 贴边交互（双模式） ----------
    def _edge_dock_check(self):
        """贴边：扒边模式=显示扒边立绘双击弹出；完全消失模式=鼠标靠近边缘弹出"""
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geo = screen.geometry()
        w, h = self.width(), self.height()

        # 拖拽时不贴边
        if self.dragging:
            if self._edge_side is not None:
                self._edge_side = None
                self._edge_popped = False
            return

        x, y = self.x(), self.y()
        mouse_x, mouse_y = QCursor.pos().x(), QCursor.pos().y()
        y_near = (y - 120) <= mouse_y <= (y + h + 120)

        if self._edge_side is None:
            # ===== 自由态：按人物（pet_label）位置判断吸附，而非整个窗口 =====
            # pet_label 在布局中水平居中、垂直顶部
            pet_left = x + (self.width() - self.pet_size) // 2
            pet_right = pet_left + self.pet_size
            pet_bottom = y + self.pet_size
            # 注：顶部贴边已按用户要求移除；只保留左/右/下
            if pet_bottom >= geo.bottom() - 18:
                self._enter_dock('bottom', y)
            elif pet_left <= 18:
                self._enter_dock('left', y)
            elif pet_right >= geo.right() - 18:
                self._enter_dock('right', y)
        else:
            side = self._edge_side
            if self._edge_mode == 'hidden':
                self._hidden_mode_logic(side, x, y, w, h, mouse_x, mouse_y, y_near, geo)
            else:
                self._peek_mode_logic(side, x, y, w, h, mouse_x, mouse_y, geo)

    def _exit_dock_to_free(self):
        """解除贴边，恢复正常待机（拖出/右键时用；v6.19d 窗口跟随面板+屏幕钳制，防截断）"""
        self._edge_side = None
        self._edge_popped = False
        if self._chat_hidden_for_dock:
            self.chat_panel.show()
            self._chat_hidden_for_dock = False
            try:
                self.chat_input.setFixedHeight(34)
                self.chat_input.setMinimumHeight(34)
            except Exception:
                pass
        self._sync_window_to_panel()
        self.pet_label.setFixedSize(self.pet_size, self.pet_size)
        self._restore_display_state()

    def _popup_from_dock(self):
        """从贴边弹出完整窗口（双击/右键用；v6.19d 窗口跟随面板+屏幕钳制）"""
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geo = screen.geometry()
        side = self._edge_side
        if self._chat_hidden_for_dock and not self.chat_panel.isVisible():
            self.chat_panel.show()
            self._chat_hidden_for_dock = False
            try:
                self.chat_input.setFixedHeight(34)
                self.chat_input.setMinimumHeight(34)
            except Exception:
                pass
        self._sync_window_to_panel()
        if side in ('left', 'right'):
            pop_x = 0 if side == 'left' else geo.right() - self.width()
            pop_y = max(geo.top(), min(self._popup_y, geo.bottom() - self.height()))
            self.move(pop_x, pop_y)
        else:
            pop_y = 0 if side == 'top' else geo.bottom() - self.height()
            pop_x = max(geo.left(), min(self._popup_x, geo.right() - self.width()))
            self.move(pop_x, pop_y)
        self._edge_popped = True
        self._restore_display_state()

    def _enter_dock(self, side, y):
        """进入贴边（立即收缩）"""
        self._edge_side = side
        self._popup_y = y
        self._popup_x = self.x()
        self._edge_popped = False
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geo = screen.geometry()
        if self.chat_panel.isVisible():
            self._chat_hidden_for_dock = True
            self.chat_panel.hide()
        # v6.51：扒边后窗口只剩立绘宽，气泡显示出来也是被裁的残句，直接收起来
        if getattr(self, 'bubble', None) is not None and self.bubble.isVisible():
            self.bubble.hide()
        if self._edge_mode == 'peek':
            # 扒边模式：窗口贴边缘，显示对应方向的扒边立绘（坐标保护：窗口完全在屏幕内）
            if side in ('left', 'right'):
                # 竖构图：窗口缩到立绘宽度，贴左/右缘
                dock_w = self.pet_size
                self.setFixedSize(dock_w, 340)
                dock_x = 0 if side == 'left' else geo.right() - dock_w
                dock_y = max(0, min(y, geo.bottom() - 340))
                self.move(dock_x, dock_y)
            else:
                # 横构图：窗口贴底缘
                self.setFixedSize(440, 300)
                dock_x = max(0, min(self._popup_x, geo.right() - 440))
                self.move(dock_x, geo.bottom() - 300)
            # 显示扒边立绘（带方向）
            self._show_peek()
        else:
            # 完全消失模式：移出屏幕只露 1px（窗口主体在屏幕外，仅边缘可触发弹出）
            self.setFixedSize(440, 340)
            if side == 'left':
                self.move(-440 + 1, max(0, min(y, geo.bottom() - 340)))
            elif side == 'right':
                self.move(geo.right() - 1, max(0, min(y, geo.bottom() - 340)))
            else:
                self.move(max(0, min(self._popup_x, geo.right() - 440)), geo.bottom() - 1)

    def _restore_window_size(self):
        """恢复完整窗口大小（v6.19d 窗口跟随面板+屏幕钳制，防截断）"""
        self._sync_window_to_panel()

    def _peek_mode_logic(self, side, x, y, w, h, mouse_x, mouse_y, geo):
        """扒边模式：双击弹出（mouseDoubleClickEvent 处理），此处只保持贴边"""
        # 保持贴边位置 + 强制显示扒边立绘（防止被眨眼/动画覆盖）
        if not self._edge_popped:
            if side in ('left', 'right'):
                dock_w = self.width()
                dock_x = 0 if side == 'left' else geo.right() - dock_w
                dock_y = max(0, min(self._popup_y, geo.bottom() - self.height()))
                self.move(dock_x, dock_y)
            else:
                dock_h = self.height()
                dock_x = max(0, min(self._popup_x, geo.right() - self.width()))
                self.move(dock_x, geo.bottom() - dock_h)
            self._show_peek()

    def _hidden_mode_logic(self, side, x, y, w, h, mouse_x, mouse_y, y_near, geo):
        """完全消失模式：鼠标靠近边缘弹出；移开后不立即收回（允许选中/点击）"""
        dock_margin = 40
        leave_margin = 90
        if side == 'left':
            mouse_near = mouse_x <= leave_margin
            pop_x, pop_y = 0, self._popup_y
            dock_x, dock_y = -w + 1, self._popup_y
        elif side == 'right':
            mouse_near = mouse_x >= geo.right() - leave_margin
            pop_x, pop_y = geo.right() - w, self._popup_y
            dock_x, dock_y = geo.right() - 1, self._popup_y
        elif side == 'top':
            mouse_near = mouse_y <= leave_margin
            pop_x, pop_y = self._popup_x, 0
            dock_x, dock_y = self._popup_x, -h + 1
        else:  # bottom
            mouse_near = mouse_y >= geo.bottom() - leave_margin
            pop_x, pop_y = self._popup_x, geo.bottom() - h
            dock_x, dock_y = self._popup_x, geo.bottom() - 1

        if self._edge_popped:
            # ===== 已弹出：鼠标在窗口上或靠近边缘 → 保持；否则收回 =====
            mouse_in_win = (pop_x - 30 <= mouse_x <= pop_x + w + 30
                            and pop_y - 40 <= mouse_y <= pop_y + h + 40)
            if mouse_near or mouse_in_win:
                self.move(pop_x, pop_y)
            else:
                # 收回
                if self.chat_panel.isVisible():
                    self._chat_hidden_for_dock = True
                    self.chat_panel.hide()
                    self.setFixedSize(440, 340)
                self.move(dock_x, dock_y)
                self._edge_popped = False
        else:
            # ===== 未弹出：靠近边缘弹出 =====
            if mouse_near and y_near:
                target_y = max(0, min(mouse_y - h // 2, geo.bottom() - h))
                target_x = max(0, min(mouse_x - w // 2, geo.right() - w))
                if side in ('left', 'right'):
                    self._popup_y = target_y
                    self.move(pop_x, target_y)
                else:
                    self._popup_x = target_x
                    self.move(target_x, pop_y)
                self._edge_popped = True
                if self._chat_hidden_for_dock and not self.chat_panel.isVisible():
                    self.chat_panel.show()
                    self.setFixedSize(440, 560)
                    self._chat_hidden_for_dock = False
            # 彻底离开（远离边缘且鼠标不在附近）→ 退出贴边
            if side == 'left':
                left_edge = not (mouse_x <= dock_margin)
            elif side == 'right':
                left_edge = not (mouse_x >= geo.right() - dock_margin)
            elif side == 'top':
                left_edge = not (mouse_y <= dock_margin)
            else:
                left_edge = not (mouse_y >= geo.bottom() - dock_margin)
            if left_edge and not y_near:
                self._edge_side = None
                self._edge_popped = False

    # ---------- 动画 ----------
    def animate(self):
        # 贴边检查（非拖拽时）
        self._edge_dock_check()
        # v6.30 fix：贴边未弹出时完全静止（不做摆头移动，避免与贴边定位冲突导致左右抽动）
        if self._edge_side is not None and not self._edge_popped:
            return
        # 待机/拖拽/睡眠：完全静止，不重绘不移动（杜绝闪烁）
        if self.state == 'idle' or self.sleeping or self.dragging:
            return
        # 思考/开心：轻微左右摆头（只动位置，不重绘图片）
        self.phase += 1
        dx = int(3 * math.sin(self.phase * 0.25))
        if self.base_x is None:
            self.base_x = self.x()
        if self.base_y is None:
            self.base_y = self.y()
        self.move(self.base_x + dx, self.base_y)

    # ---------- 睡眠 ----------
    def toggle_sleep(self):
        """睡眠切换（实现已搬至 pet_anim.toggle_sleep）"""
        return anim.toggle_sleep(self)
    # ---------- 连击 ----------
    def _on_click(self):
        import time
        now = time.time()
        self.click_times.append(now)
        self.click_times = [t for t in self.click_times if now - t < 0.8]
        if len(self.click_times) >= 3:
            self.click_times = []
            self._special_reaction()

    def _special_reaction(self):
        if self.current == 'pro':
            # v6.51：补上 state——原先只换立绘不设状态，若此刻有眨眼在途，
            # _blend_end 会按 state=='idle' 把立绘提前刷回待机（与普通角色分支行为不一致）
            self.state = 'scared'
            self.phase = 0
            self._show_state_image('scared')
            lines = self._char_lines('scared_lines')
            self.say_plain(random.choice(lines) if lines else 'Ah!')
            QTimer.singleShot(2500, lambda: self._end_state('scared'))
        else:
            self.state = 'happy'
            self.phase = 0
            self._show_state_image('happy')
            lines = self._char_lines('happy_lines')
            self.say_plain(random.choice(lines) if lines else 'Yay!')
            QTimer.singleShot(2500, lambda: self._end_state('happy'))

    def _end_state(self, st):
        """临时状态收尾（实现已搬至 pet_anim.end_state）"""
        return anim.end_state(self, st)
    # ---------- 鼠标 ----------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # 扒边贴边状态：按下即解除贴边，恢复正常待机，允许拖出
            if self._edge_side is not None and self._edge_mode == 'peek' and not self._edge_popped:
                self._exit_dock_to_free()
                self._drag_from_dock = True
            else:
                self._drag_from_dock = False
            self.dragging = True
            self.drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.dragging and (event.buttons() & Qt.LeftButton):
            self.move(event.globalPosition().toPoint() - self.drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        if self.dragging:
            self.dragging = False
            self.base_x, self.base_y = self.x(), self.y()
            self._save_position()
            if self._drag_from_dock:
                # 从贴边拖出：不触发单击说话
                self._drag_from_dock = False
            else:
                self._on_click()
        event.accept()

    def paintEvent(self, event):
        """显式填充透明背景（不调用 super，避免 QWidget 默认绘制 palette 背景色覆盖透明）"""
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.transparent)
        p.end()

    def mouseDoubleClickEvent(self, event):
        # 扒边贴边时双击 → 弹出
        if self._edge_side is not None and self._edge_mode == 'peek' and not self._edge_popped:
            if QApplication.primaryScreen():
                self._popup_from_dock()
                return
        self.say_random()

    # ---------- 托盘 ----------
    def hide_to_tray(self):
        self.hide()
        self._ensure_tray()
        if self.tray:
            msg = f'{CHARACTERS[self.current]["name"]} 已最小化到托盘，双击图标回来。' if getattr(self, 'language', 'zh') != 'en' else f'{CHARACTERS[self.current]["name"]} minimized to tray. Double-click the icon to return.'
            self.tray.showMessage(
                'DeepSeek 桌宠',
                msg,
                QSystemTrayIcon.Information, 2000
            )

    def _ensure_tray(self):
        if hasattr(self, 'tray') and self.tray is not None:
            return self.tray
        icon = QIcon(self.full_idle.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip('DeepSeek 桌宠助手')
        tray_menu = QMenu()
        show_act = tray_menu.addAction('🏠 显示桌宠' if getattr(self, 'language', 'zh') != 'en' else '🏠 Show pet')
        # 角色项由模型档案生成（新增档案即出现，无需改代码）
        for _pk in MODEL_REGISTRY.keys():
            _prof = MODEL_REGISTRY.get(_pk)
            _act = tray_menu.addAction(_prof.display_name if _prof else _pk)
            _act.triggered.connect(lambda checked=False, k=_pk: self.switch_char(k))
        tray_menu.addSeparator()
        quit_act = tray_menu.addAction('✕ 退出' if getattr(self, 'language', 'zh') != 'en' else '✕ Exit')
        show_act.triggered.connect(self.show_pet)
        quit_act.triggered.connect(self.quit_app)
        self.tray.setContextMenu(tray_menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()
        return self.tray

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_pet()

    def show_pet(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def quit_app(self):
        self._save_position()
        if self._hotkey_installed:
            try:
                ctypes.windll.user32.UnregisterHotKey(None, 1)
            except Exception:
                pass
        QApplication.quit()

    def closeEvent(self, event):
        self.hide_to_tray()
        event.ignore()

    # ---------- 开机自启 ----------
    def _autostart_pythonw(self):
        """定位 pythonw.exe（优先独立 Python 安装，兜底当前解释器同目录）"""
        import shutil
        # 当前解释器同目录的 pythonw（最常见的可靠来源）
        base = os.path.dirname(sys.executable)
        local = os.path.join(base, 'pythonw.exe')
        if os.path.exists(local):
            return local
        # 常见安装位置兜底
        candidates = [
            os.path.expanduser(r'~\AppData\Local\Programs\Python\Python314\pythonw.exe'),
        ]
        for p in candidates:
            if os.path.exists(p):
                return p
        # PATH 搜索
        found = shutil.which('pythonw.exe')
        if found:
            return found
        return local

    def _autostart_command(self):
        """自启命令：打包版用 exe 本身，开发版用 pythonw + 脚本"""
        if getattr(sys, 'frozen', False):
            # 打包版：直接启动 exe（无 pythonw/脚本文件）
            return f'"{sys.executable}"'
        python = self._autostart_pythonw()
        script = os.path.abspath(__file__)
        return f'"{python}" "{script}"'

    def _autostart_startup_path(self):
        """启动文件夹中的自启快捷方式路径（.lnk 指向启动文件，用户可见可改）"""
        appdata = os.environ.get('APPDATA', os.path.expanduser(r'~\AppData\Roaming'))
        return os.path.join(appdata, r'Microsoft\Windows\Start Menu\Programs\Startup', 'DeepSeekPet.lnk')

    def _create_autostart_lnk(self, path):
        """创建启动快捷方式：开发版指向 启动桌宠.bat，打包版指向 exe 本身"""
        try:
            if getattr(sys, 'frozen', False):
                target = sys.executable
                workdir = os.path.dirname(sys.executable)
            else:
                bat = os.path.join(BASE_DIR, '启动桌宠.bat')
                target = bat if os.path.exists(bat) else self._autostart_command()
                workdir = BASE_DIR
            ps = (
                f"$ws = New-Object -ComObject WScript.Shell; "
                f"$s = $ws.CreateShortcut({_ps_quote(path)}); "
                f"$s.TargetPath = {_ps_quote(target)}; "
                f"$s.WorkingDirectory = {_ps_quote(workdir)}; "
                f"$s.Description = 'DeepSeek Pet'; "
                f"$s.Save()"
            )
            # -EncodedCommand：Base64 UTF-16LE，彻底规避引号/中文路径/分号转义问题
            import base64 as _b64
            enc = _b64.b64encode(ps.encode('utf-16-le')).decode('ascii')
            r = _subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', enc],
                                capture_output=True, timeout=20)
            return os.path.exists(path)
        except Exception:
            return False

    def is_autostart_enabled(self):
        """检查启动文件夹中是否有自启文件"""
        return os.path.exists(self._autostart_startup_path())

    def toggle_autostart(self):
        """开关开机自启（启动文件夹快捷方式方案，指向启动文件）"""
        try:
            path = self._autostart_startup_path()
            if os.path.exists(path):
                os.remove(path)
            # 一并清理旧版 .bat/.cmd 启动项
            startup_dir = os.path.dirname(path)
            for old in ('DeepSeekPet.bat', 'DeepSeekPet.cmd'):
                oldp = os.path.join(startup_dir, old)
                if os.path.exists(oldp):
                    try:
                        os.remove(oldp)
                    except Exception:
                        pass
            if True:
                self._append_chat('桌宠', '❌ 开机自启已关闭（下次开机需手动启动桌宠）')
                self.say_plain('已关闭开机自启', immediate=True)
            else:
                # 清理旧版启动项（.bat 残留），防止开机双启动
                startup_dir = os.path.dirname(path)
                for old in ('DeepSeekPet.bat', 'DeepSeekPet.cmd'):
                    oldp = os.path.join(startup_dir, old)
                    if os.path.exists(oldp):
                        try:
                            os.remove(oldp)
                        except Exception:
                            pass
                ok = self._create_autostart_lnk(path)
                if ok:
                    # 清理旧注册表条目（若存在，避免重复启动）
                    try:
                        import winreg as _wr
                        rk = _wr.OpenKey(_wr.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run', 0, _wr.KEY_SET_VALUE)
                        try:
                            _wr.DeleteValue(rk, 'DeepSeekPet')
                        except FileNotFoundError:
                            pass
                        _wr.CloseKey(rk)
                    except Exception:
                        pass
                    self._append_chat('桌宠', '✅ 开机自启已开启（启动文件夹快捷方式）')
                    self.say_plain('已开启开机自启', immediate=True)
                else:
                    self._append_chat('桌宠', '❌ 自启写入失败')
                    self.say_plain('自启写入失败', immediate=True)
        except Exception as e:
            self._append_chat('桌宠', f'自启设置失败：{e}')
            self.say_plain(f'自启设置失败: {e}', immediate=True)

    # ---------- 随机动作 ----------
    # ============ 主动关心系统（v6.18 链式+回访） ============
    @staticmethod
    def _user_idle_minutes():
        """用户空闲分钟数（拆至 care_engine.user_idle_minutes）"""
        return user_idle_minutes()

    def _ai_wakeup_judge(self):
        """链式唤醒判断（网络/解析拆至 care_engine.judge_wakeup，此处组装状态+注入用量记录）"""
        try:
            import datetime as _dt
            now = _dt.datetime.now()
            last_chat = ''
            if self.chat_history_msgs:
                last_chat = (self.chat_history_msgs[-1].get('content') or '')[:80]
            idle = self._user_idle_minutes()
            week = '一二三四五六日'[now.weekday()]
            state = f'现在是{now.strftime("%H:%M")}（周{week}），电脑空闲 {idle:.0f} 分钟'
            if last_chat:
                state += f'，最近对话：{last_chat}'
            return judge_wakeup(
                self._current_api_key(), self._current_model(), state,
                CHARACTERS[self.current]['name'],
                record_cb=self._record_api_usage,
                endpoint=self._current_endpoint(),
            )
        except Exception:
            return None

    def _wakeup_worker(self):
        """唤醒判断线程：结果决定是否冒泡 + 更新下次唤醒间隔（链式）"""
        interval = None
        try:
            j = self._ai_wakeup_judge()
            if j:
                try:
                    interval = max(10, min(int(j.get('next_minutes', 60)), 360)) * 60
                except Exception:
                    interval = None
                if j.get('act') == 'yes' and j.get('message'):
                    self.wakeup_signal.emit(j['message'].strip())
        finally:
            if interval is None:
                interval = random.uniform(480, 1200)
            self._active_chat_next = time.time() + interval

    def _display_wakeup(self, msg):
        """主线程槽：主动关心以浮动气泡显示，不写入对话历史（v6.19 不再污染聊天记录）"""
        if not msg:
            return
        display, emotion = self._strip_emotion_tag(msg)
        if emotion:
            self._apply_emotion(emotion)
        self.say_plain(display, immediate=True)

    def _ai_followup(self, topic):
        """回访机制（消息生成拆至 care_engine.followup_message，此处组装状态+发信号）"""
        def work():
            try:
                import datetime as _dt
                now = _dt.datetime.now()
                idle = self._user_idle_minutes()
                last_chat = ''
                if self.chat_history_msgs:
                    last_chat = (self.chat_history_msgs[-1].get('content') or '')[:60]
                week = '一二三四五六日'[now.weekday()]
                state = f'现在是{now.strftime("%H:%M")}（周{week}），用户已空闲 {idle:.0f} 分钟'
                if last_chat:
                    state += f'，最近对话：{last_chat}'
                msg = followup_message(
                    self._current_api_key(), self._current_model(), state, topic,
                    CHARACTERS[self.current]['name'],
                    record_cb=self._record_api_usage,
                    endpoint=self._current_endpoint(),
                )
                if msg:
                    self.wakeup_signal.emit(msg)
            except Exception:
                pass
        import threading
        threading.Thread(target=work, daemon=True).start()

    def _check_active_chat(self):
        """主动关心检查：到点触发。AI 可用→链式判断；AI 不可用→随机台词兜底"""
        if not self.active_chat_enabled or self.sleeping:
            return
        if self._edge_side is not None and self._edge_mode == 'peek' and not self._edge_popped:
            return
        now = time.time()
        if now < self._active_chat_next:
            return
        if self.ai_enabled:
            import threading
            threading.Thread(target=self._wakeup_worker, daemon=True).start()
        else:
            # AI 不可用：随机台词兜底（原心跳）
            lines = self._char_lines('greetings')
            extra = ['该喝水啦～', '要不要休息一下眼睛？', '坐久了记得站起来走走～', '今天也要加油鸭！'] if getattr(self, 'language', 'zh') != 'en' else ['Time for some water～', 'Rest your eyes a bit?', 'Stand up and stretch!', 'Keep going today!']
            lines = (lines or []) + extra
            self.say_plain(random.choice(lines))
            self._active_chat_next = now + random.uniform(480, 1200)

    def toggle_active_chat(self):
        """开关主动关心（链式+回访，AI 自主调度唤醒）"""
        self.active_chat_enabled = not self.active_chat_enabled
        self._save_cfg_value('active_chat', self.active_chat_enabled)
        state = '已开启' if self.active_chat_enabled else '已关闭'
        mode = 'AI 智能判断（链式唤醒+回访）' if self.active_chat_enabled else ''
        self._append_chat('桌宠', f'主动关心{state}{mode}')
        self.say_plain(f'主动关心{state}', immediate=True)

    def _run_plugin_menu(self, command):
        """执行 menu 类插件的菜单命令（v6.22，结果用气泡提示不污染对话）"""
        result = self.plugin_mgr.handle_menu(command)
        if result:
            self.say_plain(str(result), immediate=True)

    def _chat_with_ai(self):
        """聚焦聊天输入框"""
        if not self.ai_enabled:
            self._append_chat('桌宠', '还没配置 AI 呢！在 config.json 里加 deepseek_api_key 就能和我聊天了')
            return
        self.chat_input.setFocus()

    def random_action(self):
        """随机做一个动作（说话/思考/场景动作），保证与上次不重复"""
        import random as rnd
        candidates = ['say', 'think'] + list(SCENE_ACTIONS.keys())
        last = getattr(self, '_last_random', None)
        if last in candidates and len(candidates) > 1:
            candidates.remove(last)
        pick = rnd.choice(candidates)
        self._last_random = pick
        if pick == 'say':
            self.say_random()
        elif pick == 'think':
            self.do_thinking()
        else:
            self.play_scene(pick)

    # ---------- 好感度关系面板（v6.30） ----------
    def _open_relation(self):
        if getattr(self, '_relation_dialog', None) is not None:
            try:
                self._relation_dialog.close()
            except Exception:
                pass
        self._relation_dialog = RelationDialog(
            self.affection, self.current, CHARACTERS[self.current]['name'])
        self._relation_dialog.show()

    # ---------- 好感度 Phase2 交互（v6.30） ----------
    def _handle_affection(self, result, role=None):
        """好感度事件结果统一处理：里程碑自动记录回忆 + 头顶提示"""
        if not result or result.get('blocked'):
            return
        role = role or self.current
        notes = []
        if result.get('leveled_up'):
            notes.append(f'等级提升到 Lv.{result["new_level"]}')
        if result.get('stage_changed'):
            notes.append(f'关系进入「{result["new_stage"]}」阶段')
        for t in result.get('unlocked_titles') or []:
            notes.append(f'获得称号「{t}」')
        if notes:
            try:
                self.memories.add(role, 'milestone', '；'.join(notes),
                                  affection_at=self.affection.snapshot(role)['affection'])
            except Exception:
                pass
            self._show_pet_bubble('、'.join(notes) + '！', 4)

    def _show_pet_bubble(self, text, secs=3):
        """角色头顶提示气泡（复用 CostBubble 动画）"""
        try:
            b = CostBubble(self, text, '#6ecb7a')
            b.show_bubble(max(8, self.width() // 2 - len(text) * 6), 8, duration=secs * 1000)
        except Exception:
            pass

    def _on_cost_bubble(self, cost):
        """API 费用气泡（主线程，跨线程信号）"""
        try:
            b = CostBubble(self, f'-¥{cost:.3f}', '#ff8a8a' if cost > 0.1 else '#9fd0ff')
            b.show_bubble(self.width() // 2 - 25, 8)
        except Exception:
            pass

    def _feed_pet(self):
        """喂食：恢复饱食度 + 好感（冷却 30 分钟）"""
        r = self.affection.feed(self.current)
        if r.get('blocked'):
            self._show_pet_bubble('刚喂过啦，过会儿再喂～')
            return
        self._handle_affection(r)
        try:
            self._show_state_image('kiss')  # v6.30 喂食成功：撒娇亲亲
        except Exception:
            pass
        self._show_pet_bubble(f'好吃！饱食度 {r.get("satiety", 100):.0f}%，好感 +2')

    def _open_games(self):
        """打开小游戏窗口"""
        if getattr(self, '_game_window', None) is not None:
            try:
                self._game_window.close()
            except Exception:
                pass
        self._game_window = GameWindow(self._on_game_result, self)
        self._game_window.show()

    def _on_game_result(self, win, score=0, game=None):
        """小游戏结果 → 好感度事件 + 高分里程碑 + 动作状态图"""
        try:
            r = self.affection.trigger(self.current, 'game_win' if win else 'game_play')
            self._handle_affection(r)
            # 高分里程碑（v6.30）：破纪录 → 庆祝 + 回忆 + 额外好感
            if game and score:
                try:
                    rec = self.affection.record_best(self.current, game, score)
                    if rec['is_record']:
                        self.memories.add(
                            self.current, 'milestone', f'「{game}」新纪录 {score} 分',
                            f'打破了之前 {rec["prev"]} 分的纪录',
                            affection_at=self.affection.snapshot(self.current)['affection'])
                        self._show_pet_bubble(f'🏆 「{game}」新纪录 {score} 分！', 4)
                        self.affection.trigger(self.current, 'chat')  # 破纪录额外好感
                except Exception:
                    pass
            try:
                self._show_state_image('victory' if win else 'defeat')
            except Exception:
                pass
            if win:
                self.play_scene('happy')
        except Exception:
            pass

    def _check_satiety(self):
        """饱食度巡检：低饱食切饥饿状态图 + 提示（零惩罚，不扣好感；每小时最多提示一次）"""
        try:
            s = self.affection.satiety(self.current)
            if s < 30:
                # v6.30 饥饿状态图（素材已应用后生效）
                try:
                    self._show_state_image('hungry')
                except Exception:
                    pass
                if time.time() - getattr(self, '_last_satiety_warn', 0) > 3600:
                    self._last_satiety_warn = time.time()
                    self._show_pet_bubble('肚子好饿…喂我吃点东西嘛 (｡•́︿•̀｡)')
        except Exception:
            pass

    # ---------- 情感选项（galgame 选择支，v6.30 Phase3b） ----------
    def _render_choices(self):
        """把待展示的选项按钮追加到 AI 回复的同一气泡（打字机完成后调用）"""
        choices = getattr(self, '_pending_choices', None) or []
        if not choices:
            return
        self._pending_choices = None
        if self.chat_type_timer.isActive():
            # 打字机还在渲染正文：等完成回调（_chat_type_tick）再追加，避免按钮插在文本中间
            return
        content = getattr(self, '_chat_type_content', None)
        if content is None:
            import datetime as _dt
            ts = _dt.datetime.now().strftime('%m-%d %H:%M')
            _, content = self._new_bubble('桌宠', ts, is_user=False, text='')
        self._add_choice_buttons(content, choices)
        self._chat_scroll_bottom()

    def _add_choice_buttons(self, content, choices):
        """在指定气泡内容区添加选项按钮（A/B/C，带情感标签 ❤️+n）"""
        letters = ['A', 'B', 'C']
        for i, c in enumerate(choices):
            if isinstance(c, dict):
                label = c.get('text', '')
                aff = c.get('affect')
                tag = f'  ❤️+{aff}' if aff else ''
            else:
                label = str(c)
                tag = ''
            btn = QPushButton(f'{letters[i]}. {label}{tag}')
            btn.setStyleSheet(
                'QPushButton { background:#2a3a55; color:#dce3f0; border:1px solid #3a4a66;'
                ' border-radius:8px; padding:8px 12px; text-align:left; font-size:13px; }'
                'QPushButton:hover { background:#35507a; border-color:#7fb2ff; }'
                'QPushButton:disabled { background:#1c2740; color:#667; border-color:#24314a; }')
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked, c=c, b=btn: self._send_choice(c, b))
            content.addWidget(btn)

    def _send_choice(self, choice, btn=None):
        """用户点击选项：禁用整组按钮防止重复选择，作为用户消息发送 + 好感度 +1(+affect)"""
        if isinstance(choice, dict):
            text = choice.get('text', '')
            aff = choice.get('affect')
        else:
            text = str(choice)
            aff = None
        if btn is not None:
            try:
                parent = btn.parentWidget()
                if parent is not None:
                    for b in parent.findChildren(QPushButton):
                        b.setEnabled(False)
            except Exception:
                pass
        try:
            if aff:
                # 情感增量：额外触发对应好感度（affect 次 chat 事件近似，或直接按数值加成）
                for _ in range(min(3, int(aff))):
                    self.affection.trigger(self.current, 'chat')
            else:
                self.affection.trigger(self.current, 'chat')
        except Exception:
            pass
        self._append_chat('我', text)
        self.chat_history_msgs.append({'role': 'user', 'content': text})
        self._save_chat_memory()
        self.ask_ai(text)

    # ---------- 回忆相册（v6.30 Phase3） ----------
    def _open_memories(self):
        dlg = MemoriesDialog(self.memories, self.current, CHARACTERS[self.current]['name'], self)
        dlg.exec()

    def _open_settings(self, page=0):
        """打开统一设置窗口（page 指定初始分类）"""
        dlg = SettingsDialog(self, MODEL_REGISTRY, parent=self)
        try:
            if 0 <= int(page) < dlg.nav.count():
                dlg.nav.setCurrentRow(int(page))
        except Exception:
            pass
        dlg.exec()
        self._load_ai_config()      # 关掉后再热加载一次，菜单/角色表立即反映改动

    def _build_context_menu(self):
        """构建右键菜单，返回 (menu, acts)。
        拆成独立方法是为了能单独校验菜单内容（menu.exec 会阻塞，无法直接测）。

        Phase 5 重构：一级从 10 项压到 6 项——「动作」留在互动、「配置」收进设置窗口、
        角色/性格/立绘合并为「形象」、关系与用量合并为「状态」。
        功能一个不删，设置窗口里都能找到。"""
        T = self._t
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { font-size: 13px; }")
        acts = {}

        # 1. 和 AI 聊天（最高频，置顶）
        acts['chat'] = menu.addAction(T('menu_chat'))

        # 2. 互动：只放「做一件事」（动作 / 玩法 / 开关）
        imenu = menu.addMenu(T('menu_interact'))
        imenu.addAction(T('say')).triggered.connect(lambda: self.say_random())
        imenu.addAction(T('think')).triggered.connect(lambda: self.do_thinking())
        imenu.addAction(T('random')).triggered.connect(lambda: self.random_action())
        imenu.addSeparator()
        imenu.addAction('🍖 喂食').triggered.connect(self._feed_pet)
        imenu.addAction('🎮 小游戏').triggered.connect(self._open_games)
        imenu.addSeparator()
        imenu.addAction(T('sleep')).triggered.connect(lambda: self.toggle_sleep())
        imenu.addAction(T('toggle_chat')).triggered.connect(lambda: self.toggle_chat_panel())
        imenu.addSeparator()
        # 场景动作：原先「常用 5 个 + 更多动作 7 个」两级嵌套，合并成一层 12 项
        scene_menu = imenu.addMenu('🎬 场景动作')
        for sk, (label, _desc) in SCENE_ACTIONS.items():
            scene_menu.addAction(label).triggered.connect(lambda checked, k=sk: self.play_scene(k))
        imenu.addSeparator()
        act_active = imenu.addAction(
            T('active_care') + (T('on') if self.active_chat_enabled else T('off')))
        act_active.setCheckable(True)
        act_active.setChecked(bool(self.active_chat_enabled))
        act_active.triggered.connect(lambda: self.toggle_active_chat())

        # 3. 形象：角色 / 立绘 / 性格（合并原「角色」「性格切换」与立绘模式）
        fmenu = menu.addMenu('🎭 形象')
        # 角色项由模型档案生成（新增档案即出现，无需改代码）
        for _pk in MODEL_REGISTRY.keys():
            _prof = MODEL_REGISTRY.get(_pk)
            _ra = fmenu.addAction(_prof.display_name if _prof else _pk)
            _ra.setCheckable(True)
            _ra.setChecked(_pk == self.current)
            _ra.triggered.connect(lambda checked=False, k=_pk: self.switch_char(k))
        fmenu.addSeparator()
        ma_static = fmenu.addAction(T('mode_static'))
        ma_static.setCheckable(True)
        ma_static.setChecked(getattr(self, 'display_mode', 'static') != 'live2d')
        ma_static.triggered.connect(lambda: self._set_display_mode('static'))
        ma_l2d = fmenu.addAction(T('mode_live2d'))
        ma_l2d.setCheckable(True)
        ma_l2d.setChecked(getattr(self, 'display_mode', 'static') == 'live2d')
        ma_l2d.triggered.connect(lambda: self._set_display_mode('live2d'))
        fmenu.addSeparator()
        pmenu = fmenu.addMenu(T('menu_personality'))
        for pk, pl in [('温柔', 'person_gentle'), ('傲娇', 'person_tsundere'),
                       ('吐槽', 'person_sarcastic'), ('元气', 'person_energetic'),
                       ('高冷', 'person_cold')]:
            pmenu.addAction(T(pl)).triggered.connect(lambda checked, pp=pk: self._set_personality(pp))
        fmenu.addSeparator()
        # v6.51：主题切换入口（此前只有 AI 工具 set_theme 能切，用户自己没有入口）
        thmenu = fmenu.addMenu('🎨 主题')
        _cur_theme = str(getattr(self, 'current_theme', 'default') or 'default')
        try:
            _theme_names = ['default'] + [str(x) for x in self.plugin_mgr.theme_names()]
        except Exception:
            _theme_names = ['default']
        for _tn in _theme_names:
            _ta = thmenu.addAction('默认（深色）' if _tn == 'default' else _tn)
            _ta.setCheckable(True)
            _ta.setChecked(_tn == _cur_theme)
            _ta.triggered.connect(lambda checked=False, t=_tn: self.apply_theme_named(t))
        fmenu.addSeparator()
        fmenu.addAction('🎯 更多形象设置…').triggered.connect(lambda: self._open_settings(2))

        # 4. 贴边模式（状态开关，留在一级）
        acts['edgemode'] = menu.addAction(
            T('edge_mode') + (T('edge_hidden') if self._edge_mode == 'peek' else T('edge_peek')))

        # 5. 状态：关系 + 用量统计（合并原「关系」与「工具」里的统计项）
        stmenu = menu.addMenu('📊 状态')
        stmenu.addAction('❤️ 与 %s 的关系' % CHARACTERS[self.current]['name']).triggered.connect(
            self._open_relation)
        stmenu.addAction('📖 回忆相册').triggered.connect(self._open_memories)
        stmenu.addSeparator()
        umenu = stmenu.addMenu('📈 API 用量')
        umenu.addAction('📊 统计悬浮窗').triggered.connect(lambda: self._toggle_api_stats_window())
        umenu.addAction('📈 按模型统计').triggered.connect(self._show_model_stats)
        umenu.addAction('🔄 查看统计历史').triggered.connect(self._show_api_stats_history)

        # 6. 设置…（统一设置窗口，替代原来的 40+ 项设置子菜单）
        acts['settings'] = menu.addAction('⚙️ 设置…')
        acts['settings'].triggered.connect(self._open_settings)

        # 7. 插件（有 menu 类插件时才出现，避免空项占位）
        plugin_menu_items = self.plugin_mgr.menu_items()
        if plugin_menu_items:
            plmenu = menu.addMenu('🔌 插件')
            for label, cmd, _pname in plugin_menu_items:
                plmenu.addAction('%s' % label).triggered.connect(
                    lambda checked, c=cmd: self._run_plugin_menu(c))

        menu.addSeparator()
        acts['hide'] = menu.addAction(T('hide_tray'))
        menu.addSeparator()
        acts['exit'] = menu.addAction(T('exit'))
        return menu, acts
    def contextMenuEvent(self, event):
        # 扒边贴边状态：右键 = 弹出（锁定其他功能）
        if self._edge_side is not None and self._edge_mode == 'peek' and not self._edge_popped:
            self._popup_from_dock()
            return
        menu, acts = self._build_context_menu()
        chosen = menu.exec(event.globalPos())
        if chosen == acts['chat']:
            self._chat_with_ai()
        elif chosen == acts['edgemode']:
            self.toggle_edge_mode()
        elif chosen == acts['hide']:
            self.hide_to_tray()
        elif chosen == acts['exit']:
            self.quit_app()

    def _set_language(self, lang):
        """切换界面语言（zh/en），保存并热加载"""
        if lang not in ('zh', 'en'):
            return
        if self._save_cfg_value('language', lang):
            # 更新输入框 placeholder
            self.chat_input.setPlaceholderText(self._t('chat_placeholder'))
            msg = '语言已切换为中文' if lang == 'zh' else 'Language switched to English'
            self._append_chat('桌宠', msg)
            self.say_plain(msg, immediate=True)


def main():
    # 显式设置 DPI awareness（必须在 QApplication 创建之前！）
    # pythonw 默认 DPI UNAWARE，从 bat/explorer 启动时 Win11 会给无边框窗口
    # 画灰色边框 + 白色背景（老问题根因）。设为 PER_MONITOR_DPI_AWARE 后透明正常。
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()  # 回退：SYSTEM_DPI_AWARE
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    pet = PetWidget()
    pet.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
