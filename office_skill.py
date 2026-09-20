# -*- coding: utf-8 -*-
"""office_skill.py — 办公文档技能（WPS / Microsoft Office，COM 驱动）v6.66
=========================================================================

背景（为什么做这个）
--------------------
使用者提出："这个产品写代码没问题，但日常任务（比如 WPS 表格/文档）行不行？"
实测：本项目原先 **29 个工具全是通用/系统类**，`write_file` 只能产出纯文本（.md/.csv），
**没有任何能生成带格式的 .xlsx/.docx/.pptx 的工具** → 日常办公任务确实做不了。

本模块补上这块能力，走**官方 COM 接口**（最稳、能力最全），并优先用 WPS、退回 MS Office：

| 能力 | 说明 |
|---|---|
| `office_info()` | 列出本机可用的办公接口（WPS 表格/文字/演示、Excel/Word/PowerPoint） |
| `sheet_write()` | 新建/打开表格，写入二维数据（支持指定工作表与起始单元格） |
| `sheet_read()` | 读回表格区域（用于校验、汇总、转给用户看） |
| `make_report()` | 生成**带样式的报表**：标题合并居中、表头加粗填色、边框、列宽自适应、数字格式 |
| `export_pdf()` | 把 xlsx/docx 导出为 PDF |
| `make_doc()` | （v6.67）生成 Word 文档：标题 + 段落 + 表格（python-docx，**不依赖装了 Word**） |
| `make_slides()` | （v6.67）生成 PPT 演示：封面 + 要点页（python-pptx，**不依赖装了 PPT**） |

实测（2026-09-19，本机）：全部 6 个 ProgID 都可用（WPS KWPS/KET/KWPP v14.0、Excel 16.0）；
`pywin32` 已随环境安装。失败一律返回**可读的错误**，不抛异常给 AI 层。

注意：COM 调用会真的启一个 Office/WPS 进程（隐藏窗口），用完立即 Quit 并释放，避免残留。
"""
import os
import time

from pet_log import get_logger

_log = get_logger('office_skill')

# 每类文档的 ProgID 候选（前面的优先 = WPS 优先）
APP_CANDIDATES = {
    'sheet': ('KET.Application', 'Excel.Application'),
    'doc': ('KWPS.Application', 'Word.Application'),
    'slides': ('KWPP.Application', 'PowerPoint.Application'),
}
APP_LABEL = {'sheet': '表格', 'doc': '文字', 'slides': '演示'}

XL_OPENXML = 51        # .xlsx
XL_PDF = 0             # ExportAsFixedFormat 的 PDF 类型
WD_PDF = 17            # Word 的 wdExportFormatPDF
CACHE_TTL = 300        # 能力检测缓存 5 分钟（COM 探测要 1~2 秒，别每次都探）

_info_cache = {'at': 0, 'data': None}


def _dispatch(kind, prefer_wps=True):
    """拿一个办公应用对象。返回 (app, prog_id, error)"""
    try:
        import win32com.client
    except Exception as e:
        return None, '', '缺少 pywin32（win32com）：%s' % type(e).__name__
    names = list(APP_CANDIDATES.get(kind) or ())
    if not prefer_wps:
        names.reverse()
    errs = []
    for prog in names:
        try:
            app = win32com.client.Dispatch(prog)
            return app, prog, ''
        except Exception as e:
            errs.append('%s(%s)' % (prog, str(e)[:30]))
    return None, '', '本机没有可用的%s应用：%s' % (APP_LABEL.get(kind, kind), '；'.join(errs))


def _quit(app):
    try:
        app.DisplayAlerts = False
    except Exception:
        pass
    try:
        app.Quit()
    except Exception:
        pass


def _norm_rows(rows):
    """把二维数据洗成 list[list]（容忍 JSON 字符串 / 一维列表 / None）"""
    parsed_json = False
    if isinstance(rows, str):
        import json
        try:
            rows = json.loads(rows)
            parsed_json = True
        except Exception:
            # 换行文本：每行一条（这种“扁平字符串列表”不能被当成同一行）
            rows = [r.strip() for r in rows.splitlines() if r.strip()]
    elif isinstance(rows, (list, tuple)):
        parsed_json = True          # 调用方直接给的 Python 列表：扁平就视为一行
    if rows is None:
        return []
    if not isinstance(rows, (list, tuple)):
        rows = [rows]
    if parsed_json and rows and not any(isinstance(r, (list, tuple)) for r in rows):
        rows = [list(rows)]
    out = []
    for r in rows:
        if isinstance(r, str):
            s = r.strip()
            if s.startswith('[') and s.endswith(']'):
                try:
                    import json as _json
                    parsed = _json.loads(s)
                    if isinstance(parsed, (list, tuple)):
                        out.append([('' if c is None else c) for c in parsed])
                        continue
                except Exception:
                    pass
            out.append([r])
        elif isinstance(r, (list, tuple)):
            out.append([('' if c is None else c) for c in r])
        else:
            out.append([('' if r is None else r)])
    return out


def _probe_available():
    """在**独立子进程**里探测本机可用办公接口。返回 {kind: {'prog_id':…, 'version':…}}。

    为什么放进子进程（v6.70 修复）：COM 在 RPC 服务器异常时会抛 **Windows 致命异常**
    （0x8007006ba / 0x8007006be），Python 的 try/except **抓不住** —— 这里硬打 Dispatch
    曾把整个测试进程（乃至真机的桌宠）打崩。隔离后：崩也只崩探测子进程。
    用 PowerShell 而不是 `sys.executable -c`，因为**打包（冻结）后 sys.executable 是桌宠 exe**，
    再跑 `-c` 会变成再启一个桌宠。
    """
    import json as _json
    import os as _os
    import subprocess
    ps1 = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'office_probe.ps1')
    if not _os.path.exists(ps1):
        return {}
    try:
        p = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ps1],
                           capture_output=True, text=True, encoding='utf-8', errors='replace',
                           timeout=45, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        lines = [l.strip() for l in (p.stdout or '').splitlines() if l.strip()]
        if not lines:
            return {}
        data = _json.loads(lines[-1])
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def office_info(refresh=False):
    """探测本机可用的办公接口。返回 (dict, error)

    v6.70：探测改到独立子进程（见 _probe_available），避开 COM 致命异常打崩主进程。
    """
    now = time.time()
    if not refresh and _info_cache['data'] and now - _info_cache['at'] < CACHE_TTL:
        return _info_cache['data'], ''
    data = _probe_available()
    _info_cache['at'] = now
    _info_cache['data'] = data
    if data:
        return data, ''
    return {}, '本机没有探测到可用的办公接口（WPS 表格/文字/演示 或 Office Excel/Word/PowerPoint）'


def sheet_write(path, rows, sheet='Sheet1', start='A1', prefer_wps=True):
    """写入二维数据到 .xlsx（不存在则新建）。返回人类可读的结果说明"""
    data = _norm_rows(rows)
    if not data:
        return '没有要写入的数据', False
    app, prog, err = _dispatch('sheet', prefer_wps)
    if app is None:
        return err, False
    wb = None
    created = not os.path.exists(path)
    try:
        app.Visible = False
        app.DisplayAlerts = False
        if created:
            wb = app.Workbooks.Add()
        else:
            wb = app.Workbooks.Open(os.path.abspath(path))
        try:
            ws = wb.Worksheets(sheet)
        except Exception:
            ws = wb.Worksheets.Add()
            ws.Name = sheet
        n_rows = len(data)
        n_cols = max(len(r) for r in data)
        r0, c0 = _split_cell(start)
        for i, row in enumerate(data):
            for j, val in enumerate(row):
                ws.Cells(r0 + i, c0 + j).Value = val
        os.makedirs(os.path.dirname(os.path.abspath(path)) or '.', exist_ok=True)
        wb.SaveAs(os.path.abspath(path), XL_OPENXML)
        return ('已写入 %s：%d 行 × %d 列（工作表 %s，起始 %s）| 引擎 %s'
                % (os.path.basename(path), n_rows, n_cols, sheet, start, prog)), True
    except Exception as e:
        return '写入失败：%s: %s' % (type(e).__name__, str(e)[:120]), False
    finally:
        if wb is not None:
            try:
                wb.Close(SaveChanges=False)
            except Exception:
                pass
        _quit(app)


def _split_cell(ref):
    """'A1' → (1, 1)"""
    ref = str(ref or 'A1').strip().upper()
    letters = ''.join(ch for ch in ref if ch.isalpha()) or 'A'
    digits = ''.join(ch for ch in ref if ch.isdigit()) or '1'
    col = 0
    for ch in letters:
        col = col * 26 + (ord(ch) - 64)
    return int(digits), max(1, col)


def _norm_cell(c):
    """单元格值归一成便于给 AI 看的文本：日期 → 'YYYY-MM-DD'，浮点整数去 .0"""
    if c is None:
        return ''
    try:
        import datetime
        if hasattr(c, 'year') and hasattr(c, 'month') and hasattr(c, 'day'):
            return c.strftime('%Y-%m-%d')
        if isinstance(c, float):
            return int(c) if abs(c - int(c)) < 1e-9 else round(c, 6)
    except Exception:
        pass
    return c


def sheet_read(path, sheet=None, cell_range=None, limit=200, prefer_wps=True):
    """读表格内容。返回 (rows, error)；rows 为 list[list]"""
    if not os.path.exists(path):
        return [], '文件不存在：%s' % path
    app, prog, err = _dispatch('sheet', prefer_wps)
    if app is None:
        return [], err
    wb = None
    try:
        app.Visible = False
        app.DisplayAlerts = False
        wb = app.Workbooks.Open(os.path.abspath(path), ReadOnly=True)
        ws = wb.Worksheets(sheet) if sheet else wb.Worksheets(1)
        rng = ws.Range(cell_range) if cell_range else ws.UsedRange
        vals = rng.Value
        if vals is None:
            return [], ''
        if not isinstance(vals, tuple):        # 单个单元格
            return [[vals]], ''
        rows = []
        for row in vals[:limit]:
            if isinstance(row, tuple):
                rows.append([_norm_cell(c) for c in row])
            else:
                rows.append([_norm_cell(row)])
        return rows, ''
    except Exception as e:
        return [], '读取失败：%s: %s' % (type(e).__name__, str(e)[:120])
    finally:
        if wb is not None:
            try:
                wb.Close(SaveChanges=False)
            except Exception:
                pass
        _quit(app)


def make_report(path, title, headers, rows, footer='', prefer_wps=True):
    """生成带样式的报表（标题合并居中 / 表头加粗填色 / 全表边框 / 列宽自适应）"""
    data = _norm_rows(rows)
    hdr = (_norm_rows(headers)[0] if headers else [])
    if not hdr and not data:
        return '没有内容可生成', False
    n_cols = max([len(hdr)] + [len(r) for r in data] or [1])
    app, prog, err = _dispatch('sheet', prefer_wps)
    if app is None:
        return err, False
    wb = None
    try:
        app.Visible = False
        app.DisplayAlerts = False
        wb = app.Workbooks.Add()
        ws = wb.Worksheets(1)
        r = 1
        if title:
            ws.Cells(r, 1).Value = title
            rng = ws.Range(ws.Cells(r, 1), ws.Cells(r, n_cols))
            rng.Merge()
            rng.Font.Bold = True
            rng.Font.Size = 14
            rng.HorizontalAlignment = -4108        # xlCenter
            ws.Rows(r).RowHeight = 26
            r += 1
        if hdr:
            for j, v in enumerate(hdr):
                ws.Cells(r, j + 1).Value = v
            hr = ws.Range(ws.Cells(r, 1), ws.Cells(r, n_cols))
            hr.Font.Bold = True
            hr.Interior.Color = 0xE6DFD8           # BGR 浅灰米色（与桌宠气质接近）
            hr.HorizontalAlignment = -4108
            r += 1
        first_data_row = r
        for row in data:
            for j, v in enumerate(row):
                ws.Cells(r, j + 1).Value = v
            r += 1
        last = max(r - 1, first_data_row)
        body = ws.Range(ws.Cells(first_data_row, 1), ws.Cells(last, n_cols))
        body.Borders.LineStyle = 1                 # xlContinuous
        try:
            ws.Columns.AutoFit()
        except Exception:
            pass
        if footer:
            ws.Cells(r + 1, 1).Value = footer
        os.makedirs(os.path.dirname(os.path.abspath(path)) or '.', exist_ok=True)
        wb.SaveAs(os.path.abspath(path), XL_OPENXML)
        return ('已生成报表 %s：%d 列 × %d 行数据（引擎 %s）'
                % (os.path.basename(path), n_cols, len(data), prog)), True
    except Exception as e:
        return '生成报表失败：%s: %s' % (type(e).__name__, str(e)[:120]), False
    finally:
        if wb is not None:
            try:
                wb.Close(SaveChanges=False)
            except Exception:
                pass
        _quit(app)


def make_doc(path, title='', paragraphs=None, headers=None, rows=None, subtitle=''):
    """生成 Word 文档（python-docx，不需要本机装 Word）。返回 (说明, 是否成功)

    - title：一级标题；subtitle：副标题段落
    - paragraphs：段落文本列表（字符串或 {'style': 'Heading 1'|'List Bullet', 'text': ...}）
    - headers/rows：可选的表格
    """
    try:
        from docx import Document
        from docx.shared import Pt
    except Exception as e:
        return '没装 python-docx，无法生成 Word：%s' % e, False
    try:
        doc = Document()
        if title:
            doc.add_heading(str(title), level=0)
        if subtitle:
            p = doc.add_paragraph(str(subtitle))
            p.runs[0].font.size = Pt(11)
            p.runs[0].italic = True
        for item in (paragraphs or []):
            if isinstance(item, dict):
                style = str(item.get('style') or '')
                text = str(item.get('text') or '')
                if style.lower().startswith('heading'):
                    doc.add_heading(text, level=int(style[-1]) if style[-1].isdigit() else 1)
                elif 'bullet' in style.lower() or style.lower() == 'list':
                    doc.add_paragraph(text, style='List Bullet')
                else:
                    doc.add_paragraph(text)
            else:
                doc.add_paragraph(str(item))
        hdr = _norm_rows(headers)[0] if headers else []
        data = _norm_rows(rows)
        if hdr or data:
            n_cols = max([len(hdr)] + [len(r) for r in data] or [1])
            t = doc.add_table(rows=0, cols=n_cols)
            t.style = 'Light Grid Accent 1'
            if hdr:
                cells = t.add_row().cells
                for i, v in enumerate(hdr):
                    cells[i].text = str(v)
            for r in data:
                cells = t.add_row().cells
                for i, v in enumerate(r[:n_cols]):
                    cells[i].text = _norm_cell(v)
        os.makedirs(os.path.dirname(os.path.abspath(path)) or '.', exist_ok=True)
        doc.save(os.path.abspath(path))
        return '已生成 Word：%s' % os.path.basename(path), True
    except Exception as e:
        return '生成 Word 失败：%s: %s' % (type(e).__name__, str(e)[:120]), False


def make_slides(path, title='', slides=None, subtitle=''):
    """生成 PPT 演示（python-pptx，不需要本机装 PowerPoint）。返回 (说明, 是否成功)

    slides 形如 [{'title': '页标题', 'bullets': ['要点1', '要点2'], 'notes': '备注（可选）'}, ...]
    """
    try:
        from pptx import Presentation
        from pptx.util import Inches
    except Exception as e:
        return '没装 python-pptx，无法生成 PPT：%s' % e, False
    try:
        prs = Presentation()
        # 封面
        cover = prs.slides.add_slide(prs.slide_layouts[0])
        cover.shapes.title.text = str(title or '演示文稿')
        if len(cover.placeholders) > 1 and subtitle:
            cover.placeholders[1].text = str(subtitle)
        for sl in (slides or []):
            sl = sl or {}
            slide = prs.slides.add_slide(prs.slide_layouts[1])
            slide.shapes.title.text = str(sl.get('title') or '')
            body = slide.placeholders[1].text_frame
            body.text = ''
            bullets = sl.get('bullets') or ([sl['text']] if sl.get('text') else [])
            for i, b in enumerate(bullets):
                p = body.paragraphs[0] if i == 0 else body.add_paragraph()
                p.text = str(b)
                p.level = 0 if not isinstance(b, dict) else int(b.get('level') or 0)
            if sl.get('notes'):
                slide.notes_slide.notes_text_frame.text = str(sl['notes'])
        os.makedirs(os.path.dirname(os.path.abspath(path)) or '.', exist_ok=True)
        prs.save(os.path.abspath(path))
        return '已生成 PPT：%s（%d 页）' % (os.path.basename(path), len(prs.slides._sldIdLst)), True
    except Exception as e:
        return '生成 PPT 失败：%s: %s' % (type(e).__name__, str(e)[:120]), False


def export_pdf(src, out, prefer_wps=True):
    """把 xlsx/docx 导出为 PDF。返回 (结果说明, 是否成功)"""
    if not os.path.exists(src):
        return '文件不存在：%s' % src, False
    ext = os.path.splitext(src)[1].lower()
    kind = 'sheet' if ext in ('.xlsx', '.xls', '.et') else 'doc'
    app, prog, err = _dispatch(kind, prefer_wps)
    if app is None:
        return err, False
    doc = None
    try:
        app.Visible = False
        app.DisplayAlerts = False
        if kind == 'sheet':
            doc = app.Workbooks.Open(os.path.abspath(src))
            doc.ExportAsFixedFormat(XL_PDF, os.path.abspath(out))
        else:
            doc = app.Documents.Open(os.path.abspath(src))
            doc.ExportAsFixedFormat(os.path.abspath(out), WD_PDF)
        return '已导出 PDF：%s（引擎 %s）' % (os.path.basename(out), prog), True
    except Exception as e:
        return ('导出 PDF 失败：%s: %s（部分 WPS 版本不支持该接口，可改用「另存为 PDF」）'
                % (type(e).__name__, str(e)[:100])), False
    finally:
        if doc is not None:
            try:
                doc.Close(False)
            except Exception:
                pass
        _quit(app)
