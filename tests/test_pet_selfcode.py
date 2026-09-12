# -*- coding: utf-8 -*-
"""tests/test_pet_selfcode.py — 「看/改自己代码」工具单测
=========================================================
背景（2026-09-12 结构性重构）：search_code / write_file_tool / edit_own_code 的实现
原先长在 PetWidget 里（177 行），搬到了 pet_selfcode.py。这三个函数直接决定
「AI 能不能改自己」，属于**安全关键路径**，必须有常驻测试兜底。

本测试不需要 Qt，且自带「源码哈希不变」校验：跑完确认没有任何 .py 被改动
（edit_own_code 的语法拦截、路径拦截等分支必须真的"不写盘"）。

运行：python tests/test_pet_selfcode.py
"""
import hashlib
import os
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from pet_selfcode import search_code, write_file_tool, edit_own_code  # noqa: E402

fails = []


def check(name, cond, detail=''):
    if not cond:
        fails.append('%s %s' % (name, detail))


def fingerprint():
    h = hashlib.sha256()
    for f in sorted(os.listdir(BASE)):
        if f.endswith('.py'):
            with open(os.path.join(BASE, f), 'rb') as fh:
                h.update(fh.read())
    return h.hexdigest()


FP0 = fingerprint()

# ---------- search_code ----------
r = search_code('临时文件再 os.replace', base_dir=BASE)
check('搜索命中', 'pet_storage.py' in r and 'os.replace' in r, repr(r[:80]))
check('搜索无结果可读提示', '未找到包含' in search_code('绝不可能出现的关键词xyzzy', base_dir=BASE))
check('空关键词被拒', '请提供搜索关键词' in search_code('', base_dir=BASE))

# ---------- write_file_tool ----------
out = write_file_tool('_selftest_write.txt', '内容ABC', base_dir=BASE)
check('写文件成功提示', '已生成文件' in out and '_selftest_write.txt' in out, repr(out[:80]))
written = [os.path.join(BASE, '_selftest_write.txt'), os.path.join(BASE, '输出', '_selftest_write.txt')]
found = [p for p in written if os.path.exists(p)]
check('文件真的落盘', bool(found), written)
for p in found:
    os.remove(p)
tmp = os.path.join(BASE, '输出', 'output.txt')
if os.path.exists(tmp):
    os.remove(tmp)

# ---------- edit_own_code：六类拒绝分支（都必须"不写盘"）----------
e = edit_own_code('', '# x', 1, 1, 'no_such_module.py', base_dir=BASE)
check('拒绝：文件不存在', '文件不存在' in e, e[:60])
e = edit_own_code('', '# x', 1, 1, '../outside.py', base_dir=BASE)
check('拒绝：路径穿越', '不允许修改的文件' in e, e[:60])
e = edit_own_code('', '# x', 1, 1, 'README.md', base_dir=BASE)
check('拒绝：非 .py 文件', '不允许修改的文件' in e, e[:60])
e = edit_own_code('', '# x', 9999, 9999, 'pet_storage.py', base_dir=BASE)
check('拒绝：行号越界', '行号越界' in e, e[:60])
e = edit_own_code('绝不存在的旧文本xyz', '新文本', None, None, 'pet_storage.py', base_dir=BASE)
check('拒绝：old_text 不匹配', '未找到要修改的代码段' in e, e[:60])
e = edit_own_code('', 'def broken(:\n    pass', 1, 1, 'pet_storage.py', base_dir=BASE)
check('拒绝：语法校验失败', '语法验证失败' in e or '修改失败' in e, e[:60])

# ---------- 安全底线：全程不得改动任何源码 ----------
check('源码未被任何分支改动', fingerprint() == FP0)

print('pet_selfcode 单测：12 组断言')
if fails:
    for f in fails:
        print('  ❌ ' + f)
    print('结果：FAIL %d 组' % len(fails))
    sys.exit(1)
print('结果：全部通过 ✅')
