# -*- coding: utf-8 -*-
"""根治：清理所有 .py BOM 并提交"""
import io
import os
import subprocess

BASE = r'E:\ai工作站\desktop-pet'
cleaned = []
for f in sorted(os.listdir(BASE)):
    if not f.endswith('.py'):
        continue
    p = os.path.join(BASE, f)
    raw = open(p, 'rb').read()
    if raw.startswith(b'\xef\xbb\xbf'):
        open(p, 'wb').write(raw[3:])
        cleaned.append(f)
print('清理 BOM:', cleaned)
if cleaned:
    subprocess.run(['git', 'add', '-A'], cwd=BASE, capture_output=True, timeout=30)
    subprocess.run(['git', 'commit', '-m', 'chore: 根治 .py BOM（git历史曾含BOM导致restore反复恢复）'], cwd=BASE,
                   capture_output=True, timeout=60)
    print('已提交')
# 验证
for f in sorted(os.listdir(BASE)):
    if f.endswith('.py'):
        if open(os.path.join(BASE, f), 'rb').read(3) == b'\xef\xbb\xbf':
            print('仍有 BOM:', f)
print('验证完成')
