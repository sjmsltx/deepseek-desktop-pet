# -*- coding: utf-8 -*-
"""v6.58 A2-1：小游戏主题化回归测试

背景：15 款小游戏的配色原先全部写死在 `pet_minigames.py`（55 处），完全不随主题变化——
用户把主题换成浅色后，只有聊天面板变了，一进小游戏还是深色。

本测试锁住：
  1. 该文件**不再有硬编码颜色**（应为 0，token 兜底色除外）；
  2. `T()` 取色随 `set_theme()` 变化；
  3. 全部游戏类都能构造，且样式表里不出现"缺键兜底"的洋红；
  4. 已打开的游戏窗口 / 列表页会随切主题自动重刷。

运行：python -m pytest tests/test_minigames_theme.py -q
"""
import os
import re
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

HEX = re.compile(r'#[0-9a-fA-F]{3,8}\b')
RGBA = re.compile(r'\brgba?\s*\(')
MAGENTA = '#ff00ff'      # T() 的缺键兜底色


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


def test_no_hardcoded_colors_left():
    """55 处字面量应已全部搬到 pet_theme；只剩 T() 的兜底色（带 theme-exempt）"""
    path = os.path.join(BASE, 'pet_minigames.py')
    bad = []
    for i, line in enumerate(open(path, encoding='utf-8').read().splitlines(), 1):
        s = line.strip()
        if s.startswith('#') or 'theme-exempt' in line:
            continue
        if HEX.search(line) or RGBA.search(line):
            bad.append((i, s[:90]))
    assert not bad, 'pet_minigames.py 仍有硬编码颜色：%s' % bad[:5]


def test_T_follows_theme():
    import pet_minigames as mg
    from pet_theme import DEFAULT_THEME
    mg.set_theme({'ui_bg': '#123456'})
    assert mg.T('ui_bg') == '#123456', 'T() 没有跟随主题快照'
    mg.set_theme(None)                       # 复位
    assert mg.T('ui_bg') == DEFAULT_THEME['ui_bg'], 'T() 复位失败'


def test_all_games_construct_with_themed_styles():
    import pet_minigames as mg
    app = _app()
    mg.set_theme(None)
    assert len(mg.GAMES) >= 10, '游戏数量异常：%d' % len(mg.GAMES)
    for name, cls in mg.GAMES.items():
        try:
            w = cls(lambda *a, **k: None)
        except Exception as e:
            raise AssertionError('%s 构造失败：%s' % (name, e))
        ss = w.styleSheet() or ''
        assert ss, '%s 没有样式表（基类主题化可能被破坏）' % name
        assert MAGENTA not in ss, '%s 命中了缺键兜底色（有 token 漏配）' % name
        w.close()
        w.deleteLater()
    app.processEvents()


def test_open_game_refreshes_on_theme_change():
    """已打开的游戏窗口要在切主题时换色（refresh_open 生效）"""
    import pet_minigames as mg
    app = _app()
    mg.set_theme(None)
    cls = list(mg.GAMES.values())[0]
    w = cls(lambda *a, **k: None)
    w.show()
    app.processEvents()
    mg.set_theme({'ui_bg': '#0a0b0c'})
    app.processEvents()
    assert '#0a0b0c' in w.styleSheet(), '切主题后已打开的游戏窗口没有重刷样式'
    w.close()
    mg.set_theme(None)


def test_game_list_window_themed():
    import pet_minigames as mg
    app = _app()
    mg.set_theme({'ui_bg': '#0a0b0c'})
    gw = mg.GameWindow(lambda *a, **k: None)
    assert '#0a0b0c' in gw.styleSheet(), '小游戏列表页没有接入主题'
    gw.close()
    mg.set_theme(None)
