# -*- coding: utf-8 -*-
"""补：git 超时 30→60s（两行格式匹配）"""
import io

DP = r'E:\ai工作站\desktop-pet\desktop_pet.py'
src = io.open(DP, encoding='utf-8').read()

old1 = """            _subprocess.run(['git', 'commit', '-m', 'AI self-edit: 修改前基线'], cwd=BASE_DIR,
                            capture_output=True, timeout=30)"""
new1 = """            _subprocess.run(['git', 'commit', '-m', 'AI self-edit: 修改前基线'], cwd=BASE_DIR,
                            capture_output=True, timeout=60)"""
assert old1 in src, '基线提交未找到'
src = src.replace(old1, new1, 1)

old2 = """            _subprocess.run(['git', 'commit', '-m', f'AI self-edit: {old_text.strip()[:40]}'],
                            cwd=BASE_DIR, capture_output=True, timeout=30)"""
new2 = """            _subprocess.run(['git', 'commit', '-m', f'AI self-edit: {old_text.strip()[:40]}'],
                            cwd=BASE_DIR, capture_output=True, timeout=60)"""
assert old2 in src, '修改提交未找到'
src = src.replace(old2, new2, 1)

io.open(DP, 'w', encoding='utf-8').write(src)
print('✅ git 超时 30→60s')

import ast
ast.parse(src)
print('✅ 语法通过')
