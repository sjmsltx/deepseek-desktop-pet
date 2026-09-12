# -*- coding: utf-8 -*-
"""
chat_render.py — 聊天渲染·纯文本解析层（P2 模块化拆分）
========================================================
从 desktop_pet.py 拆出的 Markdown 解析纯函数（无 Qt widget 依赖）：
- split_rich_blocks：拆渲染块（text/code/table 三元组）——打字机逐块渲染用
- split_md_blocks：拆块（表格/代码块整体一块，其余按行）
- md_to_html：轻量 Markdown → HTML（代码块/表格/标题/粗体/斜体/列表）
- md_table：Markdown 表格块 → HTML table
- looks_like_table：粗略判断文本是否表格

模块化说明：纯字符串处理，可独立单测。
"""
import re


def split_rich_blocks(text):
    """把 markdown 拆成渲染块：(类型, 内容)。类型 text=连续段落(保留空行分段) code=代码块 table=表格块"""
    blocks = []
    lines = str(text).split('\n')
    i, n = 0, len(lines)
    buf = []

    def flush():
        if buf:
            blocks.append(('text', '\n'.join(buf)))
            buf.clear()

    while i < n:
        line = lines[i]
        s = line.strip()
        if s.startswith('```'):
            flush()
            code_lines = [line]
            i += 1
            while i < n and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            if i < n:
                code_lines.append(lines[i])
                i += 1
            body = code_lines[1:-1] if len(code_lines) >= 2 else code_lines
            blocks.append(('code', '\n'.join(body).strip('\n')))
        elif s.startswith('|'):
            flush()
            tbl = [line]
            i += 1
            while i < n and lines[i].strip().startswith('|'):
                tbl.append(lines[i])
                i += 1
            blocks.append(('table', '\n'.join(tbl)))
        else:
            buf.append(line)
            i += 1
    flush()
    return blocks


def split_md_blocks(text):
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


def md_to_html(text):
    """轻量 Markdown → HTML（代码块/表格/标题/粗体/斜体/列表/换行）
    2026-08-06 修复：代码块/行内代码/表格先占位符保护，粗体/斜体不再误伤代码内 * 与 **
    （原实现 <pre> 内容仍会被斜体正则跨行配对，复制时星号丢失；行内代码/表格同理）"""
    t = str(text)
    t = t.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    saved = []  # 保护池：(类型, 内容)；pre=代码块 code=行内代码 table=表格HTML

    def _save(kind, content):
        saved.append((kind, content))
        return f'\x00MD{len(saved)-1}\x00'

    # ① 结构内容先占位（顺序：代码块 > 行内代码 > 表格）
    t = re.sub(r'```(?:\w*)\n(.*?)```', lambda m: _save('pre', m.group(1)), t, flags=re.S)
    t = re.sub(r'`([^`]+)`', lambda m: _save('code', m.group(1)), t)
    t = re.sub(r'((?:^\|.*\|\s*(?:\n|$))+)', lambda m: _save('table', md_table(m)), t, flags=re.M)

    # ② 行内样式（粗体/斜体不跨行，避免跨行配对误伤）
    t = re.sub(r'^###\s+(.+)$', r'<b style="font-size:14px">\1</b>', t, flags=re.M)
    t = re.sub(r'^##\s+(.+)$', r'<b style="font-size:15px">\1</b>', t, flags=re.M)
    t = re.sub(r'^#\s+(.+)$', r'<b style="font-size:16px">\1</b>', t, flags=re.M)
    t = re.sub(r'\*\*([^*\n]+)\*\*', r'<b>\1</b>', t)
    t = re.sub(r'\*([^*\n]+)\*', r'<i>\1</i>', t)
    t = re.sub(r'^[-*]\s+', '• ', t, flags=re.M)
    t = re.sub(r'^\d+\.\s+', lambda m: '&nbsp;&nbsp;' + m.group(0), t, flags=re.M)
    t = t.replace('\n', '<br>')

    # ③ 还原保护内容（逆序：先外层后内层，支持表格内嵌行内代码）
    for i in range(len(saved) - 1, -1, -1):
        kind, content = saved[i]
        ph = f'\x00MD{i}\x00'
        if kind == 'pre':
            t = t.replace(ph, '<pre style="white-space:pre-wrap;background:#1e2430;color:#d8e0f0;padding:6px;border-radius:4px">' + content + '</pre>')
        elif kind == 'code':
            t = t.replace(ph, '<code style="background:#2a3142;padding:1px 4px;border-radius:3px">' + content + '</code>')
        else:
            t = t.replace(ph, content)
    return t


def _esc(t):
    """HTML 转义（表格单元格等拼进富文本前必须转义）"""
    return (str(t).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def md_table(m):
    """Markdown 表格块 → HTML table（第二行 --- 为分隔符时视为表头）"""
    lines = [l.strip() for l in m.group(1).strip().splitlines() if l.strip().startswith('|')]
    if not lines:
        return m.group(1)
    rows = [[c.strip() for c in l.strip().strip('|').split('|')] for l in lines]
    has_sep = len(rows) >= 2 and all(c and set(c) <= set('-: ') for c in rows[1])
    header = rows[0] if has_sep else []
    body = rows[2:] if has_sep else rows  # 无表头时所有行都是数据
    html = '<table style="border-collapse:collapse;margin:4px 0;font-size:12px;max-width:100%">'
    if header:
        html += '<tr>' + ''.join(f'<th style="border:1px solid #3a4152;padding:3px 8px;background:#2a3142">{_esc(c)}</th>' for c in header) + '</tr>'
    for r in body:
        html += '<tr>' + ''.join(f'<td style="border:1px solid #3a4152;padding:3px 8px">{_esc(c)}</td>' for c in r) + '</tr>'
    if not body and not header:
        return m.group(1)
    return html + '</table>'


def looks_like_table(text):
    """粗略判断：多行且含管道符的表格"""
    lines = [ln for ln in text.splitlines() if ln.strip().startswith('|')]
    return len(lines) >= 3
