# -*- coding: utf-8 -*-
"""v6.58 A2-2：主程序 / 卡片 / 关系面板主题化 + 生效主题中央通道

覆盖：
  1. `pet_theme` 的生效主题通道（set_active / color / subscribe）；
  2. 代码卡 / 表格卡跟随主题（apply_theme）；
  3. 关系面板 / 回忆相册的 QSS 由 token 生成；
  4. 宿主 `_apply_theme()` 会发布主题（源码护栏）；
  5. 四个 UI 模块零硬编码颜色。

运行：python -m pytest tests/test_host_theme.py -q
"""
import os
import re
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

HEX = re.compile(r'#[0-9a-fA-F]{3,8}\b')
RGBA = re.compile(r'\brgba?\s*\(')


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


def test_active_theme_channel():
    import pet_theme as pt
    pt.set_active({'panel_bg': '#010203'})
    assert pt.color('panel_bg') == '#010203'
    hit = []
    unsub = pt.subscribe(lambda: hit.append(1))
    pt.set_active({'panel_bg': '#040506'})
    assert hit == [1], '订阅者没被通知（主题变化不会触发重刷）'
    assert pt.active().get('panel_bg') == '#040506'
    unsub()
    pt.set_active(None)
    assert pt.color('panel_bg') == pt.DEFAULT_THEME['panel_bg'], '复位失败'


def test_cards_follow_theme():
    import pet_theme as pt
    from chat_cards import CodeCard, TableCard
    _app()
    code = CodeCard('print(1)')
    table = TableCard('|a|\n|-|\n|1|', '<table><tr><td>1</td></tr></table>')
    pt.set_active({'ui_code_bg': '#0ABC0A'})
    code.apply_theme()
    table.apply_theme()
    assert '#0ABC0A' in code.styleSheet(), '代码卡没有跟随主题'
    assert '#0ABC0A' in table.styleSheet(), '表格卡没有跟随主题'
    pt.set_active(None)


def test_dialog_qss_from_tokens():
    import pet_theme as pt
    import affection_ui as au
    pt.set_active({'ui_bg': '#0DEF0D'})
    assert '#0DEF0D' in au.memories_qss(), '回忆相册样式未走 token'
    assert '#0DEF0D' in au.relation_qss(), '关系面板样式未走 token'
    pt.set_active(None)


def test_host_publishes_theme():
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8-sig').read()
    assert 'pet_theme.set_active(self.theme)' in src, '宿主没有发布生效主题'
    j = src.index('def _apply_theme(')
    assert '_publish_theme()' in src[j:j + 900], '_apply_theme 里没有发布主题'
    k = src.index('def _open_games(')
    assert '_publish_theme()' in src[k:k + 600], '开小游戏窗口前没有先发布主题'


def test_ui_modules_have_no_hardcoded_colors():
    """A2 目标：产品 UI 模块零硬编码颜色"""
    for fn in ('pet_minigames.py', 'chat_cards.py', 'affection_ui.py',
               'pet_bubble.py', 'chat_render.py'):
        bad = []
        for i, line in enumerate(open(os.path.join(BASE, fn), encoding='utf-8-sig').read().splitlines(), 1):
            s = line.strip()
            if s.startswith('#') or 'theme-exempt' in line:
                continue
            if HEX.search(line) or RGBA.search(line):
                bad.append((i, s[:80]))
        assert not bad, f'{fn} 仍有硬编码颜色：{bad[:3]}'
