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
from pet_theme import DEFAULT_THEME as _THEME  # v6.58 主题唯一源（兜底值也从这里取，不再写死颜色）


# ---------------- <say_bubble> 伪标签（2026-10-27） ----------------
# 模型偶尔不调用 say_bubble 工具，而是把这层标签**直接写进正文**：
#   "…正文…<say_bubble>列表推导式，一行顶一个循环～</say_bubble>"
# 实测 chat_memory_flash.json 里有 6 条回复是这样（开/闭标签各 13 处）
# ⇒ 界面上就是一串「莫名其妙的代码」漏在聊天里。
# ⚠ 必须有捕获组 (.*?)：第一版漏了组，`m.group(1)` 每次都抛 IndexError，
#   又被外层 `except: return []` 吞掉 ⇒ 恒返回空。真实 6 条样本全空才暴出来。
_SAY_BUBBLE_TAG_RE = re.compile(r'<say_bubble[^>]*>(.*?)</say_bubble\s*>', re.S | re.I)
_SAY_BUBBLE_OPEN_RE = re.compile(r'<say_bubble[^>]*>', re.I)
_SAY_BUBBLE_CLOSE_RE = re.compile(r'</say_bubble\s*>', re.I)


def extract_say_bubbles(text):
    """取出正文里被误写成文本的 <say_bubble> 内容（**不改文本**）

    供显示层把「它本来就想要的那个气泡」补上，走原有 say_bubble 的三道闸。
    ⛔ 不用宽 except 吞异常：吞掉只会让「取不到」看起来像「本来就没有」。
    """
    s = str(text or '')
    if 'say_bubble' not in s.lower():
        return []
    return [m.group(1).strip() for m in _SAY_BUBBLE_TAG_RE.finditer(s) if m.group(1).strip()]


def strip_say_bubble(text, trim=False):
    """剥掉 <say_bubble>…</say_bubble> 与孤立开/闭标签，返回清理后文本

    未闭合的开标签在这里也直接删（非流式文本已是完整一段，不存在"下一块"）。

    `trim=True`：剥完再把尾部换行清掉 —— 标签前那个空行留着就是气泡底部一块空白。
    ⛔ 流式路径**不能** trim：逐 chunk 处理会把「hello 」的尾空格吃掉，
       与下一块的「world」粘成「helloworld」。所以默认 False。
    """
    s = str(text or '')
    # ⚠ 门槛不能只认「含完整 say_bubble」：残片（`<say_bub`）天然不含完整标签名，
    #   那样会把要处理的东西全挡在门外（实测就是这样漏的）。有 '<' 就走下去，
    #   `_split_partial_say_tag` 自带严格判定，普通尖括号不会被误伤。
    if '<' not in s and 'say_bubble' not in s.lower():
        return s
    before = s
    s = _SAY_BUBBLE_TAG_RE.sub('', s)
    s = _SAY_BUBBLE_OPEN_RE.sub('', s)
    s = _SAY_BUBBLE_CLOSE_RE.sub('', s)
    # ⚠ 光删「带 > 的完整标签」不够：实测 `'正文<say_bub'` 原样漏出来（流在标签中途断掉）。
    #   这里再切一次残片尾巴 —— 本函数只服务最终文本，切掉不留后患。
    s, _frag = _split_partial_say_tag(s)
    if trim and s != before:
        s = s.rstrip('\n')
    return s


def strip_say_bubble_hold(text):
    """剥 say 标签；**开标签未闭合时把其后整段扣住**，返回 (可见文本, 待续文本)

    为什么不能简单删掉孤立开标签（第一版就是那样，实测漏）：
      流式每 3 字一块，"<say_bubble>气泡里的话～" 先到时闭合标签还没来，
      删掉开标签 ⇒ 里面的字就当成正文显示了（实测输出
      `'这是一段正文。气泡里的话～</say_bubble>'`）。
    """
    s = str(text or '')
    if 'say_bubble' not in s.lower():
        return s, ''
    s = _SAY_BUBBLE_TAG_RE.sub('', s)          # 先剥完整的成对标签
    m = _SAY_BUBBLE_OPEN_RE.search(s)          # 还剩未闭合的开标签？
    if m:
        return s[:m.start()], s[m.start():]    # 其后全部留到下一块
    s = _SAY_BUBBLE_CLOSE_RE.sub('', s)        # 孤立闭标签直接删
    return s, ''


def _split_partial_say_tag(text):
    """切出「写到一半的 <say_bubble…」尾片（流式 chunk 可能把标签拦腰截断）

    只认 say_bubble 的前缀，避免把随意结尾的 `<` 也吞掉（那样正常文本会丢字符）。
    """
    i = text.rfind('<')
    if i < 0:
        return text, ''
    tail = text[i + 1:]
    if '>' in tail or '<' in tail:
        return text, ''
    body = tail.lstrip('/').lower()
    if not body:
        return text, ''                       # 光一个 '<' 当普通字符
    # 两个方向都算「说到一半的标签」：
    #   `<say_bub`      → body 是标签名前缀（被切短）
    #   `<say_bubble x` → body 已含完整标签名但没有 '>'（带属性却没写完）
    if 'say_bubble'.startswith(body) or body.startswith('say_bubble'):
        return text[:i], text[i:]
    return text, ''


def strip_emotion_tag(text):
    """剥离文本中的 [emotion:xxx] / [emotion=xxx] 标签，返回 (剥离后的文本, 情绪名或None)

    2026-10-27：顺带剥 <say_bubble> 伪标签（见上方说明）。
    """
    m = re.search(r'\[emotion[:=]([a-z_]+)', text or '')
    cleaned_text = strip_say_bubble(text or '', trim=True)   # 最终文本：清掉尾部空行
    if m:
        cleaned = re.sub(r'\[emotion[:=][a-z_]+\]?\s*', '', cleaned_text).strip()
        return (cleaned, m.group(1))
    return (cleaned_text, None)


def strip_emotion_tags(combined):
    """过滤 emotion 控制标签（跨 chunk 安全）。返回 (清理文本, 未闭合尾缀, 提取到的情绪列表)"""
    emotions = []
    for m in re.finditer(r'\[emotion:([^\]]+)\]', combined):
        emotions.append(m.group(1).strip())
    cleaned = re.sub(r'\[emotion:[^\]]*\]', '', combined)
    # 2026-10-27：剥模型误写成正文的 <say_bubble> 伪标签（否则会显示成「代码」）
    #   未闭合的开标签要整段扣住，否则里面的字会冒充正文
    cleaned, say_hold = strip_say_bubble_hold(cleaned)
    if say_hold:
        return cleaned, say_hold, emotions
    # 再兜「写到一半的 <say_bub…」尾片（比 emotion 尾片优先：它在更后面）
    cleaned, say_tail = _split_partial_say_tag(cleaned)
    if say_tail:
        return cleaned, say_tail, emotions
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


def message_label_qss(theme, is_user=False):
    """消息文本标签的样式（创建时与切主题刷新时共用同一处规则，避免两处写法漂移）

    v6.76 fix：补上**选中配色** —— 使用者反馈“文本选不了”：
      实测控件本身是可选中的（TextSelectableByMouse=True），但样式里没写 selection-background-color
      → 拖选后高亮几乎看不见，看着就像“选不中”。这里把选中底色/前景色显式给上。
    """
    t = theme or {}
    bg = (t.get('user_bubble') if is_user else t.get('ai_bubble')) or _THEME['panel_bg']
    # 选中配色：只用主题 token，不写颜色字面量（主题护栏要求产品代码里硬编码颜色为 0）
    sel_bg = t.get('accent') or _THEME['accent']
    sel_fg = t.get('panel_bg') or _THEME['panel_bg']
    return (f'color:{t.get("bubble_text") or _THEME["bubble_text"]}; font-size:13px; background:{bg};'
            f' border-radius:8px; padding:6px 10px;'
            f' selection-background-color:{sel_bg}; selection-color:{sel_fg};')


def apply_message_label_theme(lbl, theme, is_user=False):
    """把主题配色重新套到已存在的消息标签上（v6.58 切主题时刷新历史消息用）"""
    lbl.setStyleSheet(message_label_qss(theme, is_user))
    return lbl


def bubble_text_label(html_text, theme, is_user=False):
    """消息文本标签：富文本，自动换行，可选中复制；用户/AI 不同背景色+对齐"""
    lbl = QLabel(html_text)
    lbl.setWordWrap(True)
    lbl.setTextFormat(Qt.TextFormat.RichText)
    lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    lbl.setCursor(Qt.IBeamCursor)  # 显式文本选择光标（不被面板边缘拖拽光标覆盖）
    # 2026-10-26 修：原先用户消息用 AlignRight ⇒ **正文也跟着右对齐**。
    #   多行中文会每行顶到右边、换行后更乱（Owner 实测：一整段教学文本贴进来像被排版坏了）。
    #   判定它是"对齐"而不是"原文缩进"的证据：原文 `相关知识` 那行**零缩进、仅 4 字**，
    #   左对齐只可能出现在最左边，而截图里它在最右边。
    #   注意：气泡容器本身并没有右对齐（`_new_bubble` 只把"名字+时间"那行靠右，
    #   正文标签撑满整行宽度）⇒ 原先的"靠右"其实全靠这句 AlignRight 冒充。
    #   改成正文一律左对齐后，用户/AI 仍靠「名字行位置 + 背景色 token」区分。
    lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    lbl.setStyleSheet(message_label_qss(theme, is_user))
    return lbl


def render_one_block(content_layout, kind, content, theme, is_user=False):
    """渲染单个块到内容区（文本段 / 代码卡片 / 表格卡片）。

    返回新建的控件（文本标签或卡片，供调用方登记以便切主题时刷新）。"""
    if kind == 'code':
        card = CodeCard(content)
        content_layout.addWidget(card)
        return card
    if kind == 'table':
        card = TableCard(content, md_table_from_text(content))
        content_layout.addWidget(card)
        return card
    lbl = bubble_text_label(to_html(content), theme, is_user=is_user)
    content_layout.addWidget(lbl)
    return lbl


def render_md_into(content_layout, text, theme, is_user=False):
    """把 markdown 文本分块渲染进内容区：代码/表格成卡片，连续文本合为一个段落。

    返回新建控件列表（v6.58：宿主据此登记，切主题时可刷新已有消息/卡片）。"""
    made = []
    for kind, content in split_blocks(text):
        w = render_one_block(content_layout, kind, content, theme, is_user=is_user)
        if w is not None:
            made.append(w)
    return made


def apply_say_bubble_theme(bubble, theme, mode='say'):
    """说话气泡（顶部 QLabel）跟随主题；颜色取自主题，缺键时回退原来的浅色外观。

    mode='say'  普通说话（现状不变）
    mode='care' 关心气泡（v6.60 批 3）：左侧加一条 accent 色条 + 稍大圆角，
                用于区分「它主动找我」与「系统提示」，可与普通气泡一眼分开。
    """
    t = theme or {}
    bg = t.get('say_bg') or _THEME['say_bg']
    fg = t.get('say_text') or _THEME['say_text']
    bd = t.get('say_border') or _THEME['say_border']
    if mode == 'care':
        accent = t.get('accent') or _THEME.get('accent') or bd
        bubble.setStyleSheet(
            'QLabel { background-color: %s; color: %s; border: 2px solid %s;'
            ' border-left: 4px solid %s; border-radius: 10px;'
            ' padding: 8px 12px; font-size: 13px; }' % (bg, fg, bd, accent))
        return
    bubble.setStyleSheet(
        'QLabel { background-color: %s; color: %s; border: 2px solid %s;'
        ' border-radius: 10px; padding: 8px 12px; font-size: 13px; }' % (bg, fg, bd))
