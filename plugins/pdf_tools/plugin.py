# -*- coding: utf-8 -*-
"""官方技能包：PDF 工具（pdf_tools）
=========================================
纯本地处理（pypdf），**不联网、不上传** —— 文件不出本机。
输出一律落在程序目录 输出/ 下（只取文件名，防目录穿越）。
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

OUT_DIR = os.path.join(BASE, '输出')
MAX_SPLIT_PAGES = 20          # 一次最多拆这么多页，避免刷屏


def _resolve_in(path):
    """输入：允许绝对路径或相对程序目录；返回绝对路径（不存在的由调用方报错）"""
    p = str(path or '').strip().strip('"')
    if not p:
        return ''
    return p if os.path.isabs(p) else os.path.join(BASE, p)


def _out(name, default='结果', ext='.pdf'):
    raw = os.path.basename(str(name or '').strip()) or default
    stem = os.path.splitext(raw)[0] or default
    os.makedirs(OUT_DIR, exist_ok=True)
    return os.path.join(OUT_DIR, stem + ext)


def _load_paths(args):
    """解析 paths —— 要容忍 AI 给的 Windows 路径

    ★ 实战坑：把 'C:\\Users\\...\\a.pdf' 这种反斜杠路径放在 JSON 字符串里，json.loads 会因为
    \\U \\t 这类非法转义直接报错；一报错就不能把整串当成一个路径（会把后半截也吃进去）。
    所以：先试 JSON；失败就按换行/逗号切分，并剥掉 [ ] 引号。
    """
    raw = args.get('paths') or args.get('path') or ''
    data = None
    if isinstance(raw, (list, tuple)):
        data = list(raw)
    elif isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            data = parsed if isinstance(parsed, list) else [parsed]
        except Exception:
            s = raw.strip().strip('[]')
            parts = [x.strip().strip('"').strip("'") for x in
                     s.replace('，', ',').replace(';', ',').replace('\n', ',').split(',')]
            data = [x for x in parts if x]
    out = []
    for x in (data or []):
        s = str(x).strip().strip('"').strip("'")
        if s:
            out.append(_resolve_in(s))
    return out


def _parse_pages(spec, total):
    """'1-3,5' → [0,1,2,4]（1-based 输入，0-based 输出）"""
    out = []
    spec = str(spec or '').strip()
    if not spec:
        return list(range(total))
    for part in spec.replace('，', ',').split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            a, b = part.split('-', 1)
            try:
                a, b = int(a), int(b)
            except ValueError:
                continue
            out += [i - 1 for i in range(max(1, a), min(total, b) + 1)]
        else:
            try:
                n = int(part)
            except ValueError:
                continue
            if 1 <= n <= total:
                out.append(n - 1)
    seen, uniq = set(), []
    for i in out:
        if i not in seen:
            seen.add(i)
            uniq.append(i)
    return uniq[:MAX_SPLIT_PAGES]


def _looks_garbled(s):
    """判断提取出来的文字是不是乱码

    实战教训（2026-09-20）：某些 PDF（扫描件、或生成时字体没带 ToUnicode 表的）能被“提取出”
    一堆无意义字符（如 hL[ býS Demo）—— 这不是提取失败，是**数据源就没有可读文字层**。
    这种情况要如实告知使用者（改用 OCR），不能默不作声地把乱码当正文交出去。
    """
    s = (s or '').strip()
    if len(s) < 8:
        return False
    good = 0
    for ch in s:
        if ch.isalnum() or ch.isspace() or '\u3000' <= ch <= '\u9fff' or ch in '，。、；：？！“”‘’（）《》——…·【】':
            good += 1
        elif ch in '-/()[]{}.,;:?!%¥$&*+=<>@~^_|\\\'"':
            good += 1
    return (good / len(s)) < 0.80


def pdf_tool(args):
    args = args or {}
    action = str(args.get('action') or 'info').strip().lower()
    try:
        import pypdf
    except Exception as e:
        return '没装 pypdf，无法处理 PDF：%s' % e

    paths = _load_paths(args)
    if not paths:
        return '请给出 PDF 路径（path 或 paths）。'
    missing = [p for p in paths if not os.path.isfile(p)]
    if missing:
        return '找不到文件：%s' % '、'.join(os.path.basename(m) for m in missing)

    if action == 'info':
        lines = []
        for p in paths[:5]:
            try:
                r = pypdf.PdfReader(p)
                meta = r.metadata or {}
                lines.append('%s：%d 页，%.1f KB%s'
                             % (os.path.basename(p), len(r.pages), os.path.getsize(p) / 1024,
                                '，加密' if r.is_encrypted else ''))
                if meta.get('/Title'):
                    lines.append('  标题：%s' % meta['/Title'])
            except Exception as e:
                lines.append('%s：读取失败（%s）' % (os.path.basename(p), type(e).__name__))
        return '\n'.join(lines)

    if action == 'merge':
        if len(paths) < 2:
            return '合并至少要给两个 PDF。'
        w = pypdf.PdfWriter()
        try:
            for p in paths:
                r = pypdf.PdfReader(p)
                for pg in r.pages:
                    w.add_page(pg)
            out = _out(args.get('name') or '合并结果')
            with open(out, 'wb') as f:
                w.write(f)
            return ('已合并 %d 个文件 → 输出\\%s（共 %d 页，%.1f KB）'
                    % (len(paths), os.path.basename(out), len(w.pages), os.path.getsize(out) / 1024))
        except Exception as e:
            return '合并失败：%s: %s' % (type(e).__name__, str(e)[:120])

    if action == 'text':
        try:
            r = pypdf.PdfReader(paths[0])
            chunks = []
            for i, pg in enumerate(r.pages[:10]):
                t = (pg.extract_text() or '').strip()
                if t:
                    chunks.append('—— 第 %d 页 ——\n%s' % (i + 1, t))
            body = '\n\n'.join(chunks) or '（这份 PDF 没有可直接提取的文字，可能是扫描件/图片版）'
            if chunks and _looks_garbled(body):
                body = ('（注意）提取到的文字看着像乱码：这份 PDF 很可能没有可用的文字层'
                        '（扫描件，或生成时字体没带 ToUnicode 表）。\n'
                        '建议改用 OCR（本机装了 OCR 能力）或换一份 PDF，不要把上面这堆字符当正文。\n\n'
                        + body)
            return body[:4000]
        except Exception as e:
            return '提取文字失败：%s: %s' % (type(e).__name__, str(e)[:120])

    if action == 'split':
        try:
            r = pypdf.PdfReader(paths[0])
            total = len(r.pages)
            picks = _parse_pages(args.get('pages'), total)
            if not picks:
                return '没有解析出要拆的页码（原文共 %d 页）。' % total
            base = os.path.splitext(os.path.basename(paths[0]))[0]
            prefix = str(args.get('name') or '').strip()
            prefix = os.path.basename(prefix) if prefix else base
            prefix = os.path.splitext(prefix)[0] or base
            made = []
            for n in picks:
                w = pypdf.PdfWriter()
                w.add_page(r.pages[n])
                out = _out('%s_第%02d页' % (prefix, n + 1))
                with open(out, 'wb') as f:
                    w.write(f)
                made.append(os.path.basename(out))
            return '已拆分 %d 页到 输出\\ 下：%s' % (len(made), '、'.join(made))
        except Exception as e:
            return '拆分失败：%s: %s' % (type(e).__name__, str(e)[:120])

    return '未知 action：%s（可用：info / merge / split / text）' % action
