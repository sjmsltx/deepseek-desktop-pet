# -*- coding: utf-8 -*-
"""精确检查：工作区与各历史版本的 memory_engine.py BOM 状态"""
import io
import subprocess

BASE = r'E:\ai工作站\desktop-pet'

# 工作区
wb = open(BASE + r'\memory_engine.py', 'rb').read()
print('工作区 BOM:', wb[:3] == b'\xef\xbb\xbf')

# HEAD 版本（用 git show 输出到 python 内存）
for ref in ('HEAD', 'HEAD~1', 'HEAD~2'):
    out = subprocess.run(['git', 'show', f'{ref}:memory_engine.py'],
                         cwd=BASE, capture_output=True).stdout
    print(f'{ref} BOM:', out[:3] == b'\xef\xbb\xbf')
