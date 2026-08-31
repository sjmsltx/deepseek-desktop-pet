# -*- coding: utf-8 -*-
"""补：第 7 条实际两行替换"""
import io

PB = r'E:\ai工作站\desktop-pet\prompt_builder.py'
src = io.open(PB, 'r', encoding='utf-8').read()

old7 = ("+ '7. 若确需用 edit_own_code 改代码：先用 read_file 带 start_line/end_line 精确读目标行（输出带行号），'\n"
        "        '再用 start_line/end_line + new_text 按行替换，不要凭记忆写 old_text。\\n'")
new7 = ("+ '7. 若确需用 edit_own_code 改代码：先用 search_code 定位关键词所在文件与行号，再 read_file 带 start_line/end_line '\n"
        "        '精确读目标行（输出带行号），最后 edit_own_code 指定 file（目标模块名，默认 desktop_pet.py）+ start_line/end_line + new_text 按行替换。\\n'")
assert old7 in src, '第7条未找到'
src = src.replace(old7, new7, 1)

io.open(PB, 'w', encoding='utf-8').write(src)
print('✅ 第 7 条更新完成')

import ast
ast.parse(src)
print('✅ 语法通过')
