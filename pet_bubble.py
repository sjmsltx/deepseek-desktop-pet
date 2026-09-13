# -*- coding: utf-8 -*-
"""pet_bubble.py — 气泡与 Markdown 渲染装配层

2026-09-13 桌宠收尾批 3（任务 C2）从 desktop_pet.PetWidget 拆出。

本模块负责「把一段文本变成可放进气泡/消息流的控件」这一层：
- 情绪标签剥离（流式跨 chunk 安全）
- markdown 还原与分块（实际实现已在 chat_render，这里做装配与表格兜底）
- 内容块渲染：文本段 / 代码卡 / 表格卡
- 气泡文本标签（主题着色、对齐、可选中复制）
- 说话气泡（顶部 QLabel）的主题样式

**不属本模块**（有意留在宿主，因为与定时器/窗口几何/扒边状态强耦合）：
- 气泡几何摆放：_place_bubble / _show_pet_bubble / _on_cost_bubble / _hide_bubble
- 流式打字机：_chat_type_start / _chat_type_tick / _chat_type_finish / _type_next
- 气泡装配与操作按钮：_new_bubble / _attach_bubble_actions / _save_bubble_image

调用约定：主题字典由调用方传入（宿主传 self.theme），模块内不持有任何状态。
"""
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from chat_render import split_md_blocks, split_rich_blocks, md_to_html, md_table
from chat_cards import CodeCard, TableCard
from code_checker import check_python_blocks


def strip_emotion_tag(text):
    """剥离文本中的 [emotion:xxx] / [emotion=xxx] 标签，返回 (剥离后的文本, 情绪名或None)"""
    m = re.search(r'\[emotion[:=]([a-z_]+)', text or '')
    if m:
        cleaned = re.sub(r'\[emotion[:=][a-z_]+\]?\s*', '', text or '').strip()
        return (cleaned, m.group(1))
    return (text, None)


def strip_emotion_tags(combined):
    """过滤 emotion 控制标签（跨 chunk 安全）。返回 (清理文本, 未闭合尾缀, 提取到的情绪列表)"""
    emotions = []
    for m in re.finditer(r'\[emotion:([^\]]+)\]', combined):
        emotions.append(m.group(1).strip())
    cleaned = re.sub(r'\[emotion:[^\]]*\]', '', combined)
    # 缓存可能是 emotion 标签开头的尾部（标签被切碎成任意 chunk 也能兜住）
    # 模式：[ 开头 + 字母/冒号/等号/下划线/连字符 到行尾
    tail = re.search(r'\[[a-z_:=\-]*$', cleaned)
    pending = ''
    if tail:
        pending = tail.group(0)
        cleaned = cleaned[:tail.start()]
    return cleaned, pending, emotions


def md_table_from_text(text):
    """把纯文本表格块转 HTML（供 TableCard 使用）；非表格原样返回"""
    m = re.match(r'((?:^\|.*\|\s*(?:\n|$))+)', text, flags=re.M)
    return md_table(m) if m else text


def split_blocks(text):
    """把 markdown 拆成渲染块（转发 chat_render.split_rich_blocks）"""
    return split_rich_blocks(text)


def split_typewriter_blocks(text):
    """打字机按 markdown 块拆（转发 chat_render.split_md_blocks）"""
    return split_md_blocks(text)


def to_html(text):
    """轻量 Markdown → HTML（转发 chat_render.md_to_html）"""
    return md_to_html(text)


def to_table_html(m):
    """Markdown 表格块 → HTML table（转发 chat_render.md_table）"""
    return md_table(m)


def check_code_blocks(text):
    """自动检查回复中 Python 代码块语法（转发 code_checker）"""
    return check_python_blocks(text)


def bubble_text_label(html_text, theme, is_user=False):
    """消息文本标签：富文本，自动换行，可选中复制；用户/AI 不同背景色+对齐"""
    lbl = QLabel(html_text)
    lbl.setWordWrap(True)
    lbl.setTextFormat(Qt.TextFormat.RichText)
    lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    lbl.setCursor(Qt.IBeamCursor)  # 显式文本选择光标（不被面板边缘拖拽光标覆盖）
    bg = (theme or {}).get('user_bubble') if is_user else (theme or {}).get('ai_bubble')
    lbl.setAlignment((Qt.AlignRight | Qt.AlignVCenter) if is_user else (Qt.AlignLeft | Qt.AlignVCenter))
    lbl.setStyleSheet(f'color:{(theme or {}).get("bubble_text", "#eee")}; font-size:12px; background:{bg};'
                      f' border-radius:8px; padding:6px 10px;')
    return lbl


def render_one_block(content_layout, kind, content, theme, is_user=False):
    """渲染单个块到内容区（文本段 / 代码卡片 / 表格卡片）"""
    if kind == 'code':
        content_layout.addWidget(CodeCard(content))
    elif kind == 'table':
        content_layout.addWidget(TableCard(content, md_table_from_text(content)))
    else:
        content_layout.addWidget(bubble_text_label(to_html(content), theme, is_user=is_user))


def render_md_into(content_layout, text, theme, is_user=False):
    """把 markdown 文本分块渲染进内容区：代码/表格成卡片，连续文本合为一个段落"""
    for kind, content in split_blocks(text):
        render_one_block(content_layout, kind, content, theme, is_user=is_user)


def apply_say_bubble_theme(bubble, theme):
    """说话气泡（顶部 QLabel）跟随主题；颜色取自主题，缺键时回退原来的浅色外观"""
    t = theme or {}
    bubble.setStyleSheet(
        'QLabel { background-color: %s; color: %s; border: 2px solid %s;'
        ' border-radius: 10px; padding: 8px 12px; font-size: 13px; }' % (
            t.get('say_bg', 'rgba(255,255,255,0.92)'),
            t.get('say_text', '#333'),
            t.get('say_border', '#ccc')))
