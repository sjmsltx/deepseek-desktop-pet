# -*- coding: utf-8 -*-
"""验证 edit_own_code 多文件"""
import os

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtWidgets import QApplication, QMessageBox
QMessageBox.information = staticmethod(lambda *a, **k: None)
app = QApplication([])

import desktop_pet
w = desktop_pet.PetWidget()
w.ai_enabled = False

# 1. 白名单拦截
r = w._edit_own_code('x', 'y', file='config.json')
assert '不允许' in r, r
r2 = w._edit_own_code('x', 'y', file='../evil.py')
assert '不允许' in r2, r2
print('1. 白名单拦截 OK')

# 2. 不存在文件
r3 = w._edit_own_code('x', 'y', file='nonexist.py')
assert '不存在' in r3, r3
print('2. 文件不存在 OK')

# 3. 真实跨模块修改（memory_engine.py 改 docstring 加一行注释 → git 保护流程 → 还原）
marker = '\n# v6.41 AI 自改测试标记'
old_txt = '"""\nmemory_engine.py — 记忆引擎（Phase 1 重构）'
new_txt = '"""\nmemory_engine.py — 记忆引擎（Phase 1 重构）' + marker
r4 = w._edit_own_code(old_text=old_txt, new_text=new_txt, file='memory_engine.py')
print('3. 修改 memory_engine:', r4[:100])
src = open('memory_engine.py', encoding='utf-8').read()
if marker in src:
    src = src.replace(marker, '')
    open('memory_engine.py', 'w', encoding='utf-8').write(src)
    print('   ✅ 跨模块修改生效，已还原')
else:
    print('   ⚠️ 修改未生效:', r4[:150])

# 4. 默认仍改 desktop_pet.py
r5 = w._edit_own_code(old_text='desktop_pet.py — 主程序', new_text='desktop_pet.py — 主程序', file='')
print('4. 默认 file 行为:', '已修改' in r5 or '未找到' in r5 or '失败' in r5)
app.quit()
print('验证完成')
