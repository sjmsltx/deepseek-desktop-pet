# -*- coding: utf-8 -*-
"""tests/test_pet_docs.py — 文档/图片文本提取单测
=====================================================
背景（2026-09-12 结构性重构）：docx/pdf/xlsx/pptx 解析与 AI 读自身源码的逻辑
原先长在 PetWidget（5889 行宿主类）里，搬到了 pet_docs.py。搬出来后不需要 Qt
就能测——本文件用**现场构造的 zip 样本 + 手写最小 PDF**覆盖正常与异常分支。

运行：python tests/test_pet_docs.py
"""
import logging
import os
import sys
import tempfile
import zipfile

logging.getLogger('pypdf').setLevel(logging.CRITICAL)   # 坏文件分支会把 pypdf 的告警打到 stderr

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from pet_docs import (read_docx_text, read_pdf_text, read_xlsx_text,  # noqa: E402
                      read_pptx_text, read_own_file, TEXT_BY_KIND)

TMP = tempfile.mkdtemp(prefix='pet_docs_test_')
fails = []


def check(name, cond, detail=''):
    if not cond:
        fails.append('%s %s' % (name, detail))


# ---------- 构造样本 ----------
docx = os.path.join(TMP, 'a.docx')
with zipfile.ZipFile(docx, 'w') as z:
    z.writestr('word/document.xml',
               '<w:document><w:body>'
               '<w:p><w:r><w:t>第一段</w:t></w:r></w:p>'
               '<w:p><w:r><w:t>第二段 </w:t></w:r><w:r><w:t>多 run</w:t></w:r></w:p>'
               '</w:body></w:document>')
xlsx = os.path.join(TMP, 'a.xlsx')
with zipfile.ZipFile(xlsx, 'w') as z:
    z.writestr('xl/sharedStrings.xml', '<sst><si><t>姓名</t></si><si><t>张三</t></si></sst>')
pptx = os.path.join(TMP, 'a.pptx')
with zipfile.ZipFile(pptx, 'w') as z:
    z.writestr('ppt/slides/slide1.xml', '<a:t>封面</a:t>')
    z.writestr('ppt/slides/slide10.xml', '<a:t>第十页</a:t>')
empty_docx = os.path.join(TMP, 'empty.zip')
with zipfile.ZipFile(empty_docx, 'w') as z:
    z.writestr('word/document.xml', '<w:document><w:body></w:body></w:document>')
notzip = os.path.join(TMP, 'notzip.docx')
open(notzip, 'w', encoding='utf-8').write('我不是 zip')

pdf = os.path.join(TMP, 'a.pdf')
_content = b'BT /F1 24 Tf 72 700 Td (Hello Pet) Tj ET'
_objs = [
    b'1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj',
    b'2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj',
    b'3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R'
    b'/Resources<</Font<</F1 5 0 R>>>>>>endobj',
    b'4 0 obj<</Length %d>>stream\n' % len(_content) + _content + b'\nendstream endobj',
    b'5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj',
]
_buf = bytearray(b'%PDF-1.4\n')
_offs = []
for _o in _objs:
    _offs.append(len(_buf))
    _buf += _o + b'\n'
_xref = len(_buf)
_buf += b'xref\n0 %d\n0000000000 65535 f \n' % (len(_objs) + 1)
for _off in _offs:
    _buf += b'%010d 00000 n \n' % _off
_buf += b'trailer<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n' % (len(_objs) + 1, _xref)
open(pdf, 'wb').write(bytes(_buf))

# ---------- 断言 ----------
out = read_docx_text(docx)
check('docx 段落', '第一段' in out and '第二段 多 run' in out, repr(out))

out = read_xlsx_text(xlsx)
check('xlsx 共享字符串', '姓名' in out and '张三' in out, repr(out))

out = read_pptx_text(pptx)
check('pptx 幻灯片', '封面' in out and '第十页' in out, repr(out))

out = read_pdf_text(pdf)
check('pdf 文本', 'Hello Pet' in out, repr(out))

check('docx 空文档', isinstance(read_docx_text(empty_docx), str))
check('非 zip → 可读报错', read_docx_text(notzip).startswith('（docx 解析失败'), read_docx_text(notzip))
check('文件不存在 → 可读报错', '（docx 解析失败' in read_docx_text(os.path.join(TMP, 'nope.docx')))
check('pdf 坏文件 → 可读报错', read_pdf_text(notzip).startswith('（PDF'))
check('xlsx 坏文件 → 可读报错', read_xlsx_text(notzip).startswith('（xlsx'))
check('pptx 坏文件 → 可读报错', read_pptx_text(notzip).startswith('（pptx'))

# read_own_file 的分支
check('读普通文件', 'pet_docs' in read_own_file('pet_docs.py', BASE))
r = read_own_file('pet_storage.py', BASE, 1, 3)
check('行号范围带行号', r.splitlines()[0].startswith('1: '), repr(r[:40]))
check('行号越界返回空', read_own_file('pet_storage.py', BASE, 9000, 9999) == '')
check('目录 → 文件清单', read_own_file('tests', BASE).startswith('（目录内容）'))
check('敏感文件拦截', '敏感文件拒绝读取' in read_own_file('config.json', BASE))
check('不支持类型', '不支持读取该类型文件' in read_own_file('pet_log.py', BASE).replace('pet_log.py', 'x')
      or '不支持' in read_own_file('assets/pro/pro_idle.png', BASE))
check('路径越界拦截', '路径越界' in read_own_file('../outside.txt', BASE))
check('文件不存在', '文件不存在' in read_own_file('no_such_module_xyz.py', BASE))

check('TEXT_BY_KIND 覆盖四种格式',
      set(TEXT_BY_KIND) == {'docx', 'pdf', 'xlsx', 'pptx'} and
      all(callable(v) for v in TEXT_BY_KIND.values()))

print('pet_docs 单测：%d 组断言' % 18)
if fails:
    for f in fails:
        print('  ❌ ' + f)
    print('结果：FAIL %d 组' % len(fails))
    sys.exit(1)
print('结果：全部通过 ✅')
