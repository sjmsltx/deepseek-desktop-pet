# -*- coding: utf-8 -*-
"""v6.42 彻底防卡死：edit_own_code 去掉 git commit（E盘commit 60s+），回滚靠 git restore + backup"""
import io

DP = r'E:\ai工作站\desktop-pet\desktop_pet.py'
src = io.open(DP, encoding='utf-8').read()

# 1. 基线段：rev-parse HEAD 记录（已在位，检查）
old1 = """            # 1. 记录基线 hash（v6.42：不再 commit 基线——E盘fsync慢导致两次commit让AI卡1分钟+；改hash记录+backup双保险）
            base_hash = ''
            try:
                r0 = _subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=BASE_DIR, capture_output=True, timeout=15)
                if r0.returncode == 0:
                    base_hash = (r0.stdout or b'').decode().strip()
            except Exception:
                pass"""
assert old1 in src, '基线段未在位'
print('基线段已在位（hash 记录）')

# 2. 提交段 → 无 commit 版本
old2 = """            # 4. 提交修改（可回滚；v6.42：git fsync 已项目级关闭，commit 从 ~20s 降到 <1s）
            try:
                _subprocess.run(['git', 'add', '-A'], cwd=BASE_DIR, capture_output=True, timeout=30)
                _subprocess.run(['git', 'commit', '-m', f'AI self-edit: {old_text.strip()[:40]}'],
                                cwd=BASE_DIR, capture_output=True, timeout=30)
            except Exception:
                pass
            rollback = f'git reset --hard {base_hash}' if base_hash else '可用 backup/ 备份文件恢复'
            return f'✅ 已修改并提交（回滚：{rollback}）。请重启桌宠生效；若异常对我说"回滚桌宠修改"。'"""
new2 = """            # 4. 回滚保障（v6.42：不 git commit——E盘 commit 实测 60s+ 会卡死 AI；改后文件留为工作区改动，
            #    回滚用 git restore 直接从对象库恢复 HEAD 版本 + backup/ 文件双保险）
            rollback = f'git restore {fname}' if base_hash else '可用 backup/ 备份文件恢复'
            return f'✅ 已修改（回滚：{rollback} 或 backup/ 备份）。修改会在下次 git 提交时入库；请重启桌宠生效，若异常对我说"回滚桌宠修改"。'"""
assert old2 in src, '提交段未找到'
src = src.replace(old2, new2, 1)

io.open(DP, 'w', encoding='utf-8').write(src)
print('✅ 无 commit 版本完成')

import ast
ast.parse(src)
print('✅ 语法通过')
