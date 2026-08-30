# -*- coding: utf-8 -*-
"""
code_checker.py — 代码质量检查层（P1/P2 模块化拆分）
====================================================
从 desktop_pet.py 拆出的纯函数：
- check_python_blocks：检查回复中 Python 代码块语法，返回 [(序号, 错误信息)]

模块化说明：无 UI 依赖，可独立单测。
"""
import os
import re
import tempfile


def check_python_blocks(text):
    """自动检查回复中 Python 代码块语法，返回 [(序号, 错误信息)]（v6.17 保证代码正确）"""
    blocks = re.findall(r'```python\s*\n(.*?)```', str(text), flags=re.S)
    bad = []
    for i, b in enumerate(blocks):
        if not b.strip():
            continue
        tmp = os.path.join(tempfile.gettempdir(), f'_pet_code_{i}.py')
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                f.write(b)
            import py_compile
            py_compile.compile(tmp, doraise=True)
        except Exception as e:
            msg = str(e).strip().splitlines()
            bad.append((i + 1, msg[-1] if msg else '语法错误'))
        finally:
            try:
                os.remove(tmp)
            except Exception:
                pass
    return bad
