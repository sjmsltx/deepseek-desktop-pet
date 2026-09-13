# -*- coding: utf-8 -*-
"""小游戏冒烟测试（2026-09-13，桌宠收尾批 C4）

目的：15 款小游戏此前没有任何自动化覆盖。本测试在 offscreen 下逐款实例化并走一遍
关键路径（构造 → 难度切换 → 重开局 → 结算回调 → 存档协议往返），任何一款抛异常
都会被点名。

不做的事：不弹任何对话框（QMessageBox 已打桩）、不写存档文件（存档协议只做内存往返）。
用法：python tests/test_minigames_smoke.py
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402

# 打桩：所有模态对话框直接返回，不阻塞
for _name in ('information', 'warning', 'critical', 'question'):
    setattr(QMessageBox, _name, staticmethod(lambda *a, **k: QMessageBox.Ok))

app = QApplication.instance() or QApplication([])

import pet_minigames as mg  # noqa: E402

GAMES = ['RockPaperScissors', 'GuessNumber', 'Gomoku', 'Game2048', 'Minesweeper', 'Snake',
         'MemoryMatch', 'TicTacToe', 'Farkle', 'WhackAMole', 'Blackjack', 'Sudoku',
         'Tetris', 'SlidingPuzzle', 'SimonSays']

RESTART_CANDIDATES = ('_new_game', '_reset', '_restart', '_rebuild', '_deal', '_start')

RESULTS = []


def stop_timers(w):
    for t in w.findChildren(QTimer):
        try:
            t.stop()
        except Exception:
            pass


def run_one(name):
    cls = getattr(mg, name, None)
    assert cls is not None, ' pet_minigames 里没有类 %s' % name
    calls = []
    g = cls(lambda *a: calls.append(a))
    steps = []

    # 1. 基类属性：over / difficulty 由 BaseGame 提供
    assert hasattr(g, 'over'), '缺少 over 属性（应由 BaseGame 提供）'
    assert g.over is False, 'over 初值应为 False，实际 %r' % g.over
    assert hasattr(g, 'difficulty'), '缺少 difficulty 属性'
    steps.append('构造')

    # 1.5 最小尺寸契约（C6）：显示后最小尺寸不得低于布局建议尺寸
    #     注：这是**契约式断言**（守住以后的改动），不是"修复了用户可感知缺陷"——
    #     对照实验显示修复前后窗口可缩下限一致（Qt 本就按布局设置最小尺寸）。
    g.show()
    hint_w, hint_h = g.sizeHint().width(), g.sizeHint().height()
    assert g.minimumWidth() >= hint_w and g.minimumHeight() >= hint_h, \
        '最小尺寸低于布局建议尺寸：min=(%d,%d) hint=(%d,%d)' % (g.minimumWidth(), g.minimumHeight(), hint_w, hint_h)
    steps.append('最小尺寸契约')

    # 2. 难度切换（遍历该游戏声明的所有档位）
    d = getattr(g, '_difficulties', {}) or {}
    combo = getattr(g, '_combo', None)
    for label in list(d.keys()):
        if combo is not None:
            combo.setCurrentText(label)
        g._apply_difficulty()
        assert g.difficulty is not None or len(d) == 0, '难度切换后 difficulty 仍为 None'
    steps.append('难度×%d' % len(d))

    # 3. 重开局（各游戏方法名不同，取第一个存在的）
    restarted = False
    for cand in RESTART_CANDIDATES:
        fn = getattr(g, cand, None)
        if callable(fn):
            try:
                fn()
                restarted = True
                break
            except TypeError:
                continue
    steps.append('重开局' + ('' if restarted else '（无入口，跳过）'))

    # 4. 存档协议：内存往返，不落盘
    #    先区分「子类未实现」与「已实现但当前无进度（未开局）」，后者要真的走一遍往返
    overrides = getattr(cls, '_state_to_save', None) is not getattr(mg.BaseGame, '_state_to_save', None)
    data = g._state_to_save()
    if data is None and overrides:
        # 尝试把对局开起来（各游戏入口不同；失败不视为测试失败，但会在步骤里注明）
        starters = (('_on_click', lambda fn: fn(0, 0, False)),
                    ('_reveal', lambda fn: fn(0, 0)),
                    ('_start_game', lambda fn: fn()),
                    ('_new_game', lambda fn: fn()))
        for attr, call in starters:
            fn = getattr(g, attr, None)
            if not callable(fn):
                continue
            try:
                call(fn)
            except Exception:
                continue
            data = g._state_to_save()
            if data is not None:
                break
    if data is not None:
        assert isinstance(data, (dict, list)), '存档数据应为可序列化结构，实际 %s' % type(data)
        g2 = cls(lambda *a: None)
        g2._state_from_save(data)
        stop_timers(g2)
        g2.close()
        steps.append('存档往返')
    elif overrides:
        steps.append('存档已实现但无进度（未开局）')
    else:
        steps.append('存档未实现（符合预期）')

    # 5. 结算回调
    #    注意：部分游戏（如 Blackjack 发牌即爆牌）可能在前面步骤就已自动结算并 close()，
    #    此时 _closed 会让显式结算直接返回。这里重置该守卫，以确定性验证「结算回调」这条路。
    calls.clear()
    if hasattr(g, '_closed'):
        g._closed = False
    g.over = False
    g._finish(True, '冒烟测试结算', 7)
    assert calls, '结算后未触发 on_result 回调'
    got = [tuple(c[:3]) for c in calls]
    assert (True, 7, name) in got, '显式结算未被回调：%r' % (got,)
    assert all(c[2] == name for c in got if len(c) >= 3), '回调里的游戏名不符：%r' % (got,)
    steps.append('结算回调')

    stop_timers(g)
    g.close()
    return steps


def main():
    print('===== 小游戏冒烟测试 =====')
    for name in GAMES:
        try:
            steps = run_one(name)
            RESULTS.append((name, 'PASS', ' → '.join(steps)))
            print('  ✅ %-18s %s' % (name, ' → '.join(steps)))
        except Exception as e:
            RESULTS.append((name, 'FAIL', str(e)[:150]))
            print('  ❌ %-18s %s' % (name, str(e)[:150]))

    total = len(RESULTS)
    fail = [r for r in RESULTS if r[1] == 'FAIL']
    print('\n小游戏冒烟：%d 款 / PASS %d / FAIL %d' % (total, total - len(fail), len(fail)))
    print('结果：%s' % ('全部通过 ✅' if not fail else '存在失败 ❌'))
    for n, _, e in fail:
        print('   ❌ %s: %s' % (n, e))
    return 1 if fail else 0


if __name__ == '__main__':
    sys.exit(main())
