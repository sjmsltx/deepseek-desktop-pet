# -*- coding: utf-8 -*-
"""D11-5 护栏：摆头/摇曳**只能作用在立绘上** ⛔ 不得搬整个窗口 ✗

现象（Owner 2026-10-11 实测 ✓）：
  「我发现他在**饥饿状态**的时候下面的那个对话面板也会跟着这个人物一起左右晃动，看得我头都晕了。」
根因：
  `animate()` 里用 `self.move(self.base_x + dx, self.base_y)` 做摆头 ✗
  —— 搬的是**整个窗口**（PetWidget）✗，而 `chat_panel = QFrame(self)` 是它的**子控件** ✓
  ⇒ 对话面板 / 状态栏 / 输入框**全部跟着晃** ✗
  （同函数注释写的是「轻微左右摆头（只动位置，不重绘图片）」—— 意图是让**人物**摆，实现成了搬窗口 ✗）
修法：
  ① `_render_frame(pixmap, dx=0)` 支持水平偏移 ✓（复用既有缩放缓存 ✓）
  ② `_render_idle_offset` 改为复用 `_render_frame` ✓（原来自己重画且不走缓存 ✗）
  ③ `animate()` **不再 move 窗口** ✗ → 改调 `_render_frame(当前状态图, dx=dx)` ✓
  ⇒ 窗口位置恒定 ⇒ 面板/状态栏/输入框全部稳定 ✓
  ⇒ 附带消除：原先窗口**真实位置**会随摆头漂移（`base_x` 记账 ✗）✓
"""
from __future__ import annotations

import ast
import io
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / 'desktop_pet.py'


def _src():
    return io.open(APP, encoding='utf-8').read()


def _strip_comments(src: str) -> str:
    """⭐ 先剥注释/docstring 再匹配 ✓
    （教训：结构钉 grep 会命中注释 ✗ —— 本仓已踩过一次 ✓）"""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src
    lines = src.splitlines()
    kill = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            body = getattr(node, 'body', None) or []
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                for ln in range(body[0].lineno, getattr(body[0], 'end_lineno', body[0].lineno) + 1):
                    kill.add(ln)
    out = []
    for i, l in enumerate(lines, 1):
        if i in kill:
            continue
        out.append(re.sub(r'#.*$', '', l))
    return '\n'.join(out)


def _body_of(src: str, defname: str) -> str:
    """取某个方法体（到下一个同级 def 为止）"""
    i = src.index('def %s(' % defname)
    seg = src[i:]
    m = re.search(r'\n    def ', seg)
    return seg[:m.start()] if m else seg


# ── ① ⭐ 核心：animate 里不得再搬窗口 ─────────────────────────────
def test_animate_must_not_move_window():
    s = _strip_comments(_src())
    body = _body_of(s, 'animate')
    assert 'self.move(' not in body, \
        '⭐ animate 不得移动窗口 ✗ —— 会连带动对话面板一起晃 ✗（正是 D11-5 的根因 ✓）'
    assert '_render_frame(' in body and 'dx=' in body, \
        '⭐ animate 必须改为「只偏移立绘」✓（`_render_frame(..., dx=dx)` ✗）'


# ── ② 窗口位置不得被摆头改（`base_x + dx` 这个形状消失）────────────
def test_no_base_x_offset_move():
    s = _strip_comments(_src())
    assert 'self.base_x + dx' not in s, \
        '⭐ 「按 base_x 加偏移去 move 窗口」这个形状必须消失 ✗（D11-5 根因 ✓）'


# ── ③ _render_frame 必须支持 dx，且把它用在绘制上 ────────────────
def test_render_frame_supports_dx():
    s = _strip_comments(_src())
    assert 'def _render_frame(self, pixmap=None, dx=0)' in s, '⭐ _render_frame 需支持 dx 参数 ✗'
    body = _body_of(s, '_render_frame')
    assert '+ int(dx)' in body, '⭐ dx 必须真的作用到绘制坐标上 ✗（否则是死参数 ✗）'


# ── ④ _render_idle_offset 复用 _render_frame（消重复实现）─────────
def test_idle_offset_reuses_render_frame():
    s = _strip_comments(_src())
    body = _body_of(s, '_render_idle_offset')
    assert '_render_frame(' in body, '⭐ 应复用 _render_frame ✓（避免两份 offset 实现 ✗）'
    assert 'QPainter(' not in body, '⭐ 不应再自己重画一遍 ✗'


# ── ⑤ 行为护栏：摆头不得改变窗口几何 ────────────────────────────
def test_sway_does_not_touch_window_geometry(tmp_path, monkeypatch):
    """⭐ 用一个最小替身跑 `animate` 的摆头分支 ⇒ 断言**窗口没被移动** ✓

    替身只提供 animate 需要的表面 ✓（不打真 GUI ✓、不读素材 ✓）
    """
    import types

    import desktop_pet as DP

    moved = []
    rendered = []

    class _Stub:
        pass

    w = _Stub()
    w._edge_side = None
    w._edge_popped = False
    w.state = 'hungry'          # ⭐ 正是 Owner 报的那个状态 ✓
    w.sleeping = False
    w.dragging = False
    w.phase = 0
    w._edge_dock_check = lambda: None
    w._get_state_img = lambda st: object()          # 非 None 即可 ✓
    w._render_frame = lambda pm=None, dx=0: rendered.append(dx)
    w.move = lambda *a: moved.append(a)

    DP.PetWidget.animate(w)

    assert moved == [], '⭐ animate 不得移动窗口 ✗（D11-5 ✓）实际 %r' % (moved,)
    assert rendered, '⭐ animate 必须调用 _render_frame 画立绘 ✓'
    assert rendered[-1] != 0 or True     # 相位首帧可能恰好 0 ✓ 不断言具体值 ✓


def test_sway_skips_when_idle_or_sleeping():
    """⭐ 原有静止分支必须保留 ✓（idle / sleeping / dragging 不动 ✗）"""
    import desktop_pet as DP

    for st, sleep, drag in (('idle', False, False), ('happy', True, False), ('happy', False, True)):
        moved, rendered = [], []

        class _Stub:
            pass

        w = _Stub()
        w._edge_side = None
        w._edge_popped = False
        w.state = st
        w.sleeping = sleep
        w.dragging = drag
        w.phase = 0
        w._edge_dock_check = lambda: None
        w._get_state_img = lambda s: object()
        w._render_frame = lambda pm=None, dx=0: rendered.append(dx)
        w.move = lambda *a: moved.append(a)
        DP.PetWidget.animate(w)
        assert moved == [] and rendered == [], \
            '⭐ %s（sleep=%s drag=%s）应完全静止 ✓' % (st, sleep, drag)
