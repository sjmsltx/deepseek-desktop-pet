# -*- coding: utf-8 -*-
"""重测：跨模块修改（锚点用文件第一行）"""
import os

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtWidgets import QApplication, QMessageBox
QMessageBox.information = staticmethod(lambda *a, **k: None)
app = QApplication([])

import desktop_pet
w = desktop_pet.PetWidget()
w.ai_enabled = False

# 修改 memory_engine.py 第一行（加注释标记）
marker = '# v6.41 跨模块修改测试\n'
old_txt = '# -*- coding: utf-8 -*-'
new_txt = marker + '# -*- coding: utf-8 -*-'
r = w._edit_own_code(old_text=old_txt, new_text=new_txt, file='memory_engine.py')
print('修改结果:', r[:120])
src = open('memory_engine.py', encoding='utf-8').read()
if marker in src:
    src = src.replace(marker, '')
    open('memory_engine.py', 'w', encoding='utf-8').write(src)
    print('✅ 跨模块修改生效（memory_engine.py），已还原')
else:
    print('⚠️ 未生效:', r[:150])

# 语法验证保护：改出语法错误应被拒绝
r2 = w._edit_own_code(old_text='# -*- coding: utf-8 -*-', new_text='def broken(:', file='memory_engine.py')
print('语法错误拦截:', '语法验证失败' in r2, '|', r2[:60])
app.quit()
print('验证完成')
