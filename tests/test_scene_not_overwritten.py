# -*- coding: utf-8 -*-
"""场景动作被 animate() 立刻覆盖回待机（Owner 2026-10-31 实测发现）

## 现象
面板展开时随机动作触发了（气泡显示了动作台词，如「慵懒趴地翘脚」），
但立绘不变 —— 看上去还是待机图。

## 根因（本轮实测确认，不是猜）

    play_scene(key):
        w.state = 'scene'
        w._render_frame(img)        # ← 动作图正确画上去了
        w.say_plain(info[1][:10])   # ← 气泡台词，Owner 看到的就是这个

    animate()（动画定时器，高频）:
        if self.state == 'idle' or self.sleeping or self.dragging:
            return                  # ← 'scene' 不在这个 return 条件里！
        ...
        self._render_frame(self._get_state_img(self.state), dx=dx)
                                    # ← _get_state_img('scene')
                                    #    asset() 对未知 key 兜底到 {role}_idle.png
                                    #    ⇒ 用**待机图**重绘了一遍 ⇒ 动作图被覆盖

## 实测（本轮）
    待机                hash=aa47156e98
    play_scene 之后立刻  hash=4c903b3003   ← 动作图
    animate() 跑一次后   hash=3a0f51134f   ← 被改掉（≠ 动作图）
    _get_state_img('scene') 返回 QPixmap（其实是 idle 兜底图）

## 性质
**这是老 bug，不是我本轮引入的。** 任何场景动作（右键菜单「🎲 随机动作」那条路）
都会在几十毫秒内被覆盖 —— 只是没人盯着看，所以一直没被发现。
Owner 这次看出来了，因为他现在有自动触发能反复观察。

## 修法（最小）
animate() 把 'scene' 和 'idle' 一样早退：场景动作是**静态图定格 6 秒**，
本来就不该摆头；摆头还会把动作图重绘成别的图（这次就是 idle）。

本文件锁四件事：
A. scene 状态下 animate() 不改立绘
B. scene 状态仍是 6 秒后自动回待机（收尾不能坏）
C. 其他状态（thinking/happy…）的摆头行为不受影响
D. _get_state_img('scene') 这种兜底不能再被拿来当「当前状态图」用
"""
import hashlib
import os
import sys

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

import desktop_pet as dp  # noqa: E402


def _pet():
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p._append_chat = lambda *a, **k: None
    p.show()
    _app.processEvents()
    return p


def _hash(p):
    img = p.pet_label.pixmap().toImage()
    return hashlib.sha256(bytes(img.bits())).hexdigest()[:12]


# ---------- A. 核心：scene 下 animate 不许改图 ----------
def test_animate_does_not_overwrite_scene():
    p = _pet()
    p.play_scene('eating')
    _app.processEvents()
    h_scene = _hash(p)
    assert p.state == 'scene', '前提变了：play_scene 后 state 不是 scene'
    for _ in range(5):
        p.animate()
    _app.processEvents()
    assert _hash(p) == h_scene, (
        'animate() 把动作图覆盖了 —— 这正是 Owner 看到「冒了气泡但动作没变」的原因')


def test_scene_image_differs_from_idle():
    """先证明「动作图 ≠ 待机图」，否则上一条断言可能是假绿"""
    p = _pet()
    h_idle = _hash(p)
    p.play_scene('eating')
    _app.processEvents()
    assert _hash(p) != h_idle, '吃东西的动作图和待机图一样 —— 素材或渲染有问题'


# ---------- B. 收尾不能坏 ----------
def test_scene_ends_back_to_idle():
    p = _pet()
    has_anim = True
    p.play_scene('eating')
    _app.processEvents()
    p._end_scene()          # 模拟 6 秒到点
    _app.processEvents()
    assert p.state == 'idle', '场景结束后没回 idle，实际 %r' % p.state


# ---------- C. 其他状态的摆头不受影响 ----------
@pytest.mark.parametrize('st', ['thinking', 'happy'])
def test_other_states_still_animate(st):
    p = _pet()
    p.state = st
    before = _hash(p)
    for _ in range(6):
        p.animate()
    _app.processEvents()
    # 摆头会让图像变化（dx 偏移）；不变说明 animate 被过度早退了
    assert _hash(p) != before, '%s 状态的摆头被误伤了（图像一直不变）' % st


# ---------- D. 不许再把兜底图当状态图 ----------
def test_get_state_img_scene_is_not_used_as_state_render():
    """`_get_state_img('scene')` 会回退到 idle 图 —— 任何人拿它重绘都是错的

    这条锁的是「别再有人写出 animate() 那种用法」：
    断言 animate 的源码里，对 scene 是早退，而不是去取状态图。
    """
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    i = src.find('def animate(')
    assert i > 0
    j = src.find('\n    def ', i + 10)
    body = src[i:j]
    assert "'scene'" in body, 'animate() 里没有对 scene 的处理'
    # scene 必须出现在「早退」里，且在 _render_frame 之前
    k_scene = body.find("'scene'")
    k_render = body.find('_render_frame')
    assert k_scene < k_render, 'scene 的判断写在了重绘之后，等于没挡'
