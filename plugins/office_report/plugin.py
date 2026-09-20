# -*- coding: utf-8 -*-
"""官方技能包示例：办公报表（office_report）
================================================
这是 Batch 3-1 的**真实技能包样板**：证明 manifest + 权限声明 + 工具分发这条链路
对现有内置能力（office_skill）是真的可用的，而不是纸面规范。

约定（同 plugin_manager）：def <工具名>(args: dict) -> str
权限声明见同目录 plugin.json：office.com（驱动办公软件）、files.write（写到 输出/）
"""
import os
import sys

# 技能包住在 plugins/<name>/ 下，项目根是上两级
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

OUT_DIR = os.path.join(BASE, '输出')


def _out_path(name, ext='.xlsx'):
    """只接受文件名（防目录穿越），统一落到 输出/ 下"""
    raw = os.path.basename(str(name or '').strip()) or '技能包报表'
    stem = os.path.splitext(raw)[0] or '技能包报表'
    return os.path.join(OUT_DIR, stem + ext)


def excel_report(args):
    args = args or {}
    title = str(args.get('title') or '').strip() or '报表'
    headers = args.get('headers') or []
    rows = args.get('rows') or []
    footer = str(args.get('footer') or '')
    want_pdf = args.get('pdf', True)
    os.makedirs(OUT_DIR, exist_ok=True)
    path = _out_path(args.get('name') or title)

    from office_skill import make_report, export_pdf
    msg, ok = make_report(path, title, headers, rows, footer)
    if not ok or not os.path.isfile(path):
        return '生成失败：%s' % msg

    size_kb = round(os.path.getsize(path) / 1024, 1)
    lines = ['%s（%s KB）' % (msg, size_kb)]
    if want_pdf:
        out_pdf = _out_path(args.get('name') or title, '.pdf')
        pmsg, ok = export_pdf(path, out_pdf)
        lines.append(('PDF：%s' % pmsg) if ok else ('PDF 未生成：%s' % pmsg))
    lines.append('文件位置：输出\\%s' % os.path.basename(path))
    return '\n'.join(lines)
