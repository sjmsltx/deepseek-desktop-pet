# -*- coding: utf-8 -*-
"""复现 subprocess git commit 耗时（同 _edit_own_code 参数）"""
import subprocess
import time

BASE = r'E:\ai工作站\desktop-pet'
# 模拟：改一个文件触发
open(BASE + r'\backup_timing_test.txt', 'w').write('x')

t0 = time.time()
r1 = subprocess.run(['git', 'add', '-A'], cwd=BASE, capture_output=True, timeout=60)
t1 = time.time()
print(f'git add: {t1 - t0:.1f}s rc={r1.returncode}')

msg = 'AI self-edit: test timing'
r2 = subprocess.run(['git', 'commit', '-m', msg], cwd=BASE, capture_output=True, timeout=60)
t2 = time.time()
print(f'git commit(普通): {t2 - t1:.1f}s rc={r2.returncode}')

# 多行特殊 message
open(BASE + r'\backup_timing_test2.txt', 'w').write('y')
r3 = subprocess.run(['git', 'add', '-A'], cwd=BASE, capture_output=True, timeout=60)
msg2 = 'AI self-edit: """\nmemory_engine.py — 记忆引擎（Phase 1 重构）'
r4 = subprocess.run(['git', 'commit', '-m', msg2], cwd=BASE, capture_output=True, timeout=60)
t3 = time.time()
print(f'git commit(多行中文): {t3 - t2:.1f}s rc={r4.returncode}')

# 清理
import os
os.remove(BASE + r'\backup_timing_test.txt')
os.remove(BASE + r'\backup_timing_test2.txt')
subprocess.run(['git', 'add', '-A'], cwd=BASE, capture_output=True, timeout=60)
subprocess.run(['git', 'commit', '-m', 'cleanup timing test'], cwd=BASE, capture_output=True, timeout=60)
print('清理完成')
