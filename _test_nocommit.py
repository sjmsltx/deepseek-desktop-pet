# -*- coding: utf-8 -*-
"""实测：无 commit 版 edit_own_code 速度 + 回滚验证"""
import os
import subprocess
import time

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtWidgets import QApplication, QMessageBox
QMessageBox.information = staticmethod(lambda *a, **k: None)
app = QApplication([])

import desktop_pet
w = desktop_pet.PetWidget()
w.ai_enabled = False

BASE = r'E:\ai工作站\desktop-pet'
marker = '\n# v6.42 性能测试标记'
old_txt = '# -*- coding: utf-8 -*-'

# 1. 修改速度
t0 = time.time()
r = w._edit_own_code(old_text=old_txt, new_text=old_txt + marker, file='memory_engine.py')
dt = time.time() - t0
print(f'修改耗时: {dt:.1f}s | 结果: {r[:80]}')
src = open(BASE + r'\memory_engine.py', encoding='utf-8').read()
assert marker in src, '修改未生效'
assert dt < 5, f'仍太慢 {dt}s'
print(f'1. ✅ 修改秒级完成（{dt:.1f}s）')

# 2. 回滚（git restore）
subprocess.run(['git', 'restore', 'memory_engine.py'], cwd=BASE, capture_output=True, timeout=15)
src2 = open(BASE + r'\memory_engine.py', encoding='utf-8').read()
assert marker not in src2, '回滚失败'
print('2. ✅ git restore 回滚成功')

# 3. 语法错误拦截仍有效
r2 = w._edit_own_code(old_text='# -*- coding: utf-8 -*-', new_text='def broken(:', file='memory_engine.py')
assert '语法验证失败' in r2, r2[:100]
print('3. ✅ 语法拦截正常')
app.quit()
print('全部通过')
