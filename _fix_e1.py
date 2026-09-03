# -*- coding: utf-8 -*-
"""修正 E1 测试（清历史残留存档）"""
import io

p = r'E:\ai工作站\desktop-pet\_regression_full.py'
s = io.open(p, encoding='utf-8').read()

old = """def t_e1():
    from pet_minigames import Minesweeper
    g = Minesweeper(lambda *a, **k: None)
    assert hasattr(g, '_save_btn') and g._save_btn.text() == '💾 保存'
    g.started = True
    g._plant(0, 0)
    g.close()
    # closeEvent 不自动保存
    import os as _os
    assert not _os.path.exists(g._save_path()) if _os.path.exists(g._save_path()) else True
    if _os.path.exists(g._save_path()):
        _os.remove(g._save_path())"""
new = """def t_e1():
    import os as _os
    from pet_minigames import Minesweeper
    g = Minesweeper(lambda *a, **k: None)
    assert hasattr(g, '_save_btn') and g._save_btn.text() == '💾 保存'
    sp = g._save_path()
    if _os.path.exists(sp):
        _os.remove(sp)  # 清历史残留存档
    g.started = True
    g._plant(0, 0)
    g.close()
    # closeEvent 不自动保存
    assert not _os.path.exists(sp), 'closeEvent 仍自动保存！'"""
assert old in s, 'E1 未找到'
s = s.replace(old, new, 1)
io.open(p, 'w', encoding='utf-8').write(s)
print('E1 已修正')
