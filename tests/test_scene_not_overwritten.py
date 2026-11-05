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
import time

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


def _pet_not_hungry(tmp_path):
    """实例的饱食度固定为「饱」（100）且 last_sat_time=现在

    ⚠ 2026-11-01：`satiety()` 是按 last_sat_time **动态衰减**算的
      （存档 100，每 0.139 分掉 1 点）。原来这些测试直接用真实 affection.json，
      一旦距上次喂食超过约 5 小时，实时饱食度就掉到 30 以下，
      `_end_scene` 会正确地回到 'hungry'（产品设计：饿了常显），
      于是「场景结束回 idle」这条断言就红 —— 那是**测试依赖真实数据**，不是 bug。
      实测：2026-11-01 19:50 时衰减到 23.0。
      这里用临时文件 + 固定饱食度，把前提钉死，跟真实存档解耦。
    """
    import affection_engine as ae
    p = _pet()
    p.affection = ae.AffectionEngine(str(tmp_path / 'aff.json'))
    with p.affection._lock:
        st = p.affection._state(p.current)
        st['satiety'] = 100
        st['last_sat_time'] = time.time()
        p.affection._save()
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
def test_scene_ends_back_to_idle(tmp_path):
    p = _pet_not_hungry(tmp_path)
    p.play_scene('eating')
    _app.processEvents()
    p._end_scene()          # 模拟 6 秒到点
    _app.processEvents()
    assert p.state == 'idle', '场景结束后没回 idle，实际 %r' % p.state


def test_scene_ends_to_hungry_when_hungry(tmp_path):
    """对照：饿的时候场景结束**应该**回 hungry（Owner 2026-09-23 裁定：饿了常显）

    ⛔ 有这一条才不会有人为了「让上一条变绿」去去掉饥饿回退 ——
       那是产品行为，不该为了测试让步。
    """
    import affection_engine as ae
    p = _pet()
    p.affection = ae.AffectionEngine(str(tmp_path / 'aff2.json'))
    with p.affection._lock:
        st = p.affection._state(p.current)
        st['satiety'] = 5
        st['last_sat_time'] = time.time()
        p.affection._save()
    p.play_scene('eating')
    _app.processEvents()
    p._end_scene()
    _app.processEvents()
    assert p.state == 'hungry', '饿着的时候场景结束却没回 hungry，实际 %r' % p.state


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


# ═══ E. 加载失败不许被缓存永久化（2026-11-05，评审-180 ⑤）═══
# 外部评审指出 + 我实测坐实：`self.scene_imgs[key] = QPixmap(pth)` 没检查 isNull()，
# 于是一次瞬时加载失败会让 `key in self.scene_imgs` 恒为 True ⇒ 文件修好也不再重读 ⇒
# **该场景动作在本次会话内永久失效，要重启桌宠**。
# 实测（改前）：第 1 次 isNull=True 已入缓存 → 换成合法 PNG → 第 2 次仍 isNull=True。


def test_null_pixmap_is_not_cached(monkeypatch, tmp_path):
    """坏文件读成 null 时不许入缓存 —— 否则一次失败永久失效"""
    bad = tmp_path / 'bad.png'
    bad.write_bytes(b'not a png at all')

    p = _pet()
    monkeypatch.setattr(dp, 'asset', lambda role, key, *a, **k: str(bad))
    got = p._get_scene_img('eating')

    assert 'eating' not in p.scene_imgs, (
        'null 结果被写进缓存了 —— 文件修好后也不会重读')
    assert got is None or got.isNull(), '坏文件居然读出了非 null 图'


def test_recovers_after_transient_load_failure(monkeypatch, tmp_path):
    """★ 核心回归：第一次加载失败，文件修好后必须能读到（不许永久失效）"""
    from PySide6.QtGui import QPixmap

    p = _pet()
    # 找一张真实存在的图当「修好后的文件」
    good_src = dp.asset(p.current, 'eating')
    assert os.path.exists(good_src), '找不到 eating 素材，测试前提不成立：%s' % good_src

    target = tmp_path / 'flaky.png'
    target.write_bytes(b'broken')                       # 先坏
    monkeypatch.setattr(dp, 'asset', lambda role, key, *a, **k: str(target))

    first = p._get_scene_img('eating')
    assert first is None or first.isNull(), '第一次应失败'

    # 修好文件（复制真图过来）
    with open(good_src, 'rb') as f:
        data = f.read()
    target.write_bytes(data)
    assert not QPixmap(str(target)).isNull(), '夹具没修好'

    second = p._get_scene_img('eating')
    assert second is not None and not second.isNull(), (
        '文件已修好但没重读 —— null 被粘在缓存里了（这正是缺陷本身）')


def test_all_real_scene_assets_load():
    """所有登记的场景键都能加载出非 null 图（防止素材漏配 + 防我改坏加载逻辑）"""
    p = _pet()
    keys = list(getattr(dp, 'SCENE_ACTIONS', {}) or {})
    assert keys, 'SCENE_ACTIONS 为空，测试前提不成立'
    # ⚠ 2026-11-05（评审-181 ②）：只判「能读出非 null」是**假锁** ——
    #   `asset()` 对未知键会层层兜底到 `{role}_idle.png`，所以**真删掉 flash_eating.png
    #   这条测试仍会绿**（读出来的是待机图）。这和 `>= 400` 是同一类：
    #   断言区分不了「素材在」与「兜底成功」。
    #   ⇒ 先判**专属文件在不在**，再判能不能读。
    missing = []
    bad = []
    for k in keys:
        exact = os.path.join(dp.ASSETS, p.current, '%s_%s.png' % (p.current, k))
        if not os.path.exists(exact):
            missing.append(k)
        img = p._get_scene_img(k)
        if img is None or img.isNull():
            bad.append(k)
    assert not missing, '这些场景键没有专属素材（会静默兜底成待机图）：%r' % missing
    assert not bad, '这些场景键加载不出图：%r（共 %d 个键）' % (bad, len(keys))

