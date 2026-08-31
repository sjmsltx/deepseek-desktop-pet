# -*- coding: utf-8 -*-
"""二分：subprocess git 卡点"""
import os
import subprocess
import time

BASE = r'E:\ai工作站\desktop-pet'
open(BASE + r'\zz_timing.txt', 'w').write('t')
subprocess.run(['git', 'add', '-A'], cwd=BASE, capture_output=True, timeout=30)

def timed(name, cmd, timeout=20, **kw):
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=BASE, capture_output=True, timeout=timeout, **kw)
        print(f'{name}: {time.time() - t0:.1f}s rc={r.returncode}')
        return r
    except subprocess.TimeoutExpired:
        print(f'{name}: ⏱️ 超时 {timeout}s')
        return None

timed('git status', ['git', 'status'])
timed('git diff --cached', ['git', 'diff', '--cached', '--stat'])
timed('git commit', ['git', 'commit', '-m', 'zz timing test'])
timed('git commit --no-verify', ['git', 'commit', '--no-verify', '-m', 'zz timing test2'])

# 清理
os.remove(BASE + r'\zz_timing.txt')
subprocess.run(['git', 'add', '-A'], cwd=BASE, capture_output=True, timeout=30)
subprocess.run(['git', 'commit', '-m', 'cleanup zz'], cwd=BASE, capture_output=True, timeout=30)
print('清理完成')
