# -*- coding: utf-8 -*-
"""git commit 超时 60→120s（E 盘 fsync 慢实测 17.9s+）"""
import io

DP = r'E:\ai工作站\desktop-pet\desktop_pet.py'
src = io.open(DP, encoding='utf-8').read()

src = src.replace("capture_output=True, timeout=60)", "capture_output=True, timeout=120)")

io.open(DP, 'w', encoding='utf-8').write(src)
print('✅ git 超时 60→120s')

import ast
ast.parse(src)
print('✅ 语法通过')
