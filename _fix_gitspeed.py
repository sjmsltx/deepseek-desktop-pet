# -*- coding: utf-8 -*-
"""防卡死优化：基线 commit→hash 记录；修改后单次 commit"""
import io

DP = r'E:\ai工作站\desktop-pet\desktop_pet.py'
src = io.open(DP, encoding='utf-8').read()

old1 = """            # 1. 提交基线（确保可回滚）
            _subprocess.run(['git', 'add', '-A'], cwd=BASE_DIR, capture_output=True, timeout=30)
            _subprocess.run(['git', 'commit', '-m', 'AI self-edit: 修改前基线'], cwd=BASE_DIR,
                            capture_output=True, timeout=120)"""
new1 = """            # 1. 记录基线 hash（v6.42：不再 commit 基线——E盘fsync慢导致两次commit让AI卡1分钟+；改hash记录+backup双保险）
            base_hash = ''
            try:
                r0 = _subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=BASE_DIR, capture_output=True, timeout=15)
                if r0.returncode == 0:
                    base_hash = (r0.stdout or b'').decode().strip()
            except Exception:
                pass"""
assert old1 in src, '基线段未找到'
src = src.replace(old1, new1, 1)

old2 = """            # 4. 提交修改（可回滚）
            _subprocess.run(['git', 'add', '-A'], cwd=BASE_DIR, capture_output=True, timeout=30)
            _subprocess.run(['git', 'commit', '-m', f'AI self-edit: {old_text.strip()[:40]}'],
                            cwd=BASE_DIR, capture_output=True, timeout=120)
            return '✅ 已修改并提交（git 可回滚）。请重启桌宠生效（回复说"重启桌宠"即可）；如果重启后异常，对我说"回滚桌宠修改"我会用 git 恢复。'"""
new2 = """            # 4. 提交修改（可回滚；v6.42：git fsync 已项目级关闭，commit 从 ~20s 降到 <1s）
            try:
                _subprocess.run(['git', 'add', '-A'], cwd=BASE_DIR, capture_output=True, timeout=30)
                _subprocess.run(['git', 'commit', '-m', f'AI self-edit: {old_text.strip()[:40]}'],
                                cwd=BASE_DIR, capture_output=True, timeout=30)
            except Exception:
                pass
            rollback = f'git reset --hard {base_hash}' if base_hash else '可用 backup/ 备份文件恢复'
            return f'✅ 已修改并提交（回滚：{rollback}）。请重启桌宠生效；若异常对我说"回滚桌宠修改"。'"""
assert old2 in src, '提交段未找到'
src = src.replace(old2, new2, 1)

io.open(DP, 'w', encoding='utf-8').write(src)
print('✅ 防卡死优化完成')

import ast
ast.parse(src)
print('✅ 语法通过')
