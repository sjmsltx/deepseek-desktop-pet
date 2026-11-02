# -*- coding: utf-8 -*-
"""贴边状态下不该演动作（Owner 2026-11-01 报）

Owner 原话：
    「把它放处于贴边状态的时候它也会弹随机演演化动作的那个气泡，但是把它拖出来之后
      还是平常的待机图片，你把这个问题处理一下，既然都弹着气泡了那么用户看到肯定想
      把它拖出来看一看，要不然你就干脆不要在贴边状态之下也弹气泡。」

## 根因（本轮实测确认，不是猜）
贴边的真实标志是 `_edge_side is not None`（由 `_enter_dock()` 设置），
而我 2026-10-31 写的判断用的是 `_edge_docked` —— 那个属性**全仓只有初始化和
测试里出现，`_enter_dock` 从不设它** ⇒ 判断永远不生效。

实测：
    调 _enter_dock('left') 以后，_edge_side='left'、_edge_docked=False
    → _random_action_tick() **照样演动作** ✗

## 为什么上一版测试没抓到
`test_skipped_when_docked` 里写的是 `p._edge_docked = True` ——
手设了一个**真实代码从不产生的状态**。断言确实碰到了「_edge_docked 为真」这条路径，
但那条路径在现实里不存在 ⇒ 典型的**假绿**（断言没碰到真实路径）。

## 口径选择
Owner 给了两个选项：要么贴边时演了就让拖出来能看到，要么贴边时干脆不弹。
取后者：贴边时立绘被换成 peek 图（`_show_peek()`），演动作会和它打架，
用户看到「有气泡但立绘没动」本来就是个坏体验。
真正的原因是**根本不该在贴边时演**。

本文件锁六件事：
A. 真实进贴边（_enter_dock）后 tick 不演
B. 贴边但有气泡场景（_edge_popped=True）时也不演
C. 其他边（top/bottom/right）同样不演
D. 拖出贴边后恢复正常演
E. **测试不许手设 _edge_docked** —— 那个标志要么删掉，要么真的被维护
F. 贴边时不弹任何气泡（连"动作没演"的提示也不弹）
"""
import os
import sys

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

import desktop_pet as dp  # noqa: E402


def _pet(tmp_path):
    import affection_engine as ae
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p._append_chat = lambda *a, **k: None
    p.affection = ae.AffectionEngine(str(tmp_path / 'aff.json'))
    p.random_action_when = 'always'
    # ⚠ 2026-11-01 加固：_random_action_tick 有五个前置条件，逐个锁死「允许」。
    #   否则被前面测试污染时，断言会因为「另一个条件挡住了」而误红（实测踩到）。
    p.sleeping = False
    p._ai_busy = False
    p.bubble = None          # 气泡可见也会挡；测试只关心贴边这一个条件
    p._ra_calls = []
    p._bubbles = []
    p.random_action = lambda: p._ra_calls.append(1)
    p._show_pet_bubble = lambda t, *a, **k: p._bubbles.append(t)
    p.say_plain = lambda t, *a, **k: p._bubbles.append(t)
    p.show()
    _app.processEvents()
    return p


def _enter_edge(p, side='left'):
    """走真实的进入贴边路径（不是手设标志）"""
    p._enter_dock(side, p.y())
    _app.processEvents()
    # 断言前提：真的进入贴边了
    assert p._edge_side == side, '前提不成立：_enter_dock 之后 _edge_side=%r' % p._edge_side


def _leave_edge(p):
    """走**真实**的拖出路径 `_exit_dock_to_free()`，不手设属性

    ⚠ 2026-11-01：原先这里手设 `_edge_side = None`。那是"假拖出"——
      真实拖出还会恢复 chat_panel 高度、同步窗口到面板、恢复显示状态。
      手设属性等于测了一个用户操作不会产生的中间态（本轮第三次同类错误）。
    """
    p._exit_dock_to_free()
    _app.processEvents()


# ---------- A. 真实贴边不演 ----------
@pytest.mark.parametrize('side', ['left', 'right', 'top', 'bottom'])
def test_docked_by_real_path_does_not_fire(tmp_path, side):
    """走 _enter_dock 进贴边 —— 这才是用户真实触发的路径"""
    p = _pet(tmp_path)
    _enter_edge(p, side)
    p._random_action_tick()
    assert not p._ra_calls, '%s 边贴边状态下仍然演了动作' % side


def test_docked_does_not_bubble_even_hint(tmp_path):
    """贴边时连提示气泡都不弹 —— Owner：「干脆不要在贴边状态之下也弹气泡」"""
    p = _pet(tmp_path)
    _enter_edge(p)
    p._random_action_tick()
    assert not p._bubbles, '贴边状态下弹了气泡：%r' % (p._bubbles,)


# ---------- B. 贴边已弹出（_edge_popped）也不演 ----------
def test_docked_but_popped_does_not_fire(tmp_path):
    p = _pet(tmp_path)
    _enter_edge(p)
    p._edge_popped = True          # 鼠标悬停后弹出来的状态
    _app.processEvents()
    p._random_action_tick()
    assert not p._ra_calls, '贴边弹出状态下仍然演了动作'


# ---------- D. 拖出后恢复 ----------
def test_after_undock_it_fires_again(tmp_path):
    p = _pet(tmp_path)
    _enter_edge(p)
    p._random_action_tick()
    assert not p._ra_calls, '前提不成立：贴边时本不该演'

    _leave_edge(p)
    p._random_action_tick()
    assert len(p._ra_calls) == 1, '拖出贴边后应恢复正常演动作'


# ---------- E. 不许再手设那个假标志 ----------
def test_no_test_sets_edge_docked():
    """_edge_docked 是死标志：全仓只有初始化，没有任何代码把它设成 True

    谁在测试里手设它，就是在测一个现实中不存在的状态（上一版就是这么假绿的）。
    """
    import ast
    here = os.path.dirname(os.path.abspath(__file__))
    bad = []
    for fn in sorted(os.listdir(here)):
        if not (fn.startswith('test_') and fn.endswith('.py')):
            continue
        src = open(os.path.join(here, fn), encoding='utf-8').read()
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            for t in targets:
                if isinstance(t, ast.Attribute) and t.attr == '_edge_docked':
                    bad.append('%s:%d' % (fn, node.lineno))
    assert not bad, ('测试里手设了 _edge_docked —— 那是死标志，'
                     '真实代码从不为真。应改用 _enter_dock()。位置：%r' % bad)


def test_real_code_maintains_or_drops_edge_docked():
    """_edge_docked 要么被真实维护，要么删掉 —— 不许「保留但从不赋值」

    ⛔ 用 ast 判「代码里有没有对这个属性的访问」，
       不 grep 文本 —— 我第一版就是这么写的，被**注释里提到的名字**打成红。
       （同一个坑第四次：check_channel_ledger / test_no_log_pollution /
         test_recycle 的 docstring。）
    """
    import ast
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    tree = ast.parse(src)

    assigns_true = False
    touches = 0
    for node in ast.walk(tree):
        # 赋值：self._edge_docked = ...
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        elif isinstance(node, ast.AugAssign):
            targets = [node.target]
        for t in targets:
            if isinstance(t, ast.Attribute) and t.attr == '_edge_docked':
                touches += 1
                if isinstance(node.value, ast.Constant) and node.value.value is True:
                    assigns_true = True
        # 读取：getattr(self, '_edge_docked', ...)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == 'getattr' and len(node.args) >= 2:
            a1 = node.args[1]
            if isinstance(a1, ast.Constant) and a1.value == '_edge_docked':
                touches += 1

    if touches == 0:
        return                      # 已彻底删掉，符合要求
    assert assigns_true, (
        '_edge_docked 仍在被读写，但没有任何地方把它设成 True —— '
        '这是个会骗人的死标志：看着像判了贴边，实际永远为 False。'
        '要么真维护它，要么删掉改用 _edge_side。')



# ---------- G. 完整链路（本轮端到端实测固化的那条）----------
def test_full_chain_free_dock_undock(tmp_path):
    """自由 → 贴边 → 拖出：三步行为都要对

    走的是**用户真实会触发的路径**：
        贴边：窗口移到让「立绘左边界 <= 18」的位置 → _edge_dock_check()
              （注意贴边判断看的是 pet_label 位置，不是窗口 x ——
                我第一版量错了窗口坐标，结果窗口在 x=0 时立绘左边界其实是 90，够不到阈值）
        拖出：_exit_dock_to_free()（用户拖出时真实调用的就是它，
              不是 _edge_dock_check —— 那条只在「完全消失模式」里管退出）
    """
    p = _pet(tmp_path)

    # 1) 自由态：应该演
    p.move(400, 300)
    _app.processEvents()
    p._random_action_tick()
    assert len(p._ra_calls) == 1, '自由态没演动作'

    # 2) 贴到左边缘：不该演、不该弹
    p._ra_calls.clear()
    p._bubbles.clear()
    left = 18 - (p.width() - p.pet_size) // 2
    p.move(left, 300)
    _app.processEvents()
    p.dragging = False
    p._edge_dock_check()
    _app.processEvents()
    assert p._edge_side == 'left', '没进入贴边（前提不成立），实际 %r' % p._edge_side
    p._random_action_tick()
    assert not p._ra_calls, '贴边状态下演了动作'
    assert not p._bubbles, '贴边状态下弹了气泡'

    # 3) 拖出：恢复
    p._exit_dock_to_free()
    _app.processEvents()
    assert p._edge_side is None, '拖出后仍是贴边状态'
    p._random_action_tick()
    assert p._ra_calls, '拖出贴边后没恢复演动作'
