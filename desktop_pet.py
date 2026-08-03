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
import winsound
from PySide6.QtCore import Qt, QTimer, QPoint, QRect, QRectF, Signal, Slot as QtSlot
from PySide6.QtGui import QPixmap, QPainter, QColor, QAction, QPainterPath, QFont, QIcon, QImage, QTransform, QCursor
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QMenu, QGraphicsOpacityEffect,
    QVBoxLayout, QHBoxLayout, QPushButton, QFrame, QSizePolicy,
    QSystemTrayIcon, QTextBrowser, QTextEdit, QLineEdit, QInputDialog, QScrollArea
)

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
MEMORY_PATH = os.path.join(BASE_DIR, 'memory.json')
TODO_PATH = os.path.join(BASE_DIR, 'todos.json')

def asset(role, state):
    return os.path.join(ASSETS, role, f'{role}_{state}.png')

# ============ 国际化（v6.20，右键菜单/提示/AI 回复语言） ============
UI_ZH = {
    'menu_role': '🎭 角色', 'menu_chat': '🤖 和 AI 聊天', 'menu_interact': '💬 互动',
    'say': '💬 说句话', 'think': '🤔 思考一下', 'random': '🎲 随机动作', 'sleep': '💤 睡觉/唤醒',
    'toggle_chat': '💬 隐藏/显示聊天窗口', 'active_care': '💗 主动关心',
    'edge_mode': '📌 贴边模式：', 'edge_hidden': '完全消失', 'edge_peek': '扒边',
    'menu_actions': '🎬 动作', 'menu_personality': '🎭 性格切换', 'menu_settings': '⚙️ 设置',
    'api_setting': '🔑 API 设置…', 'model_menu': '🎯 角色模型', 'current': '当前',
    'style_menu': '💬 回复风格', 'token_menu': '📝 回复长度', 'custom': '🎯 自定义…',
    'city': '🌆 默认城市…', 'custom_personality': '🎭 自定义性格…',
    'memory_menu': '🧠 记忆管理', 'view_memory': '📋 查看记忆', 'delete_memory': '🗑 删除一条…', 'clear_memory': '🧹 清空全部…',
    'export_chat': '📤 导出聊天记录', 'autostart': '🚀 开机自启', 'on': '（已开）', 'off': '（已关）',
    'hide_tray': '🏠 最小化到托盘', 'exit': '✕ 退出',
    'language_menu': '🌐 语言', 'language_zh': '中文', 'language_en': 'English',
    'chat_placeholder': '和桌宠聊天…（Enter 发送，Shift+Enter 换行，/clear 清空）',
    'person_gentle': '温柔', 'person_tsundere': '傲娇', 'person_sarcastic': '吐槽', 'person_energetic': '元气', 'person_cold': '高冷',
    'style_short': '极简', 'style_normal': '标准', 'style_detailed': '详细',
    'tok_short': '短（500）', 'tok_normal': '标准（1000）', 'tok_long': '长（2000）', 'tok_xlong': '超长（4000）', 'tok_max': '极长（16000）',
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
    'api_setting': '🔑 API Settings…', 'model_menu': '🎯 Models', 'current': 'Current',
    'style_menu': '💬 Reply style', 'token_menu': '📝 Reply length', 'custom': '🎯 Custom…',
    'city': '🌆 Default city…', 'custom_personality': '🎭 Custom personality…',
    'memory_menu': '🧠 Memory', 'view_memory': '📋 View memory', 'delete_memory': '🗑 Delete one…', 'clear_memory': '🧹 Clear all…',
    'export_chat': '📤 Export chat', 'autostart': '🚀 Auto-start', 'on': ' (ON)', 'off': ' (OFF)',
    'hide_tray': '🏠 Minimize to tray', 'exit': '✕ Exit',
    'language_menu': '🌐 Language', 'language_zh': '中文', 'language_en': 'English',
    'chat_placeholder': 'Chat with pet… (Enter send, Shift+Enter newline, /clear reset)',
    'person_gentle': 'Gentle', 'person_tsundere': 'Tsundere', 'person_sarcastic': 'Sarcastic', 'person_energetic': 'Energetic', 'person_cold': 'Cold',
    'style_short': 'Minimal', 'style_normal': 'Normal', 'style_detailed': 'Detailed',
    'tok_short': 'Short (500)', 'tok_normal': 'Normal (1000)', 'tok_long': 'Long (2000)', 'tok_xlong': 'Extra (4000)', 'tok_max': 'Max (16000)',
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

# ============ 角色配置 ============
CHARACTERS = {
    'flash': {
        'name': 'V4 Flash',
        'sub': '浅蓝和服 · 快言快语',
        'color': QColor(176, 196, 222),
        'greetings': [
            '我在呢！有什么要帮忙的？',
            'Flash 模式，快问快答～',
            '今天也是效率满满的一天！',
            '要不要试试 V4 Pro 大哥？它想事情更细。',
            '别急，我打字很快的！',
            '你盯着我看好久了，我害羞了啦！',
            '今天天气不错，适合写代码！',
            '诶？你发现我在摸鱼了？',
        ],
        'happy_lines': ['耶！你戳我！(*≧▽≦)', '嘻嘻，痒痒的～', '今天心情超好！'],
        'think_lines': ['嗯…这个问题让我想想。', '正在高速运转中…', '我的小脑瓜快冒烟啦！'],
        'greetings_en': [
            'Here! Need any help?',
            'Flash mode, quick Q&A～',
            'Another productive day!',
            'Want to try V4 Pro? It thinks deeper.',
            'No worries, I type fast!',
            'You have been staring at me… I am blushing!',
            'Nice weather today, good for coding!',
        ],
        'happy_lines_en': ['Yay! You poked me! (*≧▽≦)', 'Hee hee, that tickles～', 'Feeling great today!'],
        'think_lines_en': ['Hmm… let me think about this.', 'Processing at full speed…', 'My little brain is smoking!'],
    },
    'pro': {
        'name': 'V4 Pro',
        'sub': '深蓝女仆 · 深思熟虑',
        'color': QColor(46, 74, 142),
        'greetings': [
            '我在。有什么需要仔细思考的吗？',
            '已经帮你推演了三套方案。',
            'V4 Pro 模式，专注深度分析。',
            '别急，我把每一条都查证过再回答。',
            '这个需求需要拆解一下，我先列个提纲。',
            '嗯…这个问题值得深入想一想。',
            '数据都核对过了，可以放心用。',
            '要不要我帮你做个误差分析？',
        ],
        'happy_lines': ['能被你信任是我的荣幸。', '分析完成，一切尽在掌握。'],
        'think_lines': ['让我先梳理一下逻辑链。', '推演中…排除所有可能干扰项。', '这个问题有三层因果关系。'],
        'scared_lines': ['啊！别戳了别戳了！', '饶命！我这就认真思考！', '冷静！我先梳理一下逻辑！'],
        'greetings_en': [
            'I am here. Anything that needs deep thought?',
            'Already worked out three approaches for you.',
            'V4 Pro mode, focused deep analysis.',
            'No rush — I verify every detail before answering.',
            'This needs breaking down; let me outline it first.',
            'Hmm… this deserves deeper thought.',
            'All data cross-checked, safe to use.',
            'Want me to run an error analysis?',
        ],
        'happy_lines_en': ['Being trusted by you is my honor.', 'Analysis complete, all under control.'],
        'think_lines_en': ['Let me sort out the logic chain first.', 'Reasoning… eliminating all possible interferences.', 'This problem has three layers of causality.'],
        'scared_lines_en': ['Ah! Stop poking me!', 'Mercy! I will think seriously!', 'Calm down! Let me sort out the logic first!'],
    },
}

GREET_INTERVAL = (20 * 60 * 1000, 40 * 60 * 1000)

# 场景动作立绘
SCENE_ACTIONS = {
    'lying': ('🛏️ 趴地板', '慵懒趴地翘脚'),
    'eating': ('🍜 吃面', '抱碗吃面'),
    'phone': ('📱 玩手机', '低头刷手机'),
    'hug_whale': ('🐋 抱玩偶', '抱着鲸鱼玩偶蹭蹭'),
    'typing': ('💻 打字', '认真码字工作'),
    'reading': ('📖 看书', '沉浸阅读'),
    'coffee': ('☕ 喝咖啡', '优雅小酌咖啡'),
    'music': ('🎧 听歌', '戴耳机陶醉'),
    'exercise': ('💪 健身', '举哑铃锻炼'),
    'flower': ('🌸 捧花', '害羞捧花'),
    'gift': ('🎁 礼物', '开心捧礼物'),
    'umbrella': ('🌂 撑伞', '雨中撑伞漫步'),
}

# ============ AI 工具定义（function calling） ============
AI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "打开电脑上的应用程序或文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "应用名，如：记事本、计算器、画图、cmd、powershell、pycharm、vscode、浏览器、资源管理器，或直接输入程序名/路径/盘符（如 D:\\ 或用户主目录），或用用户自定义别名"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_time",
            "description": "获取当前日期和时间",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "计算数学表达式",
            "parameters": {
                "type": "object",
                "properties": {
                    "expr": {"type": "string", "description": "数学表达式，如 2+3*4"}
                },
                "required": ["expr"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": "设置定时提醒。相对时间直接换算秒数；如需绝对时间（如 下午3点）请先调用 get_time 获取当前时间，再计算正确的秒数",
            "parameters": {
                "type": "object",
                "properties": {
                    "seconds": {"type": "integer", "description": "多少秒后提醒（1-86400）"},
                    "text": {"type": "string", "description": "提醒内容"}
                },
                "required": ["seconds", "text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "lock_screen",
            "description": "锁定电脑屏幕",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_weather",
            "description": "查询城市天气。仅当用户明确要求查天气/温度/降雨/空气质量/适不适合出门时才调用；用户问美食/景点/地理等与天气无关的问题时不要调用",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市名，如 重庆"}
                },
                "required": ["city"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_powershell",
            "description": "在 Windows PowerShell 中执行命令并返回输出。适合：查询系统/服务/文件/网络(ping/ipconfig)/磁盘状态等。禁止删除、关机、格式化、写文件等危险操作（工具层会自动拦截并拒绝）",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "PowerShell 命令，如 Get-Process | Sort-Object WS -Descending | Select-Object -First 5"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_info",
            "description": "获取电脑系统信息：CPU 型号/占用、内存总量/剩余、磁盘、系统版本、开机时间",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_processes",
            "description": "列出当前最占内存的前 N 个进程（默认 10 个）",
            "parameters": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer", "description": "进程数量，默认 10"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "kill_process",
            "description": "结束指定名称的进程（如 notepad、chrome）。系统关键进程会被保护拒绝",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "进程名，如 notepad 或 notepad.exe"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "control_volume",
            "description": "精确控制系统音量：set=设置到指定百分比（如 调到60%）；up/down=相对调大调小；mute/unmute=静音/取消静音",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["set", "up", "down", "mute", "unmute"], "description": "操作类型：set 精确设置百分比，up/down 相对调节，mute/unmute 静音"},
                    "percent": {"type": "integer", "description": "目标音量百分比 0-100，仅 action=set 时必填"},
                    "steps": {"type": "integer", "description": "相对调节步数（每步 1%），action=up/down 时使用，默认 5"}
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "搜索电脑上的文件（按文件名关键词），默认在用户目录下搜索",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "文件名关键词，如 期末报告"},
                    "path": {"type": "string", "description": "搜索起始目录，可选，默认用户主目录"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_clipboard",
            "description": "读取剪贴板文本内容。适合：用户复制了文字/数据，需要整理、分析、转表格时",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_clipboard",
            "description": "把文本写入剪贴板（用户可直接粘贴）。适合：生成代码/文字后让用户复制",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "要写入剪贴板的文本"}
                },
                "required": ["text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "manage_todo",
            "description": "待办清单管理：add=添加待办（text），list=列出全部，done=标记完成（id 或 text），remove=删除（id 或 text）。用户说\"记住要做XX\"\"提醒我交作业\"等适合 add",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["add", "list", "done", "remove"], "description": "操作类型"},
                    "text": {"type": "string", "description": "待办内容（add 必填；done/remove 可用文本匹配）"},
                    "id": {"type": "string", "description": "待办 ID（done/remove 用）"}
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_followup",
            "description": "安排回访：对话结束后过一段时间主动找用户关心一下。适合用户提到重要事件（去吃饭/考试/开会/睡觉/办事/心情不好）时安排。seconds=多少秒后回访(600-21600)，reason=要关心的主题",
            "parameters": {
                "type": "object",
                "properties": {
                    "seconds": {"type": "integer", "description": "多少秒后回访（600-21600，即10分钟到6小时）"},
                    "reason": {"type": "string", "description": "回访要关心的主题，如 用户去吃饭了"}
                },
                "required": ["seconds", "reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "memorize",
            "description": "长期记忆：记住用户的重要信息（偏好/习惯/个人事实/任务目标/重要结论）。add=新增记忆，update=更新已有记忆（需 id），delete=遗忘某条记忆（需 id 或 content）。只记录持久有价值的信息，不要记一次性的闲聊。重要度 importance 1-5（5=最重要）。role：both=两个角色共享（默认，用户偏好等通用信息），flash=仅Flash角色，pro=仅Pro角色（角色专属信息如角色名字/人设用对应的 role）",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["add", "update", "delete"], "description": "add 新增 / update 更新 / delete 遗忘"},
                    "content": {"type": "string", "description": "记忆内容（add/update 时必填）"},
                    "importance": {"type": "integer", "description": "重要度 1-5，默认 3"},
                    "id": {"type": "string", "description": "记忆 ID（update/delete 时用，可通过对话让用户提供或从上下文推断）"},
                    "role": {"type": "string", "enum": ["both", "flash", "pro"], "description": "记忆归属角色：both=共享默认，flash=仅Flash，pro=仅Pro"}
                },
                "required": ["action"]
            }
        }
    },
]

# ============ PowerShell 安全执行（v6） ============
import re as _re
import subprocess as _subprocess

# 危险命令检测（精确匹配，避免误杀 Format-Table 等常用命令）
DANGEROUS_PATTERNS = [
    r'\bshutdown\b', r'\brestart\b', r'\breboot\b', r'\bformat\s+[a-zA-Z]:', r'\bdiskpart\b',
    r'\bremove-item\b', r'\brm\s+-r', r'\brmdir\s+/s', r'\bdel\s+/s', r'\breg\s+delete\b',
    r'\bnet\s+user\b', r'\bclear-recyclebin\b', r'\bformat-volume\b',
    r'set-content\b', r'add-content\b', r'out-file\b', r'new-item\b',
    r'stop-process\s+-force', r'\brmdir\b.*-recurse',
]
DANGEROUS_RE = [_re.compile(p, _re.IGNORECASE) for p in DANGEROUS_PATTERNS]


def _check_dangerous(cmd):
    """返回拦截提示，无危险返回 None"""
    for rx in DANGEROUS_RE:
        if rx.search(cmd):
            return f'危险操作已拦截（匹配 {rx.pattern}）：删除/关机/格式化/写文件/强制结束等操作我不执行，请手动操作。'
    return None


def _read_clipboard_text():
    """读取剪贴板文本（纯 ctypes，worker 线程安全）"""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        # 64 位下句柄/指针必须显式声明 restype + argtypes，否则默认 32 位 c_int 截断
        user32.GetClipboardData.restype = ctypes.c_void_p
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        if not user32.OpenClipboard(0):
            return None
        try:
            if not user32.IsClipboardFormatAvailable(13):  # CF_UNICODETEXT
                return None
            h = user32.GetClipboardData(13)
            if not h:
                return None
            p = kernel32.GlobalLock(h)
            try:
                return ctypes.c_wchar_p(p).value or ''
            finally:
                kernel32.GlobalUnlock(h)
        finally:
            user32.CloseClipboard()
    except Exception:
        return None


def _write_clipboard_text(text):
    """写入剪贴板文本（纯 ctypes，worker 线程安全）"""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        user32.SetClipboardData.restype = ctypes.c_void_p
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        if not user32.OpenClipboard(0):
            return False
        try:
            user32.EmptyClipboard()
            data = str(text).encode('utf-16-le') + b'\x00\x00'
            h = kernel32.GlobalAlloc(0x0042, len(data))  # GMEM_MOVEABLE | GMEM_ZEROINIT
            if not h:
                return False
            p = kernel32.GlobalLock(h)
            if not p:
                return False
            ctypes.memmove(p, data, len(data))
            kernel32.GlobalUnlock(h)
            user32.SetClipboardData(13, h)
            return True
        finally:
            user32.CloseClipboard()
    except Exception:
        return False


def _run_ps(command, timeout=15, skip_check=False):
    """执行 PowerShell 命令：安全校验 + 超时 + UTF-8 + 输出截断"""
    if not skip_check:
        blocked = _check_dangerous(command)
        if blocked:
            return blocked
    try:
        full = f'[Console]::OutputEncoding=[Text.Encoding]::UTF8; $OutputEncoding=[Text.Encoding]::UTF8; {command}'
        p = _subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command', full],
            capture_output=True, text=True, timeout=timeout,
            encoding='utf-8', errors='replace', creationflags=_subprocess.CREATE_NO_WINDOW,
        )
        out = (p.stdout or '').strip()
        err = (p.stderr or '').strip()
        if not out and err:
            out = f'（错误）{err}'
        if not out:
            out = '（无输出，执行成功）'
        return out if len(out) <= 1500 else out[:1500] + '\n…（输出过长已截断）'
    except _subprocess.TimeoutExpired:
        return f'（超时：命令超过 {timeout} 秒未完成，已终止）'
    except Exception as e:
        return f'（执行失败：{e}）'


# ============ 精确音量控制（v6.1，IAudioEndpointVolume API） ============
_VOLUME_CS = r'''using System;
using System.Runtime.InteropServices;

[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
class MMDeviceEnumeratorComObject { }

[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator {
    int EnumAudioEndpoints(int dataFlow, int stateMask, out IMMDevice device);
    int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice device);
}

[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice {
    int Activate(ref Guid iid, int clsCtx, IntPtr pActivationParams, out IAudioEndpointVolume volume);
}

[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume {
    int RegisterControlChangeNotify(IntPtr pNotify);
    int UnregisterControlChangeNotify(IntPtr pNotify);
    int GetChannelCount(out int count);
    int SetMasterVolumeLevel(float level, Guid ctx);
    int SetMasterVolumeLevelScalar(float level, Guid ctx);
    int GetMasterVolumeLevel(out float level);
    int GetMasterVolumeLevelScalar(out float level);
    int SetChannelVolumeLevel(uint index, float level, Guid ctx);
    int SetChannelVolumeLevelScalar(uint index, float level, Guid ctx);
    int GetChannelVolumeLevel(uint index, out float level);
    int GetChannelVolumeLevelScalar(uint index, out float level);
    int SetMute(bool mute, Guid ctx);
    int GetMute(out bool mute);
}

public static class Volume {
    static IAudioEndpointVolume GetVolume() {
        IMMDeviceEnumerator enumerator = (IMMDeviceEnumerator)(new MMDeviceEnumeratorComObject());
        IMMDevice device;
        enumerator.GetDefaultAudioEndpoint(0, 1, out device);
        Guid iid = new Guid("5CDF2C82-841E-4546-9722-0CF74078229A");
        IAudioEndpointVolume volume;
        device.Activate(ref iid, 23, IntPtr.Zero, out volume);
        return volume;
    }
    public static float GetPercent() {
        float level;
        GetVolume().GetMasterVolumeLevelScalar(out level);
        return (float)Math.Round(level * 100f);
    }
    public static void SetPercent(float percent) {
        float v = Math.Max(0f, Math.Min(100f, percent)) / 100f;
        GetVolume().SetMasterVolumeLevelScalar(v, Guid.Empty);
    }
    public static bool GetMuted() {
        bool m;
        GetVolume().GetMute(out m);
        return m;
    }
    public static void SetMuted(bool mute) {
        GetVolume().SetMute(mute, Guid.Empty);
    }
}
'''


def _volume_ps(script):
    """执行带 Volume 类的 PowerShell 脚本"""
    ps = f'[Console]::OutputEncoding=[Text.Encoding]::UTF8; Add-Type -TypeDefinition @"\n{_VOLUME_CS}\n"@; {script}'
    return _run_ps(ps, timeout=20)



# blink 图相对 idle 的平移偏移（相位相关测得）：用于对齐整图切换眨眼
# 切换时其他部位完全重合，只有眼睛变化，不闪
BLINK_OFFSETS = {
    'flash': (0, 0),
    'pro': (0, 0),
}


def _hotkey_filter_factory(callback):
    """创建全局热键过滤器（WM_HOTKEY）"""
    import ctypes.wintypes  # 必须显式导入（Python 3.14 中 ctypes.wintypes 不随 ctypes 自动加载）
    from PySide6.QtCore import QAbstractNativeEventFilter
    class _HotkeyFilter(QAbstractNativeEventFilter):
        def nativeEventFilter(self, eventType, message):
            try:
                # PySide6 的 eventType 是 QByteArray（不是 str/bytes），message 是 VoidPtr
                et = bytes(eventType) if hasattr(eventType, '__bytes__') else str(eventType).encode('utf-8', 'ignore')
                if b'windows_generic_MSG' in et:
                    msg = ctypes.wintypes.MSG.from_address(int(message))
                    if msg.message == 0x0312 and msg.wParam == 1:  # WM_HOTKEY, id=1
                        callback()
                        return True, 0
            except Exception:
                pass
            return False, 0
    return _HotkeyFilter()


class PetWidget(QWidget):
    # 类级信号：AI 回复（跨线程安全）
    ai_reply_signal = Signal(str)
    ai_status_signal = Signal(str)  # AI 处理状态（思考中/正在执行xx）
    wakeup_signal = Signal(str)    # 主动消息（心跳/回访触发）
    confirm_signal = Signal(object)  # 危险操作确认请求（跨线程回调）
    weather_signal = Signal(str)   # 早安日报天气结果（跨线程安全）
    ocr_signal = Signal(str)       # OCR 识别结果（截图粘贴，跨线程安全）

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
        # AI 回复信号（类级定义，connect 跨线程槽）
        self.ai_reply_signal.connect(self._display_ai_reply)
        self.ai_status_signal.connect(self._update_ai_status)
        self.wakeup_signal.connect(self._display_wakeup)
        self.confirm_signal.connect(lambda fn: fn())  # 确认回调在主线程执行
        # 全局快捷键 Ctrl+Alt+P 呼出
        self._hotkey_installed = False
        try:
            app = QApplication.instance()
            if app is not None:
                self._hotkey_filter = _hotkey_filter_factory(self._on_global_hotkey)
                app.installNativeEventFilter(self._hotkey_filter)
                if ctypes.windll.user32.RegisterHotKey(None, 1, 0x0002 | 0x0001, 0x50):  # MOD_CONTROL|MOD_ALT, 'P'
                    self._hotkey_installed = True
        except Exception:
            self._hotkey_installed = False
        # 对话记忆 + 定时提醒 + 贴边
        self.chat_history_msgs = []
        self.personality = '温柔'
        self.memory_facts = []      # 长期事实记忆
        self.memory_summaries = []  # 会话摘要
        self._load_memory()
        self.todos = []             # 待办清单
        self._load_todos()
        self._load_chat_memory()
        self.reminders = []
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
        self.chat_panel.setStyleSheet("""
            QFrame { background-color: rgba(20,20,30,0.85); border-radius: 12px; }
            QTextBrowser {
                background: transparent; color: #eee; border: none;
                font-size: 12px; padding: 6px;
            }
            QTextEdit {
                background: rgba(255,255,255,0.12); color: #fff; border: none;
                border-radius: 8px; padding: 6px 10px; font-size: 12px;
            }
            QTextEdit:focus { background: rgba(255,255,255,0.18); }
            QTextEdit viewport { background: transparent; }
        """)
        chat_layout = QVBoxLayout(self.chat_panel)
        chat_layout.setContentsMargins(8, 4, 8, 8)
        chat_layout.setSpacing(6)

        # 拖拽把手（调整对话窗口高度）
        self.chat_drag_bar = QFrame(self.chat_panel)
        self.chat_drag_bar.setFixedHeight(6)
        self.chat_drag_bar.setCursor(Qt.SizeVerCursor)
        self.chat_drag_bar.setStyleSheet("background: rgba(255,255,255,0.15); border-radius: 3px;")
        chat_layout.addWidget(self.chat_drag_bar)

        # 聊天历史（只读）
        self.chat_history = QTextBrowser(self.chat_panel)
        self.chat_history.setOpenExternalLinks(False)
        self.chat_history.setPlaceholderText('')
        chat_layout.addWidget(self.chat_history, 1)

        # 输入框（多行自适应：内容多自动增高，超上限内部滚动）
        self.chat_input = QTextEdit(self.chat_panel)
        self.chat_input.setPlaceholderText(self._t('chat_placeholder'))
        self.chat_input.setAcceptRichText(False)  # 粘贴/拖入自动转纯文本，避免富文本格式污染背景
        self.chat_input.setFixedHeight(34)
        self.chat_input.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.chat_input.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chat_input.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.chat_input.document().contentsChanged.connect(self._auto_resize_input)
        self.chat_input.installEventFilter(self)
        chat_layout.addWidget(self.chat_input)

        # 底部拖拽把手（标准：下拉=扩大）
        self.chat_drag_bar_bottom = QFrame(self.chat_panel)
        self.chat_drag_bar_bottom.setFixedHeight(6)
        self.chat_drag_bar_bottom.setCursor(Qt.SizeVerCursor)
        self.chat_drag_bar_bottom.setStyleSheet("background: rgba(255,255,255,0.15); border-radius: 3px;")
        chat_layout.addWidget(self.chat_drag_bar_bottom)

        self.layout.addWidget(self.chat_panel, 0, Qt.AlignHCenter)
        self.chat_panel.setFixedWidth(420)
        self.chat_panel.setFixedHeight(240)
        self._chat_dragging = False
        self._chat_drag_mode = None   # None / 'v'（垂直把手）/ 'h'（左右边缘）
        self._chat_drag_from_bottom = False  # True=底部把手（下拉扩大），False=顶部把手（上拉扩大）
        self._chat_drag_start_y = 0
        self._chat_drag_start_h = 0
        self._chat_drag_start_x = 0
        self._chat_drag_start_w = 0
        self.chat_drag_bar.mousePressEvent = self._chat_drag_press
        self.chat_drag_bar.mouseMoveEvent = self._chat_drag_move
        self.chat_drag_bar.mouseReleaseEvent = self._chat_drag_release
        self.chat_drag_bar_bottom.mousePressEvent = self._chat_drag_press_bottom
        self.chat_drag_bar_bottom.mouseMoveEvent = self._chat_drag_move
        self.chat_drag_bar_bottom.mouseReleaseEvent = self._chat_drag_release
        # 左右边缘拖拽（对称扩展）
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
                    # 屏幕边界保护：坐标在屏幕外则移回屏幕内
                    screen = QApplication.primaryScreen()
                    if screen:
                        avail = screen.geometry()
                        if x < 0 or x > avail.right() - 100:
                            x = avail.right() - self.width() - 40
                        if y < 0 or y > avail.bottom() - 100:
                            y = avail.bottom() - self.height() - 60
                    self.move(x, y)
                    self.base_x, self.base_y = x, y
                    return
        except Exception:
            pass
        screen = QApplication.primaryScreen()
        if screen:
            avail = screen.geometry()
            self.move(avail.right() - self.width() - 40, avail.bottom() - self.height() - 60)
            self.base_x, self.base_y = self.x(), self.y()

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
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
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
        """从 config.json 读取 DeepSeek API 配置"""
        try:
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                key = cfg.get('deepseek_api_key', '')
                if key:
                    self.ai_key = key
                    self.model_flash = cfg.get('model_flash', 'deepseek-v4-flash')
                    self.model_pro = cfg.get('model_pro', 'deepseek-v4-pro')
                    self.ai_model = self._current_model()
                    self.ai_enabled = True
                self.pet_city = cfg.get('city', '重庆')
                self.personality = cfg.get('personality', '温柔')
                self.reply_style = cfg.get('reply_style', 'normal')  # short/normal/detailed
                self.language = cfg.get('language', 'zh')  # zh/en
                self.max_tokens = max(256, min(int(cfg.get('max_tokens', 1000)), 64000))
                self.display_mode = cfg.get('display_mode', 'static')  # static/live2d
                self.live2d_model = cfg.get('live2d_model', 'mao')  # Live2D 模型目录名
        except Exception:
            pass

    def _current_model(self):
        """按当前角色返回对应模型（Flash→flash模型，Pro→pro模型）"""
        if self.current == 'pro':
            return getattr(self, 'model_pro', 'deepseek-v4-pro')
        return getattr(self, 'model_flash', 'deepseek-v4-flash')

    def ask_ai(self, text):
        """调用 DeepSeek API 对话（线程执行，不卡 UI）"""
        self._load_ai_config()  # 热加载：每次聊天前刷新 config.json（改配置无需重启）
        if not self.ai_enabled:
            self._append_chat('桌宠', '还没配置 AI 呢！在 config.json 里加 deepseek_api_key 就能和我聊天了')
            return
        if getattr(self, '_ai_busy', False):
            self._append_chat('桌宠', '⏳ 还在想上一条呢，稍等一下～')
            return
        import threading
        self._ai_busy = True
        threading.Thread(target=self._ai_worker, args=(text,), daemon=True).start()

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
            with open(idx_path, 'w', encoding='utf-8') as f:
                json.dump({'built_at': time.time(), 'apps': apps}, f, ensure_ascii=False)
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
                        os.system(f'start "" "{display}" 2>nul')
                else:
                    # 只有名字没有路径（如 UWP）：尝试 start
                    os.system(f'start "" "{display}" 2>nul')
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
                    subprocess.Popen(['cmd', '/c', 'start', target])
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
                subprocess.Popen(['cmd', '/c', 'start', 'http://www.baidu.com'])
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
                os.system(f'start {site_map[target]}')
                return f'已用浏览器打开 {app}'
            # 桌面应用：尝试 start（查找 PATH / 关联）
            result = os.system(f'start "" {target} 2>nul')
            if result == 0:
                return f'已尝试打开 {app}'
            # 失败则用浏览器兜底
            os.system(f'start https://www.bing.com/search?q={app}')
            return f'已尝试打开 {app}，若失败已用浏览器搜索'

        # 3. 检查是否含网址关键词 → 浏览器打开
        url_keywords = ['http', 'www.', '.com', '.cn', '.net', '.org', 'bilibili', '知乎', '百度']
        if any(k in app.lower() for k in url_keywords) or app in ('bilibili', '哔哩哔哩', 'b站'):
            url = app
            if not app.startswith('http'):
                url = f'https://www.{app}.com' if '.' not in app else f'https://{app}'
            os.system(f'start {url}')
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
            result = os.system(f'start "" "{app}" 2>nul')
            if result == 0:
                return f'已尝试打开 {app}'
        except Exception:
            pass

        return f'找不到 {app}，请确认名称'

    # ============ 长期记忆系统（v6.11） ============
    def _load_memory(self):
        """加载 memory.json（事实 + 摘要）"""
        try:
            import json as _j
            if os.path.exists(MEMORY_PATH):
                data = _j.load(open(MEMORY_PATH, encoding='utf-8'))
                self.memory_facts = data.get('facts', []) or []
                self.memory_summaries = data.get('summaries', []) or []
        except Exception:
            self.memory_facts = []
            self.memory_summaries = []

    def _save_memory(self):
        """保存 memory.json"""
        try:
            import json as _j
            with open(MEMORY_PATH, 'w', encoding='utf-8') as f:
                _j.dump({'facts': self.memory_facts, 'summaries': self.memory_summaries,
                         'updated_at': __import__('datetime').datetime.now().isoformat()},
                        f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _remember_fact(self, action, content='', importance=3, fid='', role='both'):
        """memorize 工具处理：add/update/delete 长期事实。role: both=共享 / flash / pro"""
        import datetime
        now = datetime.datetime.now().isoformat(timespec='seconds')
        try:
            importance = max(1, min(int(importance), 5))
        except Exception:
            importance = 3
        if role not in ('flash', 'pro', 'both'):
            role = 'both'
        content = (content or '').strip()
        if action == 'add':
            if not content:
                return '内容为空，未保存'
            # 相似内容已存在则更新（软覆盖）
            for f in self.memory_facts:
                if f.get('status') == 'active' and (f.get('content') == content or content in f.get('content', '') or f.get('content', '') in content):
                    f['content'] = content
                    f['importance'] = importance
                    f['roles'] = role
                    f['updated_at'] = now
                    self._save_memory()
                    return f'已更新已有记忆 #{f["id"]}'
            fid = f'f{int(datetime.datetime.now().timestamp() * 1000)}'
            self.memory_facts.append({'id': fid, 'content': content, 'importance': importance,
                                      'created_at': now, 'updated_at': now, 'status': 'active', 'roles': role})
            # 遗忘机制：超 50 条按 重要度升序+旧 淘汰
            if len(self.memory_facts) > 50:
                self.memory_facts.sort(key=lambda x: (x.get('importance', 3), x.get('updated_at', '')))
                self.memory_facts = self.memory_facts[-50:]
            self._save_memory()
            return f'已记住（重要度 {importance}/5）'
        if action == 'delete':
            for f in self.memory_facts:
                if f.get('id') == fid or f.get('content') == content:
                    f['status'] = 'superseded'
                    f['updated_at'] = now
                    self._save_memory()
                    return f'已遗忘 #{f["id"]}'
            return '未找到对应记忆'
        if action == 'update':
            for f in self.memory_facts:
                if f.get('id') == fid:
                    f['content'] = content or f.get('content', '')
                    f['importance'] = importance
                    f['updated_at'] = now
                    f['status'] = 'active'
                    self._save_memory()
                    return f'已更新 #{fid}'
            return '未找到对应记忆 ID'
        return '未知操作（add/update/delete）'

    def _memory_block(self):
        """生成注入 system prompt 的记忆块（按当前角色过滤，预算：事实 ≤1000 字符 + 摘要 ≤900）"""
        lines = []
        budget = 1000
        # 角色过滤：roles=both（或无 roles 字段=共享）或 roles==当前角色
        facts = [f for f in self.memory_facts
                 if f.get('status') == 'active'
                 and (f.get('roles', 'both') == 'both' or f.get('roles') == self.current)]
        facts.sort(key=lambda x: -x.get('importance', 3))
        for f in facts:
            text = f.get('content', '').strip()
            if not text:
                continue
            if budget - len(text) < 0:
                break
            lines.append(f'★{f.get("importance", 3)} {text}')
            budget -= len(text)
        block = '\n'.join(lines)
        # 会话摘要（最多 3 条，每条 ≤300 字符）
        sm = []
        for s in self.memory_summaries[-3:]:
            t = (s.get('content') or '').strip()[:300]
            if t:
                sm.append(t)
        if sm:
            block += ('\n【之前的对话摘要】\n' + '\n'.join(sm)) if block else '【之前的对话摘要】\n' + '\n'.join(sm)
        return block.strip()

    def _summarize_old(self):
        """旧消息滚动摘要：chat_history_msgs 超 20 条时，最旧 10 条压成摘要"""
        if len(self.chat_history_msgs) <= 20 or not self.ai_enabled:
            return
        try:
            import urllib.request, json as _j
            old = self.chat_history_msgs[:10]
            texts = []
            for m in old:
                c = (m.get('content') or '').strip()
                if c and not c.startswith('（'):
                    texts.append(f'{"用户" if m.get("role") == "user" else "桌宠"}: {c[:100]}')
            if not texts:
                self.chat_history_msgs = self.chat_history_msgs[10:]
                return
            data = _j.dumps({
                'model': cur_model,
                'messages': [{'role': 'user', 'content': f'把下面的对话压缩成 1-2 句中文摘要（≤120字），只留关键信息：\n' + '\n'.join(texts[-8:])}],
                'max_tokens': 200,
            }).encode()
            req = urllib.request.Request('https://api.deepseek.com/chat/completions', data=data,
                headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {self.ai_key}'})
            with urllib.request.urlopen(req, timeout=25) as resp:
                r = _j.loads(resp.read().decode())
            summary = (r['choices'][0]['message'].get('content') or '').strip()
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
            import json as _j
            with open(TODO_PATH, 'w', encoding='utf-8') as f:
                _j.dump(self.todos, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _todo_block(self):
        """生成注入 prompt 的待办清单块"""
        if not self.todos:
            return ''
        lines = []
        for t in self.todos:
            mark = '✅' if t.get('done') else '⬜'
            lines.append(f'{mark} {t.get("text", "")}')
        return '\n'.join(lines)

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
        """按用户消息关键词预判 AI 状态（猜测，工具确认后会覆盖）——返回 (状态文本, 语言) 交由调用方适配"""
        t = (text or '').lower()
        rules = [
            (['天气', '温度', '下雨', '降雨', '气温', '雾霾', '空气质量', '湿度'], ('正在查询天气', 'Checking weather')),
            (['时间', '几点', '日期', '星期'], ('正在获取时间', 'Getting time')),
            (['文件', '搜索', '查找', '找到', '哪个目录'], ('正在搜索文件', 'Searching files')),
            (['进程', '卡顿', '内存', 'cpu', '占用', '后台'], ('正在读取系统状态', 'Reading system status')),
            (['打开', '启动', '运行', '启动程序', '开一下'], ('正在打开程序', 'Opening app')),
            (['音量', '静音', '声音', '喇叭'], ('正在调整音量', 'Adjusting volume')),
            (['提醒', '闹钟', '待办', 'todo', '记得', '任务'], ('正在安排提醒/待办', 'Setting reminder/todo')),
            (['锁屏', '锁定'], ('正在锁定屏幕', 'Locking screen')),
            (['剪贴板', '复制', '粘贴'], ('正在读取剪贴板', 'Reading clipboard')),
            (['计算', '算一下', '等于'], ('正在计算', 'Calculating')),
            (['吃什么', '美食', '景点', '推荐', '介绍', '历史', '攻略'], ('正在组织回答', 'Preparing answer')),
        ]
        for keys, status in rules:
            if any(k in t for k in keys):
                return status
        return ('正在思考', 'Thinking')

    def _execute_tool(self, name, args):
        """执行 AI 请求的工具，返回结果文本"""
        try:
            if name == 'open_app':
                app = args.get('name', '')
                return self._smart_open(app)
            elif name == 'get_time':
                import datetime
                return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            elif name == 'calculate':
                expr = args.get('expr', '').replace(' ', '')
                if all(ch in '0123456789+-*/().%' for ch in expr):
                    return f'{expr} = {eval(expr)}'
                return '表达式含非法字符'
            elif name == 'set_reminder':
                sec = max(1, min(int(args.get('seconds', 60)), 86400))
                text = args.get('text', '提醒')
                self._add_reminder(sec, text)
                return f'已设置 {sec} 秒后提醒：{text}'
            elif name == 'lock_screen':
                ctypes.windll.user32.LockWorkStation()
                return '已锁定屏幕'
            elif name == 'query_weather':
                # 真正联网查天气（wttr.in）
                city = args.get('city', '') or self.pet_city
                try:
                    import urllib.request
                    import urllib.parse
                    url = f'https://wttr.in/{urllib.parse.quote(city)}?format=3&lang=zh'
                    req = urllib.request.Request(url, headers={'User-Agent': 'curl/8.0'})
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        result = resp.read().decode('utf-8').strip()
                    if result:
                        return f'{city} 的天气：{result}'
                    return f'没查到 {city} 的天气'
                except Exception as e:
                    return f'天气查询失败：{e}'
            elif name == 'run_powershell':
                cmd = args.get('command', '')
                blocked = _check_dangerous(cmd)
                if blocked:
                    # 危险操作改为询问用户：允许才执行
                    if self._request_confirm(f'检测到危险操作，是否允许执行？\n\n{cmd}'):
                        return _run_ps(cmd, skip_check=True)
                    return '用户拒绝了危险操作，未执行'
                return _run_ps(cmd)
            elif name == 'memorize':
                return self._remember_fact(args.get('action', 'add'), args.get('content', ''), args.get('importance', 3), args.get('id', ''), args.get('role', 'both'))
            elif name == 'manage_todo':
                return self._manage_todo(args.get('action', 'list'), args.get('text', ''), args.get('id', ''))
            elif name == 'schedule_followup':
                sec = max(600, min(int(args.get('seconds', 3600)), 21600))
                reason = (args.get('reason', '关心一下') or '').strip()
                self._add_reminder(sec, reason, rtype='followup')
                return f'已安排 {sec} 秒后回访：{reason}'
            elif name == 'read_clipboard':
                txt = _read_clipboard_text()
                if txt is None:
                    return '剪贴板没有文本内容'
                return f'剪贴板内容（{len(txt)} 字符）：\n{txt[:1000]}' + ('…（过长已截断）' if len(txt) > 1000 else '')
            elif name == 'write_clipboard':
                txt = args.get('text', '')
                if not txt:
                    return '没有可写入的内容'
                return '已写入剪贴板，用户可直接粘贴' if _write_clipboard_text(txt) else '剪贴板写入失败'
            elif name == 'get_system_info':
                return _run_ps('$os = Get-CimInstance Win32_OperatingSystem; $cpu = Get-CimInstance Win32_Processor; $cs = Get-CimInstance Win32_ComputerSystem; "系统: $($os.Caption) $($os.Version)"; "CPU: $($cpu.Name)"; "内存: $([math]::Round(($os.TotalVisibleMemorySize/1MB),1)) GB 总量, $([math]::Round(($os.FreePhysicalMemory/1MB),1)) GB 可用"; "开机: $($os.LastBootUpTime)"; "用户: $($cs.UserName)"')
            elif name == 'list_processes':
                n = int(args.get('n', 10))
                return _run_ps(f'Get-Process | Sort-Object WS -Descending | Select-Object -First {n} Name, Id, @{{N="内存MB";E={{[math]::Round($_.WS/1MB)}}}} | Format-Table -AutoSize | Out-String -Width 100')
            elif name == 'kill_process':
                proc = args.get('name', '').replace('.exe', '')
                protected = {'system', 'svchost', 'explorer', 'winlogon', 'csrss', 'services', 'dwm', 'pythonw', 'python', 'autoclaw'}
                if proc.lower() in protected:
                    return f'{proc} 是系统/关键进程，已保护，不能结束'
                return _run_ps(f'Get-Process -Name {proc} -ErrorAction SilentlyContinue | Stop-Process; if ($?) {{ "已结束进程 {proc}" }} else {{ "未找到进程 {proc}" }}')
            elif name == 'control_volume':
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
            elif name == 'search_files':
                fname = (args.get('name') or '').strip()
                fpath = (args.get('path') or os.path.expanduser('~')).strip()
                if not fname:
                    return '请提供文件名关键词'
                cmd = (f'[Console]::OutputEncoding=[Text.Encoding]::UTF8; '
                       f'Get-ChildItem -Path "{fpath}" -Recurse -Filter "*{fname}*" -File -ErrorAction SilentlyContinue '
                       f'| Select-Object -First 10 FullName | Out-String -Width 200')
                result = _run_ps(cmd, timeout=12)
                if '（' in result and 'Error' in result:
                    return result
                return result if result and '（无输出' not in result else f'没找到包含 "{fname}" 的文件'
            return f'未知工具 {name}'
        except Exception as e:
            return f'工具执行失败：{e}'

    def _ai_worker(self, text):
        """后台线程：调用 DeepSeek API（支持 function calling 循环）"""
        import urllib.request
        import json as jsonlib
        try:
            # 旧消息超 20 条 → 先滚动摘要（不阻塞主流程）
            self._summarize_old()
            # 意图预判：秒出状态提示（猜测，工具确认后覆盖）
            gs = self._guess_status(text)
            self.ai_status_signal.emit(gs[1] if getattr(self, 'language', 'zh') == 'en' else gs[0])
            # 上下文：最近 10 条 + 当前消息
            ctx = self.chat_history_msgs[-10:] + [{'role': 'user', 'content': text}]
            # 根据配置生成回复风格提示
            style_hint = {
                'short': '回复尽量简短（一两句话以内）。',
                'detailed': '分析类问题可以详细回答，允许用列表/表格，不必受简短限制。',
                'normal': '回答简短可爱，但分析类问题可以稍详细。',
            }.get(getattr(self, 'reply_style', 'normal'), '回答简短可爱。')
            # 长期记忆注入（预算内）
            mem = self._memory_block()
            mem_hint = f'\n\n【你的长期记忆】\n{mem}' if mem else ''
            mem_rule = '\n当你发现用户的重要偏好/个人事实/任务目标时，调用 memorize 工具记住它；用户明确说"忘了/不要记住"时用 memorize 删除对应记忆。' if mem else '\n记忆规则：当你发现用户的重要偏好/个人事实/任务目标时，调用 memorize 工具记住它。'
            # 待办清单注入
            todo_block = self._todo_block()
            todo_hint = f'\n\n【待办清单】\n{todo_block}' if todo_block else ''
            cur_model = self._current_model()
            # 语言指示：AI 回复语言跟随配置
            lang_hint = self._t('lang_hint')
            # 角色身份锚定：名字优先级 系统设定 > 记忆中的角色命名
            char_name = CHARACTERS[self.current]['name']
            role_anchor = f'你是{char_name}（角色：{self.current}，模型：{cur_model}）。回答"你是谁"时先明确你是{char_name}（{self.current}）；如果长期记忆中有用户给你起的名字（如小蓝/大蓝），按角色对应使用（只认与你当前角色匹配的名字），不要混用其他角色的名字。'
            messages = [
                {'role': 'system', 'content': f'你是{CHARACTERS[self.current]["name"]}，一只Q版桌宠，用中文。当前性格：{self.personality}。{style_hint}{lang_hint}你运行在 Windows 电脑上，可以调用工具帮用户操作电脑：打开程序/时间/计算/提醒/锁屏/天气，还能用 PowerShell 查询系统信息、进程、网络（危险操作如删除/关机/格式化需要用户确认后才会执行，不要反复尝试）。工具使用规则：只在用户明确要求时才调用对应工具，不要为了回答常识/推荐/介绍类问题而调用无关工具（如介绍美食、景点、历史等直接用你的知识回答，不要查天气、不要执行命令）。{mem_hint}{todo_hint}{mem_rule}回复开头可带情绪标签[emotion:xxx]（可选），可选：happy(开心)/thinking(思考)/sleep(困倦)/shy(害羞)/angry(生气)/sad(委屈)/excited(兴奋)/calm(平静)。例如"[emotion:happy]今天好开心！"。'},

            ] + ctx

            # 最多 5 轮工具调用；空回复自动重试（防截断/空content）
            final_reply = None
            empty_retries = 0
            for _ in range(5):
                # 请求阶段：覆盖预判为确定状态
                self.ai_status_signal.emit('正在思考…' if getattr(self, 'language', 'zh') != 'en' else 'Thinking…')
                data = jsonlib.dumps({
                    'model': cur_model,
                    'messages': messages,
                    'tools': AI_TOOLS,
                    'max_tokens': getattr(self, 'max_tokens', 1000),
                }).encode()
                req = urllib.request.Request(
                    'https://api.deepseek.com/chat/completions',
                    data=data,
                    headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {self.ai_key}'},
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    result = jsonlib.loads(resp.read().decode())
                msg = result['choices'][0]['message']
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
                        req2 = urllib.request.Request(
                            'https://api.deepseek.com/chat/completions',
                            data=data2,
                            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {self.ai_key}'},
                        )
                        with urllib.request.urlopen(req2, timeout=30) as resp2:
                            result2 = jsonlib.loads(resp2.read().decode())
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
                    status_map = {
                        'open_app': ('正在打开应用', 'Opening app'), 'query_weather': ('正在查询天气', 'Checking weather'),
                        'run_powershell': ('正在执行命令', 'Running command'), 'get_system_info': ('正在读取系统信息', 'Reading system info'),
                        'list_processes': ('正在读取进程列表', 'Listing processes'), 'kill_process': ('正在结束进程', 'Ending process'),
                        'search_files': ('正在搜索文件', 'Searching files'), 'calculate': ('正在计算', 'Calculating'),
                        'get_time': ('正在获取时间', 'Getting time'), 'memorize': ('正在记住', 'Remembering'),
                        'set_reminder': ('正在设置提醒', 'Setting reminder'), 'lock_screen': ('正在锁定屏幕', 'Locking screen'),
                        'control_volume': ('正在调整音量', 'Adjusting volume'),
                    }
                    st = status_map.get(name, (f'正在执行 {name}', f'Running {name}'))
                    self.ai_status_signal.emit((st[1] if is_en else st[0]) + '…')
                    result_text = self._execute_tool(name, args)
                    messages.append({
                        'role': 'tool',
                        'tool_call_id': tc['id'],
                        'content': result_text,
                    })

            if final_reply is None:
                # 工具轮次耗尽但没生成文本回复：强制不带工具重试一次
                self.ai_status_signal.emit('正在整理结果…' if getattr(self, 'language', 'zh') != 'en' else 'Preparing result…')
                try:
                    data3 = jsonlib.dumps({
                        'model': cur_model,
                        'messages': messages + [{'role': 'user', 'content': '请用简短中文总结一下刚才的处理结果（不要调用工具）'}],
                        'max_tokens': 300,
                    }).encode()
                    req3 = urllib.request.Request(
                        'https://api.deepseek.com/chat/completions',
                        data=data3,
                        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {self.ai_key}'},
                    )
                    with urllib.request.urlopen(req3, timeout=30) as resp3:
                        result3 = jsonlib.loads(resp3.read().decode())
                    final_reply = (result3['choices'][0]['message'].get('content') or '').strip()
                except Exception:
                    final_reply = None
                if not final_reply:
                    final_reply = '（刚才分析到一半走神了，换个问法再试一次？）'

            # 保存到对话记忆（占位/错误回复不存，避免污染后续上下文）
            if final_reply and not final_reply.startswith('（'):
                self.chat_history_msgs.append({'role': 'user', 'content': text})
                self.chat_history_msgs.append({'role': 'assistant', 'content': final_reply})
            self.ai_reply_signal.emit(final_reply)
        except Exception as e:
            self.ai_reply_signal.emit(f'（AI 出错了：{e}）')
        finally:
            self._ai_busy = False

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
        """剥离文本中的 [emotion:xxx] / [emotion=xxx] 标签，返回 (剥离后的文本, 情绪名或None)"""
        import re as re_mod
        m = re_mod.search(r'\[emotion[:=]([a-z_]+)', text or '')
        if m:
            cleaned = re_mod.sub(r'\[emotion[:=][a-z_]+\]?\s*', '', text or '').strip()
            return (cleaned, m.group(1))
        return (text, None)

    def _apply_emotion(self, emotion):
        """应用情绪：切立绘 + emoji 气泡 + 定时恢复（10 秒，可重启不叠加）"""
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

    def _display_ai_reply(self, reply):
        """主线程槽：显示 AI 回复（解析情绪标签切换立绘）"""
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
        """把 markdown 拆成渲染块：表格/代码块整体一块，其余按行"""
        lines = str(text).split('\n')
        blocks = []
        i = 0
        n = len(lines)
        while i < n:
            line = lines[i]
            s = line.strip()
            if s.startswith('```'):
                code_lines = [line]
                i += 1
                while i < n and not lines[i].strip().startswith('```'):
                    code_lines.append(lines[i])
                    i += 1
                if i < n:
                    code_lines.append(lines[i])
                    i += 1
                blocks.append('\n'.join(code_lines))
            elif s.startswith('|'):
                tbl = [line]
                i += 1
                while i < n and lines[i].strip().startswith('|'):
                    tbl.append(lines[i])
                    i += 1
                blocks.append('\n'.join(tbl))
            else:
                blocks.append(line)
                i += 1
        return blocks

    def _chat_type_start(self, text):
        """开始流式显示：拆块预渲染，逐块插入（回复到达时先清掉残留状态行）"""
        raw_blocks = self._split_md_blocks(text)
        self.chat_type_blocks = [self._md_to_html(b) for b in raw_blocks]
        self.chat_type_index = 0
        # 回复到达：清除残留状态行（⏳/思考中），避免提示词留在面板里
        self._remove_status_line()
        # 追加前缀行
        self.chat_history.append(f'<b style="color:#7fb2ff">桌宠:</b> ')
        sb = self.chat_history.verticalScrollBar()
        sb.setValue(sb.maximum())
        if not self.chat_type_blocks:
            return
        self.chat_type_timer.start(30)

    def _chat_type_tick(self):
        """打字机 tick：插入一块 HTML"""
        from PySide6.QtGui import QTextCursor
        if self.chat_type_index >= len(self.chat_type_blocks):
            self.chat_type_timer.stop()
            return
        block = self.chat_type_blocks[self.chat_type_index]
        cur = self.chat_history.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        if self.chat_type_index > 0:
            cur.insertHtml('<br>')  # 必须用 insertHtml，insertText 会把 <br> 当字面量显示
        cur.insertHtml(block)
        self.chat_type_index += 1
        sb = self.chat_history.verticalScrollBar()
        sb.setValue(sb.maximum())
        if self.chat_type_index >= len(self.chat_type_blocks):
            self.chat_type_timer.stop()

    def _chat_type_finish(self):
        """立即完成剩余块（新消息到达时 fast-forward）"""
        from PySide6.QtGui import QTextCursor
        if not self.chat_type_timer.isActive():
            return
        self.chat_type_timer.stop()
        while self.chat_type_index < len(getattr(self, 'chat_type_blocks', [])):
            block = self.chat_type_blocks[self.chat_type_index]
            cur = self.chat_history.textCursor()
            cur.movePosition(QTextCursor.MoveOperation.End)
            if self.chat_type_index > 0:
                cur.insertHtml('<br>')  # 必须用 insertHtml，insertText 会把 <br> 当字面量显示
            cur.insertHtml(block)
            self.chat_type_index += 1
        sb = self.chat_history.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ---------- 对话记忆（按角色隔离，v6.16） ----------
    def _chat_memory_path(self):
        """每个角色独立的对话历史文件"""
        return os.path.join(BASE_DIR, f'chat_memory_{self.current}.json')

    def _load_chat_memory(self):
        """从文件加载当前角色的历史对话"""
        mem_path = self._chat_memory_path()
        try:
            if os.path.exists(mem_path):
                with open(mem_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.chat_history_msgs = data.get('messages', [])
                # 恢复显示（只显示最近 20 条）
                for m in self.chat_history_msgs[-20:]:
                    who = '我' if m['role'] == 'user' else '桌宠'
                    self._append_chat(who, m['content'])
        except Exception:
            pass

    def _save_chat_memory(self):
        """保存当前角色的对话历史到文件"""
        mem_path = self._chat_memory_path()
        try:
            # 只保留最近 50 条
            msgs = self.chat_history_msgs[-50:]
            with open(mem_path, 'w', encoding='utf-8') as f:
                json.dump({'messages': msgs}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _clear_chat_memory(self):
        self.chat_history_msgs = []
        self._save_chat_memory()
        self.chat_history.clear()

    def _export_chat(self):
        """导出聊天记录到 txt（含时间戳）"""
        try:
            import datetime as _dt
            fname = f'聊天记录_{_dt.datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'
            path = os.path.join(BASE_DIR, fname)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(f'DeepSeek 桌宠聊天记录（导出时间 {_dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}）\n')
                f.write('=' * 40 + '\n')
                for m in self.chat_history_msgs:
                    who = '我' if m.get('role') == 'user' else '桌宠'
                    c = (m.get('content') or '').strip()
                    if c and not c.startswith('（'):
                        import re as _rex
                        c = _rex.sub(r'\[emotion:[a-z_]+\]?\s*', '', c)
                        f.write(f'{who}: {c}\n')
                if len(self.chat_history_msgs) == 0:
                    f.write('（暂无聊天记录）\n')
            self._append_chat('桌宠', f'📤 已导出：{path}')
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
            self.chat_history.clear()
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
    def _check_reminders(self):
        """每秒检查提醒是否到期（普通提醒=气泡；回访=触发 AI 主动关心）"""
        now = time.time()
        due = [r for r in self.reminders if now >= r['time']]
        if due:
            self.reminders = [r for r in self.reminders if now < r['time']]
            for r in due:
                if r.get('type') == 'followup':
                    self._ai_followup(r['text'])
                else:
                    self.say_plain(f'⏰ 提醒：{r["text"]}')
                    self._append_chat('桌宠', f'⏰ 提醒：{r["text"]}')
                    self._play_sound('remind')

    def _add_reminder(self, seconds, text, rtype='normal'):
        self.reminders.append({'time': time.time() + seconds, 'text': text, 'type': rtype})
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
            refresh()

        def clear_all():
            if self.reminders:
                self.reminders.clear()
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
        """系统空闲秒数（GetLastInputInfo，零依赖）"""
        try:
            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [('cbSize', ctypes.c_uint), ('dwTime', ctypes.c_uint)]
            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
            if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
                return (ctypes.windll.kernel32.GetTickCount() - lii.dwTime) / 1000.0
        except Exception:
            pass
        return 0

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
        """恢复显示状态：睡眠→睡眠立绘，否则→待机（贴边拖出/弹出后用）"""
        if self.sleeping:
            self._show_state_image('sleep')
        else:
            self._show_idle()

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
        """显示状态立绘（sleep/happy/thinking/scared/...；Live2D 模式由模型代替）"""
        if getattr(self, 'display_mode', 'static') == 'live2d':
            return
        img = self._get_state_img(st)
        if img is None:
            self._show_idle()
            return
        self._render_frame(img)

    # ---------- 气泡（预设短台词 ≤20 字，不挡脸） ----------
    def _place_bubble(self):
        """气泡悬浮在窗口顶部（pet_label 上方区域）"""
        self.bubble.raise_()  # 置顶：防止被 pet_label（后创建，z-order 更高）遮挡
        bw = min(max(self.bubble.sizeHint().width(), 40), 380)
        bh = self.bubble.sizeHint().height()
        bx = max(0, (self.width() - bw) // 2)
        by = 6
        self.bubble.setGeometry(bx, by, bw, bh)

    def say_plain(self, text, immediate=False):
        """气泡显示短文本。immediate=True 时直接完整显示（状态提示用，避免打字机卡顿误导）"""
        if not text:
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
        """随机说一句问候（气泡 + 聊天记录）"""
        if self.sleeping:
            return
        lines = self._char_lines('greetings')
        text = random.choice(lines) if lines else 'Hello!'
        self.say_plain(text)
        self._append_chat('桌宠', text)

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
        """情绪立绘结束后恢复待机"""
        if not self.sleeping:
            self.state = 'idle'
            self._show_idle()

    # ---------- 场景动作 ----------
    def play_scene(self, key):
        """播放场景动作立绘（6 秒后恢复待机）"""
        if self.sleeping:
            return
        img = self._get_scene_img(key)
        if img is None or img.isNull():
            self.say_plain('这个动作还没准备好~')
            return
        self.state = 'scene'  # 关键：锁定状态，防止 blink/光标跟随在播放期间切回待机
        self.phase = 0
        self._render_frame(img)
        desc = SCENE_ACTIONS[key][1]
        self.say_plain(desc[:10])
        QTimer.singleShot(6000, self._end_scene)

    def _end_scene(self):
        """场景动作结束：恢复待机"""
        if not self.sleeping:
            self.state = 'idle'
            self._show_idle()

    # ---------- 眨眼 ----------
    def _do_blink(self):
        # 睡眠/拖拽/非待机/贴边时不眨眼
        if (self.sleeping or self.dragging or self._blinking or self.state != 'idle'
                or self._edge_side is not None):
            self.blink_timer.start(random.randint(8000, 15000))
            return
        if self.blink_aligned is None:
            self.blink_timer.start(random.randint(8000, 15000))
            return
        self._blinking = True
        # 缩放渲染（blink 是 2048 原图，必须缩放到 pet_label 尺寸，否则只显示左上角局部）
        self._render_frame(self.blink_aligned)
        QTimer.singleShot(1500, self._blend_end)
        self.blink_timer.start(random.randint(8000, 15000))

    def _blend_end(self):
        self._blinking = False
        if self._edge_side is not None and not self._edge_popped:
            self._show_peek()
        elif not self.sleeping and self.state == 'idle':
            self._show_idle()

    # ---------- 聊天窗口 ----------
    def _append_chat(self, who, text):
        """追加一条聊天记录（自动滚动到底部，带时间戳）"""
        import datetime as _dt
        ts = _dt.datetime.now().strftime('%H:%M')
        safe = str(text).replace('<', '&lt;').replace('>', '&gt;')
        self.chat_history.append(f'<span style="color:#667;font-size:10px">{ts}</span> <b style="color:#7fb2ff">{who}:</b> {safe}')
        sb = self.chat_history.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _append_chat_md(self, who, text):
        """追加一条聊天记录（AI 回复用，支持轻量 Markdown 渲染，带时间戳）"""
        import datetime as _dt
        ts = _dt.datetime.now().strftime('%H:%M')
        self.chat_history.append(f'<span style="color:#667;font-size:10px">{ts}</span> <b style="color:#7fb2ff">{who}:</b> {self._md_to_html(text)}')
        sb = self.chat_history.verticalScrollBar()
        sb.setValue(sb.maximum())

    @staticmethod
    def _md_to_html(text):
        """轻量 Markdown → HTML（代码块/表格/标题/粗体/斜体/列表/换行）"""
        import re
        t = str(text)
        t = t.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        t = re.sub(r'```(?:\w*)\n(.*?)```', lambda m: f'<pre style="background:#1e2430;color:#d8e0f0;padding:6px;border-radius:4px">{m.group(1)}</pre>', t, flags=re.S)
        t = re.sub(r'`([^`]+)`', r'<code style="background:#2a3142;padding:1px 4px;border-radius:3px">\1</code>', t)
        t = re.sub(r'^###\s+(.+)$', r'<b style="font-size:14px">\1</b>', t, flags=re.M)
        t = re.sub(r'^##\s+(.+)$', r'<b style="font-size:15px">\1</b>', t, flags=re.M)
        t = re.sub(r'^#\s+(.+)$', r'<b style="font-size:16px">\1</b>', t, flags=re.M)
        t = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', t)
        t = re.sub(r'\*([^*]+)\*', r'<i>\1</i>', t)
        t = re.sub(r'^[-*]\s+', '• ', t, flags=re.M)
        t = re.sub(r'^\d+\.\s+', lambda m: '&nbsp;&nbsp;' + m.group(0), t, flags=re.M)
        # 表格（必须放在换行转换之前，靠 \n 分行）
        t = re.sub(r'((?:^\|.*\|\s*(?:\n|$))+)', PetWidget._md_table, t, flags=re.M)
        t = t.replace('\n', '<br>')
        return t

    @staticmethod
    def _md_table(m):
        """Markdown 表格块 → HTML table（第二行 --- 为分隔符时视为表头）"""
        import re
        lines = [l.strip() for l in m.group(1).strip().splitlines() if l.strip().startswith('|')]
        if not lines:
            return m.group(1)
        rows = [[c.strip() for c in l.strip().strip('|').split('|')] for l in lines]
        has_sep = len(rows) >= 2 and all(c and set(c) <= set('-: ') for c in rows[1])
        header = rows[0] if has_sep else []
        body = rows[2:] if has_sep else rows  # 无表头时所有行都是数据
        html = '<table style="border-collapse:collapse;margin:4px 0;font-size:12px;max-width:100%">'
        if header:
            html += '<tr>' + ''.join(f'<th style="border:1px solid #3a4152;padding:3px 8px;background:#2a3142">{c}</th>' for c in header) + '</tr>'
        for r in body:
            html += '<tr>' + ''.join(f'<td style="border:1px solid #3a4152;padding:3px 8px">{c}</td>' for c in r) + '</tr>'
        if not body and not header:
            return m.group(1)
        return html + '</table>'

    def _remove_status_line(self):
        """删除聊天面板最后一行（仅当它是状态行 ⏳/思考中），连同空块一起清掉，不留空行"""
        from PySide6.QtGui import QTextCursor
        doc = self.chat_history.document()
        last = doc.lastBlock().text().strip()
        if last.startswith('⏳') or '思考中' in last:
            cur = QTextCursor(doc)
            cur.beginEditBlock()
            # 选中最后块全部内容
            cur.movePosition(QTextCursor.MoveOperation.End)
            cur.movePosition(QTextCursor.MoveOperation.StartOfBlock, QTextCursor.MoveMode.KeepAnchor)
            cur.removeSelectedText()
            # 现在块已空，光标在块首；前移选中它前面的段落符并删除
            # → 空块与上一块合并，空块消失（不留空行）
            cur.movePosition(QTextCursor.MoveOperation.PreviousCharacter, QTextCursor.MoveMode.KeepAnchor)
            if cur.selectedText():
                cur.removeSelectedText()
            cur.endEditBlock()
            return True
        return False

    def _update_ai_status(self, text):
        """更新 AI 处理状态（删旧状态行 + 追加新状态行，不残留）"""
        self._remove_status_line()
        self.chat_history.append(f'<span style="color:#8aa">⏳ {text}</span>')
        sb = self.chat_history.verticalScrollBar()
        sb.setValue(sb.maximum())

    def toggle_chat_panel(self):
        """显示/隐藏聊天面板"""
        if self.chat_panel.isVisible():
            self.chat_panel.hide()
            self.setFixedSize(440, 340)
        else:
            self.chat_panel.show()
            self.setFixedSize(440, 560)
            # 修复：拖拽遗留的大尺寸可能让面板超出窗口/屏幕（输入框被吞、边缘拖不到）
            # 显示时检查窗口是否超出屏幕工作区，超出则重置面板尺寸并移回屏幕内
            try:
                scr = self.screen() or QApplication.primaryScreen()
                avail = scr.availableGeometry()
                if (self.y() + self.height() > avail.bottom() or self.x() + self.width() > avail.right()
                        or self.y() < avail.top() or self.x() < avail.left()):
                    self.chat_panel.setFixedWidth(420)
                    self.chat_panel.setFixedHeight(240)
                    self.setFixedSize(440, 560)
                    nx = max(avail.left(), min(self.x(), avail.right() - 440))
                    ny = max(avail.top(), min(self.y(), avail.bottom() - 560))
                    self.move(nx, ny)
            except Exception:
                pass

    def _chat_drag_press(self, event):
        """顶部把手按下：垂直拖拽（上拉扩大）"""
        self._chat_drag_mode = 'v'
        self._chat_drag_from_bottom = False
        self._chat_drag_start_y = event.globalPosition().y()
        self._chat_drag_start_h = self.chat_panel.height()
        event.accept()

    def _chat_drag_press_bottom(self, event):
        """底部把手按下：垂直拖拽（下拉扩大，标准行为）"""
        self._chat_drag_mode = 'v'
        self._chat_drag_from_bottom = True
        self._chat_drag_start_y = event.globalPosition().y()
        self._chat_drag_start_h = self.chat_panel.height()
        event.accept()

    def _chat_drag_move(self, event):
        """垂直把手拖动：窗口高度同步跟随，输入框不会被吞"""
        if self._chat_drag_mode == 'v':
            dy = event.globalPosition().y() - self._chat_drag_start_y
            old_h = self.chat_panel.height()
            # 屏幕工作区上限（防止拖大后面板超出屏幕底部）
            try:
                scr = self.screen() or QApplication.primaryScreen()
                avail = scr.availableGeometry()
                max_win_h = max(240, avail.height() - 24)
                max_panel_h = max(120, max_win_h - (self.height() - old_h))
            except Exception:
                max_panel_h = 900
            if self._chat_drag_from_bottom:
                # 底部把手：下拉（dy>0）→ 扩大（标准）
                new_h = int(max(120, min(self._chat_drag_start_h + dy, 900, max_panel_h)))
            else:
                # 顶部把手：上拉（dy<0）→ 扩大
                new_h = int(max(120, min(self._chat_drag_start_h - dy, 900, max_panel_h)))
            delta = new_h - old_h
            if delta:
                self.chat_panel.setFixedHeight(new_h)
                self.setFixedSize(self.width(), self.height() + delta)
        event.accept()

    def _chat_drag_release(self, event):
        self._chat_drag_mode = None
        event.accept()

    def _chat_panel_press(self, event):
        """聊天面板按下：检测左右边缘 → 水平对称拖拽"""
        x = event.position().x()
        w = self.chat_panel.width()
        if x < 8 or x > w - 8:
            self._chat_drag_mode = 'h'
            self._chat_drag_start_x = event.globalPosition().x()
            self._chat_drag_start_w = w
        else:
            self._chat_drag_mode = None
        event.accept()

    def _chat_panel_move(self, event):
        """面板鼠标移动：拖拽中改宽（对称），悬停边缘显示光标"""
        if self._chat_drag_mode == 'h':
            dx = event.globalPosition().x() - self._chat_drag_start_x
            old_w = self.chat_panel.width()
            # 屏幕工作区上限（防止拖大后面板超出屏幕右缘）
            try:
                scr = self.screen() or QApplication.primaryScreen()
                avail = scr.availableGeometry()
                max_win_w = max(300, avail.width() - 24)
                max_panel_w = max(300, max_win_w - (self.width() - old_w))
            except Exception:
                max_panel_w = 700
            # 1:1：鼠标移动多少总宽变多少（面板居中 → 两边对称各 dx/2）
            new_w = int(max(300, min(self._chat_drag_start_w + dx, 700, max_panel_w)))
            delta = new_w - old_w
            if delta:
                self.chat_panel.setFixedWidth(new_w)
                self.setFixedSize(self.width() + delta, self.height())
        else:
            # 悬停光标提示（左右边缘可拖拽）
            x = event.position().x()
            w = self.chat_panel.width()
            self.chat_panel.setCursor(Qt.SizeHorCursor if (x < 8 or x > w - 8) else Qt.ArrowCursor)
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
        """检测剪贴板图片：保存临时文件 → 线程 OCR；无图返回 False 放行文本粘贴"""
        try:
            img = QApplication.clipboard().image()
            if img.isNull():
                return False
        except Exception:
            return False
        is_en = getattr(self, 'language', 'zh') == 'en'
        path = os.path.join(BASE_DIR, '_pasted_ocr.png')
        try:
            img.save(path, 'PNG')
        except Exception:
            return False
        self._append_chat('桌宠', '🔍 正在识别截图…' if not is_en else '🔍 Recognizing screenshot…')
        import threading
        def worker():
            try:
                self.ocr_signal.emit(self._ocr_image(path))
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True).start()
        return True

    def _ocr_image(self, path):
        """Windows 自带 OCR（PowerShell WinRT，零依赖），返回识别文本"""
        try:
            r = _subprocess.run(
                ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', OCR_PS1, path],
                capture_output=True, timeout=60)
            if r.returncode != 0:
                return ''
            return r.stdout.decode('utf-8', errors='ignore').strip()
        except Exception:
            return ''

    def _on_ocr_result(self, text):
        """OCR 完成：识别内容显示为消息并发送给 AI"""
        p = os.path.join(BASE_DIR, '_pasted_ocr.png')
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
        self._append_chat('我', f'📷 [截图识别] {text}')
        self.ask_ai((f'（用户粘贴了一张截图，OCR 识别内容如下，请根据内容回答或处理）\n{text}'
                    if not is_en else f'(User pasted a screenshot. OCR result below; answer or act on it.)\n{text}'))

    def _on_chat_input(self):
        """处理聊天输入：本地指令 / AI 对话（用户消息里的 [emotion:xxx]/[emotion=xxx] 也会触发立绘）"""
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
            expr = low[6:].replace(' ', '')
            try:
                if all(ch in '0123456789+-*/().%' for ch in expr):
                    self._append_chat('桌宠', f'{expr} = {eval(expr)}')
                else:
                    self._append_chat('桌宠', '表达式含非法字符')
            except Exception as e:
                self._append_chat('桌宠', f'计算失败：{e}')
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
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
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
        """弹窗自定义 token 上限"""
        from PySide6.QtWidgets import QInputDialog
        is_en = getattr(self, 'language', 'zh') == 'en'
        text, ok = QInputDialog.getText(self, self._t('dlg_tokens'),
            '输入 token 上限（256-64000，越大回复越长）：' if not is_en else 'Enter token limit (256-64000, higher = longer replies):',
            text=str(getattr(self, 'max_tokens', 1000)))
        if ok and text.strip().isdigit():
            val = max(256, min(int(text.strip()), 64000))
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

    def _set_model_dialog(self, role):
        """弹窗设置指定角色的模型 ID"""
        from PySide6.QtWidgets import QInputDialog
        is_en = getattr(self, 'language', 'zh') == 'en'
        key = 'model_flash' if role == 'flash' else 'model_pro'
        cur = getattr(self, key, 'deepseek-v4-flash' if role == 'flash' else 'deepseek-v4-pro')
        label = 'Flash' if role == 'flash' else 'Pro'
        text, ok = QInputDialog.getText(self, f'{label} {self._t("dlg_model")}',
            (f'输入 {label} 角色使用的模型 ID（如 deepseek-v4-{role}）：' if not is_en else f'Enter model ID for {label} (e.g. deepseek-v4-{role}):'), text=cur)
        if ok and text.strip():
            if self._save_cfg_value(key, text.strip()):
                self.ai_model = self._current_model()
                self._append_chat('桌宠', f'{label} 角色模型：{text.strip()}（当前角色生效）' if not is_en else f'{label} model: {text.strip()} (active for current character)')

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
        self.chat_history.clear()
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
        """解除贴边，恢复正常待机（拖出/右键时用）"""
        self._edge_side = None
        self._edge_popped = False
        if self._chat_hidden_for_dock:
            self.chat_panel.show()
            self._chat_hidden_for_dock = False
        self.setFixedSize(440, 560)
        self.pet_label.setFixedSize(self.pet_size, self.pet_size)
        self._restore_display_state()

    def _popup_from_dock(self):
        """从贴边弹出完整窗口（双击/右键用）"""
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geo = screen.geometry()
        side = self._edge_side
        # 恢复完整窗口大小
        if self._chat_hidden_for_dock and not self.chat_panel.isVisible():
            self.chat_panel.show()
            self._chat_hidden_for_dock = False
        self.setFixedSize(440, 560)
        if side in ('left', 'right'):
            pop_x = 0 if side == 'left' else geo.right() - 440
            self.move(pop_x, self._popup_y)
        else:
            pop_y = 0 if side == 'top' else geo.bottom() - 560
            self.move(self._popup_x, pop_y)
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
        """恢复完整窗口大小"""
        self.setFixedSize(440, 560)

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
        self.sleeping = not self.sleeping
        if self.sleeping:
            self.type_timer.stop()
            self.bubble.hide()
            self._show_state_image('sleep')
            self.say_plain('我先睡一会儿，有事叫我…')
        else:
            self._render_frame()
            self.say_plain('醒啦！')

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
            self._show_state_image('scared')
            lines = self._char_lines('scared_lines')
            self.say_plain(random.choice(lines) if lines else 'Ah!')
            QTimer.singleShot(2500, self._render_frame)
        else:
            self.state = 'happy'
            self.phase = 0
            self._show_state_image('happy')
            lines = self._char_lines('happy_lines')
            self.say_plain(random.choice(lines) if lines else 'Yay!')
            QTimer.singleShot(2500, lambda: self._end_state('happy'))

    def _end_state(self, st):
        if not self.sleeping and self.state == st:
            self.state = 'idle'
            self._show_idle()

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
        flash_act = tray_menu.addAction('⚡ Flash')
        pro_act = tray_menu.addAction('🐋 Pro')
        tray_menu.addSeparator()
        quit_act = tray_menu.addAction('✕ 退出' if getattr(self, 'language', 'zh') != 'en' else '✕ Exit')
        show_act.triggered.connect(self.show_pet)
        flash_act.triggered.connect(lambda: self.switch_char('flash'))
        pro_act.triggered.connect(lambda: self.switch_char('pro'))
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
        """启动文件夹中的自启文件路径（文件系统方案，比注册表可靠）"""
        appdata = os.environ.get('APPDATA', os.path.expanduser(r'~\AppData\Roaming'))
        return os.path.join(appdata, r'Microsoft\Windows\Start Menu\Programs\Startup', 'DeepSeekPet.bat')

    def is_autostart_enabled(self):
        """检查启动文件夹中是否有自启文件"""
        return os.path.exists(self._autostart_startup_path())

    def toggle_autostart(self):
        """开关开机自启（启动文件夹方案）"""
        try:
            path = self._autostart_startup_path()
            if os.path.exists(path):
                os.remove(path)
                self._append_chat('桌宠', '❌ 开机自启已关闭（下次开机需手动启动桌宠）')
                self.say_plain('已关闭开机自启', immediate=True)
            else:
                cmd = self._autostart_command()
                content = f'@echo off\r\nstart "" {cmd}\r\n'
                # GBK 编码：cmd 默认代码页 936，含中文的路径必须 GBK 才能正确解析
                with open(path, 'w', encoding='gbk', newline='') as f:
                    f.write(content)
                if os.path.exists(path):
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
                    self._append_chat('桌宠', '✅ 开机自启已开启（启动文件夹）')
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
        """用户空闲分钟数（GetLastInputInfo，纯 ctypes）"""
        try:
            import ctypes
            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [('cbSize', ctypes.c_uint), ('dwTime', ctypes.c_uint)]
            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
            ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
            millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
            return millis / 60000.0
        except Exception:
            return 0.0

    def _ai_wakeup_judge(self):
        """链式唤醒判断：轻量请求 AI 决定 是否主动找用户 + 下次唤醒间隔（独立上下文，不污染主对话）"""
        try:
            import urllib.request, json as _j, datetime as _dt, re as _re
            now = _dt.datetime.now()
            last_chat = ''
            if self.chat_history_msgs:
                last_chat = (self.chat_history_msgs[-1].get('content') or '')[:80]
            idle = self._user_idle_minutes()
            week = '一二三四五六日'[now.weekday()]
            state = f'现在是{now.strftime("%H:%M")}（周{week}），电脑空闲 {idle:.0f} 分钟'
            if last_chat:
                state += f'，最近对话：{last_chat}'
            prompt = (f'{state}。你是桌宠{CHARACTERS[self.current]["name"]}。请判断现在要不要主动找用户说句话。'
                      f'规则：用户空闲超过30分钟、或深夜(23:00-8:00)、或用户明显在忙时不打扰；'
                      f'如果最近有值得关心的事（未完成的话题/重要事件）可以主动。'
                      f'只返回 JSON：{{"act":"yes"或"no","message":"要说话时的1-2句自然关心语(act=yes时)","next_minutes":下次唤醒间隔分钟数(10-360)}}')
            data = _j.dumps({'model': self._current_model(),
                             'messages': [{'role': 'user', 'content': prompt}], 'max_tokens': 200}).encode()
            req = urllib.request.Request('https://api.deepseek.com/chat/completions', data=data,
                headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {self.ai_key}'})
            with urllib.request.urlopen(req, timeout=25) as resp:
                r = _j.loads(resp.read().decode())
            content = (r['choices'][0]['message'].get('content') or '')
            m = _re.search(r'\{[^{}]*\}', content, _re.S)
            if m:
                return _j.loads(m.group(0))
        except Exception:
            pass
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
        """主线程槽：显示主动消息（气泡+聊天面板+立绘+写入对话历史）"""
        if not msg:
            return
        self._display_ai_reply(msg)
        self.chat_history_msgs.append({'role': 'assistant', 'content': msg})
        self._save_chat_memory()

    def _ai_followup(self, topic):
        """回访机制：对话中安排的回访到点 → 主动生成关心消息（带状态感知 v6.18）"""
        def work():
            try:
                import urllib.request, json as _j, datetime as _dt
                now = _dt.datetime.now()
                idle = self._user_idle_minutes()
                last_chat = ''
                if self.chat_history_msgs:
                    last_chat = (self.chat_history_msgs[-1].get('content') or '')[:60]
                week = '一二三四五六日'[now.weekday()]
                state = f'现在是{now.strftime("%H:%M")}（周{week}），用户已空闲 {idle:.0f} 分钟'
                if last_chat:
                    state += f'，最近对话：{last_chat}'
                prompt = (f'{state}。用户之前提到：{topic}。作为{CHARACTERS[self.current]["name"]}，'
                          f'现在按约定主动关心一下，1-2句话，自然不刻意。'
                          f'根据状态调整语气：用户空闲超过60分钟→体谅/不催促（可能不在或很忙）；'
                          f'空闲不到10分钟→语气可以亲近自然。可带[emotion:xxx]。')
                data = _j.dumps({'model': self._current_model(),
                                 'messages': [{'role': 'user', 'content': prompt}], 'max_tokens': 150}).encode()
                req = urllib.request.Request('https://api.deepseek.com/chat/completions', data=data,
                    headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {self.ai_key}'})
                with urllib.request.urlopen(req, timeout=25) as resp:
                    r = _j.loads(resp.read().decode())
                msg = (r['choices'][0]['message'].get('content') or '').strip()
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

    def contextMenuEvent(self, event):
        # 扒边贴边状态：右键 = 弹出（锁定其他功能）
        if self._edge_side is not None and self._edge_mode == 'peek' and not self._edge_popped:
            self._popup_from_dock()
            return
        T = self._t
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { font-size: 13px; }")
        acts = {}

        # 1. 角色切换（子菜单）
        cmenu = menu.addMenu(T('menu_role'))
        act_flash = cmenu.addAction('⚡ V4 Flash')
        act_flash.triggered.connect(lambda: self.switch_char('flash'))
        act_pro = cmenu.addAction('🐋 V4 Pro')
        act_pro.triggered.connect(lambda: self.switch_char('pro'))

        # 2. 常用：和 AI 聊天（顶级）
        acts['chat'] = menu.addAction(T('menu_chat'))

        # 3. 互动（子菜单）
        imenu = menu.addMenu(T('menu_interact'))
        imenu.addAction(T('say')).triggered.connect(lambda: self.say_random())
        imenu.addAction(T('think')).triggered.connect(lambda: self.do_thinking())
        imenu.addAction(T('random')).triggered.connect(lambda: self.random_action())
        imenu.addAction(T('sleep')).triggered.connect(lambda: self.toggle_sleep())
        imenu.addSeparator()
        imenu.addAction(T('toggle_chat')).triggered.connect(lambda: self.toggle_chat_panel())
        imenu.addSeparator()
        imenu.addAction(T('l2d_preview')).triggered.connect(self._open_live2d_preview)
        imenu.addAction(T('archive')).triggered.connect(lambda: self._archive_and_clear())
        act_active = imenu.addAction(T('active_care') + (T('on') if self.active_chat_enabled else T('off')))
        act_active.triggered.connect(lambda: self.toggle_active_chat())

        # 4. 贴边模式（顶级开关）
        acts['edgemode'] = menu.addAction(T('edge_mode') + (T('edge_hidden') if self._edge_mode == 'peek' else T('edge_peek')))

        # 5. 动作（子菜单）
        amenu = menu.addMenu(T('menu_actions'))
        for sk, (label, _desc) in SCENE_ACTIONS.items():
            amenu.addAction(label).triggered.connect(lambda checked, k=sk: self.play_scene(k))

        # 6. 性格切换（子菜单）
        pmenu = menu.addMenu(T('menu_personality'))
        for pk, pl in [('温柔', 'person_gentle'), ('傲娇', 'person_tsundere'), ('吐槽', 'person_sarcastic'), ('元气', 'person_energetic'), ('高冷', 'person_cold')]:
            pmenu.addAction(T(pl)).triggered.connect(lambda checked, pp=pk: self._set_personality(pp))

        # 7. 设置（子菜单）
        smenu = menu.addMenu(T('menu_settings'))
        smenu.addAction(T('api_setting')).triggered.connect(self._set_api_key_dialog)
        mdlmenu = smenu.addMenu(T('model_menu'))
        mdlmenu.addAction('⚡ Flash 模型…').triggered.connect(lambda: self._set_model_dialog('flash'))
        mdlmenu.addAction('🐋 Pro 模型…').triggered.connect(lambda: self._set_model_dialog('pro'))
        mdlmenu.addSeparator()
        mdlmenu.addAction(f'{T("current")}：{self._current_model()}（{CHARACTERS[self.current]["name"]}）').setEnabled(False)
        smenu.addSeparator()
        rsmenu = smenu.addMenu(T('style_menu'))
        for key, val in [('style_short', 'short'), ('style_normal', 'normal'), ('style_detailed', 'detailed')]:
            ra = rsmenu.addAction(T(key))
            ra.setCheckable(True)
            ra.setChecked(getattr(self, 'reply_style', 'normal') == val)
            ra.triggered.connect(lambda checked, v=val, k=key: self._set_reply_style(v, T(k)))
        tmmenu = smenu.addMenu(T('token_menu'))
        cur_tok = getattr(self, 'max_tokens', 1000)
        for key, val in [('tok_short', 500), ('tok_normal', 1000), ('tok_long', 2000), ('tok_xlong', 4000), ('tok_max', 16000)]:
            ta = tmmenu.addAction(T(key))
            ta.setCheckable(True)
            ta.setChecked(cur_tok == val)
            ta.triggered.connect(lambda checked, v=val, k=key: self._set_max_tokens(v, T(k)))
        tmmenu.addSeparator()
        tmmenu.addAction(T('custom')).triggered.connect(self._set_max_tokens_dialog)
        smenu.addSeparator()
        # 显示模式：静态立绘 / Live2D
        modemenu = smenu.addMenu(T('mode_menu'))
        ma_static = modemenu.addAction(T('mode_static'))
        ma_static.setCheckable(True)
        ma_static.setChecked(getattr(self, 'display_mode', 'static') != 'live2d')
        ma_static.triggered.connect(lambda: self._set_display_mode('static'))
        ma_l2d = modemenu.addAction(T('mode_live2d'))
        ma_l2d.setCheckable(True)
        ma_l2d.setChecked(getattr(self, 'display_mode', 'static') == 'live2d')
        ma_l2d.triggered.connect(lambda: self._set_display_mode('live2d'))
        # Live2D 模型库：扫描 assets/live2d/，用户放入 model3.json 文件夹即可选用
        l2dmm = modemenu.addMenu(T('l2d_model_menu'))
        l2d_models = self._scan_live2d_models()
        if l2d_models:
            cur_model = getattr(self, 'live2d_model', 'mao')
            for mname in sorted(l2d_models):
                ma = l2dmm.addAction(mname)
                ma.setCheckable(True)
                ma.setChecked(mname == cur_model)
                ma.triggered.connect(lambda checked, n=mname: self._set_live2d_model(n))
        else:
            l2dmm.addAction(T('l2d_no_model')).setEnabled(False)
        smenu.addSeparator()
        smenu.addAction(T('city')).triggered.connect(self._set_city_dialog)
        smenu.addAction(T('custom_personality')).triggered.connect(self._set_personality_dialog)
        smenu.addSeparator()
        mmmenu = smenu.addMenu(T('memory_menu'))
        mmmenu.addAction(T('mem_mgr')).triggered.connect(self._open_memory_manager)
        mmmenu.addSeparator()
        mmmenu.addAction(T('view_memory')).triggered.connect(self._show_memory)
        mmmenu.addAction(T('delete_memory')).triggered.connect(self._delete_memory_dialog)
        mmmenu.addAction(T('clear_memory')).triggered.connect(self._clear_memory_confirm)
        mmmenu.addSeparator()
        mmmenu.addAction(T('mem_backup')).triggered.connect(self._export_memory_backup)
        mmmenu.addAction(T('mem_import')).triggered.connect(self._import_memory_backup)
        smenu.addAction(T('reminder_menu')).triggered.connect(self._open_reminder_manager)
        smenu.addAction(T('todo_menu')).triggered.connect(self._open_todo_manager)
        smenu.addSeparator()
        smenu.addAction(T('export_chat')).triggered.connect(self._export_chat)
        smenu.addSeparator()
        autostart_act = smenu.addAction(T('autostart') + (T('on') if self.is_autostart_enabled() else T('off')))
        autostart_act.setCheckable(True)
        autostart_act.setChecked(self.is_autostart_enabled())
        autostart_act.triggered.connect(self.toggle_autostart)
        smenu.addSeparator()
        # 语言切换
        langmenu = smenu.addMenu(T('language_menu'))
        act_zh = langmenu.addAction('中文')
        act_zh.setCheckable(True)
        act_zh.setChecked(getattr(self, 'language', 'zh') == 'zh')
        act_zh.triggered.connect(lambda: self._set_language('zh'))
        act_en = langmenu.addAction('English')
        act_en.setCheckable(True)
        act_en.setChecked(getattr(self, 'language', 'zh') == 'en')
        act_en.triggered.connect(lambda: self._set_language('en'))

        menu.addSeparator()
        acts['hide'] = menu.addAction(T('hide_tray'))
        menu.addSeparator()
        acts['exit'] = menu.addAction(T('exit'))

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
