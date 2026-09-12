# -*- coding: utf-8 -*-
"""pet_docs.py — 文档/图片文本提取（2026-09-12 从 desktop_pet.PetWidget 搬出）
=========================================================================
原本 docx/pdf/xlsx/pptx 四个解析器 + Windows OCR + 「AI 读自身源码」都长在
PetWidget 里（那个类已经 5889 行），但它们**完全不依赖 UI 或宿主状态**：
唯一的外部依赖是项目根目录，改成参数传入即可。

搬出来的收益：
1. 宿主类减重（附件/文档解析不再占它的行数）；
2. 解析逻辑可独立单测 —— tests/test_pet_docs.py 用**构造的 zip / 手写 PDF 样本**
   覆盖正常与异常分支，不需要起 Qt；
3. 以后要加格式（odt、csv 表格等）只动这一个文件。

接口（纯函数，失败时返回以「（…失败：原因）」开头的可读文本，绝不抛异常）：
    read_docx_text(path) / read_pdf_text(path) / read_xlsx_text(path) / read_pptx_text(path)
    ocr_image(path, ps1_path)                     Windows 自带 OCR（PowerShell WinRT）
    read_own_file(rel_path, base_dir, start_line=None, end_line=None)
    TEXT_BY_KIND                                  附件 kind → 解析函数
"""
import os
import re
import subprocess


def read_docx_text(path):
    """docx 文本提取：zip + XML，纯标准库（docx 本质是 zip 包）"""
    import zipfile
    import re as _re
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read('word/document.xml').decode('utf-8', errors='ignore')
        # 按段落拆（</w:p>），逐段提取 <w:t> 文本，段落间换行
        paras = []
        for seg in xml.split('</w:p>'):
            ts = _re.findall(r'<w:t[^>]*>(.*?)</w:t>', seg, _re.S)
            if ts:
                paras.append(''.join(ts))
        return '\n'.join(paras).strip()
    except Exception as e:
        return f'（docx 解析失败：{e}）'

def read_pdf_text(path):
    """pdf 文本提取（需 pypdf：pip install pypdf）"""
    try:
        from pypdf import PdfReader
    except ImportError:
        return '（PDF 解析需要 pypdf：pip install pypdf，安装后重启桌宠即可读取）'
    try:
        reader = PdfReader(path)
        pages = []
        for i, page in enumerate(reader.pages[:15]):
            pages.append(page.extract_text() or '')
        return '\n'.join(pages).strip()
    except Exception as e:
        return f'（PDF 解析失败：{e}）'

def read_xlsx_text(path):
    """xlsx 文本提取：zip + sharedStrings（纯标准库）"""
    import zipfile
    import re as _re
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            parts = []
            if 'xl/sharedStrings.xml' in names:
                xml = z.read('xl/sharedStrings.xml').decode('utf-8', errors='ignore')
                parts.append('\n'.join(_re.findall(r'<t[^>]*>(.*?)</t>', xml, _re.S)))
            return '\n'.join(p for p in parts if p).strip() or '（空表格）'
    except Exception as e:
        return f'（xlsx 解析失败：{e}）'

def read_pptx_text(path):
    """pptx 文本提取：zip + 各 slide 的 <a:t>（纯标准库）"""
    import zipfile
    import re as _re
    try:
        with zipfile.ZipFile(path) as z:
            slides = sorted(n for n in z.namelist()
                            if n.startswith('ppt/slides/slide') and n.endswith('.xml'))
            parts = []
            for s in slides:
                xml = z.read(s).decode('utf-8', errors='ignore')
                texts = _re.findall(r'<a:t[^>]*>(.*?)</a:t>', xml, _re.S)
                if texts:
                    parts.append(''.join(texts))
            return '\n'.join(parts).strip() or '（空演示文稿）'
    except Exception as e:
        return f'（pptx 解析失败：{e}）'

def ocr_image(path, ps1_path):
    """Windows 自带 OCR（PowerShell WinRT，零依赖），返回识别文本"""
    try:
        r = subprocess.run(
            ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ps1_path, path],
            capture_output=True, timeout=120)
        if r.returncode != 0:
            return ''
        return r.stdout.decode('utf-8', errors='ignore').strip()
    except Exception:
        return ''

# ---------- 文件附件（拖放进聊天框） ----------

def read_own_file(rel_path, base_dir, start_line=None, end_line=None):
    """AI 读自己的文件（限项目目录内，防穿越；v6.25 支持行号范围，带行号输出方便精确引用）"""
    try:
        full = os.path.normpath(os.path.join(base_dir, rel_path or ''))
        if not full.startswith(os.path.normpath(base_dir)):
            return '（路径越界，拒绝读取）'
        if not os.path.isfile(full):
            # v6.41：目录 → 返回文件列表（AI 可浏览项目结构）
            if os.path.isdir(full):
                _lines = []
                for _f in sorted(os.listdir(full)):
                    _fp = os.path.join(full, _f)
                    if os.path.isfile(_fp):
                        try:
                            _n = sum(1 for _ in open(_fp, encoding='utf-8', errors='ignore'))
                        except Exception:
                            _n = 0
                        _lines.append(f'{_f} ({_n} 行)')
                    elif os.path.isdir(_fp):
                        _lines.append(f'{_f}/')
                return '（目录内容）\n' + '\n'.join(_lines[:60]) if _lines else '（空目录）'
            return f'（文件不存在：{rel_path}）'
        # 敏感文件禁止读取（API key/隐私数据，防止泄露给 AI）
        _low = full.lower()
        if any(_s in _low for _s in ('config.json', 'api_stats.json', 'affection.json',
                                     'memories.json', 'chat_memory', '.env', 'api_key', 'private_key')):
            return '（敏感文件拒绝读取：包含 API 密钥/隐私数据）'
        if _low.endswith(('.py', '.md', '.txt', '.json', '.bat', '.ps1', '.html')):
            with open(full, encoding='utf-8', errors='ignore') as f:
                content = f.read()  # 行号模式需读全文件（v6.25）
            if start_line is not None:
                try:
                    lines = content.splitlines()
                    s = max(0, int(start_line) - 1)
                    e = len(lines) if end_line is None else min(len(lines), int(end_line))
                    sel = lines[s:e]
                    content = '\n'.join(f'{s + i + 1}: {ln}' for i, ln in enumerate(sel))
                except Exception:
                    pass
            else:
                content = content[:8000]
            return content
        return f'（不支持读取该类型文件：{rel_path}）'
    except Exception as e:
        return f'（读取失败：{e}）'

# 附件 kind → 解析函数（desktop_pet 构建附件上下文时按 kind 取用）
TEXT_BY_KIND = {
    'docx': read_docx_text,
    'pdf': read_pdf_text,
    'xlsx': read_xlsx_text,
    'pptx': read_pptx_text,
}
