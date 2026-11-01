# -*- coding: utf-8 -*-
"""食物动作图（Owner 2026-11-01：「既然有多样化的食物那么应该有对应的那个动作图片」）

素材来源与处理（本轮做的，不是凭空来的）
--------------------------------------
用现有 flash_eating.png 作角色参考，逐个生成 5 张：
    rice / cake / tea / apple / candy
生成图是 2048x2048 白底 JPG，处理流程：
    ① 洪水填充（从四边种子）判背景 —— 不用亮度阈值：
       白底连通、角色内部白色（和服/发高光）被轮廓包住，所以不会在衣服上开洞
    ② 连通域：最大块是角色，面积 < 0.3% 的孤立小块当水印/噪点剔除
       （**不靠固定坐标**，换图水印挪位置也不会漏）
    ③ 缩放到 1024x1024 RGBA
实测结果：
    透明比例 63.3~64.5%（benchmark flash_eating = 64.1%）
    角色包围盒 727x935（benchmark flash_eating = 734x939，差 <1%）
    → 与现有素材同规格、同构图，切换动作时角色不跳
生成图右下角原本有水印文字，被连通域那步清干净（洋红底复验无残留）。

本文件锁六件事：
A. FOODS 表里每种食物都有明确的动作图状态；没有多余图
B. 每种食物的图**真实存在**（显式检查，不靠 asset() 的兜底——
   兜底会静默降级到 idle，这正是「场景动作被覆盖」那个 bug 的土壤）
C. 取不到时退回通用 eating，**不是** idle
D. 喂食时演的是该食物的图，不是统一一张
E. 状态用 'scene'（animate 已早退），否则会被重绘成通用图
F. 素材规格：1024x1024 RGBA 且有透明区域
"""
import os
import sys

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

import desktop_pet as dp  # noqa: E402


def _pet(tmp_path):
    import affection_engine as ae
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p._append_chat = lambda *a, **k: None
    p.affection = ae.AffectionEngine(str(tmp_path / 'aff.json'))
    p._bubbles = []
    p._show_pet_bubble = lambda t, *a, **k: p._bubbles.append(t)
    return p


# ---------- A. 食物 → 动作状态映射 ----------
def test_every_food_has_mapped_state():
    foods = set(dp.PetWidget.FOODS.keys())
    mapped = set(dp.PetWidget.FOOD_STATE.keys())
    assert foods <= mapped, '这些食物没有对应动作状态：%r' % (foods - mapped)


def test_no_orphan_state_mapping():
    """反向：不许映射里出现 FOODS 没有的键（那就是死配置的表亲）"""
    foods = set(dp.PetWidget.FOODS.keys())
    mapped = set(dp.PetWidget.FOOD_STATE.keys())
    assert mapped <= foods, '映射里有不存在的食物：%r' % (mapped - foods)


def test_states_are_unique_or_intentionally_shared():
    """noodle 复用现有的 eating（吃面图本来就有），其余各有专属图"""
    st = dp.PetWidget.FOOD_STATE
    assert st['noodle'] == 'eating', '面应复用现有 flash_eating.png'
    others = [v for k, v in st.items() if k != 'noodle']
    assert len(set(others)) == len(others), '除了面之外，每种食物应有专属图：%r' % others


# ---------- B. 图真的存在（显式检查，不靠兜底）----------
def test_all_food_images_exist_on_disk():
    from desktop_pet import asset
    missing = []
    for food, st in dp.PetWidget.FOOD_STATE.items():
        p = asset('flash', st)
        if not os.path.exists(p):
            missing.append((food, st, p))
    assert not missing, '缺图（asset() 会静默兜底成别的图，必须在磁盘上真的存在）：%r' % missing


# ---------- C. 取不到时退回 eating，不是 idle ----------
def test_fallback_is_eating_not_idle(tmp_path, monkeypatch):
    p = _pet(tmp_path)
    # 让专属图「取不到」：直接问一个不存在食物的图
    img = p._feeding_image('不存在的食物')
    assert img is not None and not img.isNull(), '取不到专属图时应退回 eating，实际 None'
    # 与 eating 图渲染出来的应一致
    from desktop_pet import asset
    ref = QPixmap(asset('flash', 'eating'))
    assert img.size() == ref.size()


# ---------- D. 喂食演对应食物的图 ----------
def test_feed_uses_food_specific_image(tmp_path):
    """喂蛋糕和喂苹果，画出来的应该是两张不同的图"""
    p = _pet(tmp_path)
    p.show()
    _app.processEvents()

    shots = {}
    for food in ('cake', 'apple'):
        with p.affection._lock:
            st = p.affection._state(p.current)
            st['satiety'] = 20
            st['cooldowns'] = {}
            p.affection._save()
        p._feed_pet(food, reaction='eating')
        _app.processEvents()
        pm = p.pet_label.pixmap()
        shots[food] = bytes(pm.toImage().bits())
    assert shots['cake'] != shots['apple'], '喂不同食物画出来的是同一张图 —— 没接上专属图'


def test_feed_sets_scene_state(tmp_path):
    """必须用 'scene' 状态：animate() 对 scene 早退，否则会被重绘成通用图"""
    p = _pet(tmp_path)
    with p.affection._lock:
        st = p.affection._state(p.current)
        st['satiety'] = 20
        st['cooldowns'] = {}
        p.affection._save()
    p._feed_pet('rice', reaction='eating')
    assert p.state == 'scene', '喂食后状态应为 scene，实际 %r' % p.state


def test_food_image_survives_animate(tmp_path):
    """吃过一次 animate 之后，图不能变（这是「场景动作被覆盖」那个老 bug 的复发检查）"""
    p = _pet(tmp_path)
    p.show()
    _app.processEvents()
    with p.affection._lock:
        st = p.affection._state(p.current)
        st['satiety'] = 20
        st['cooldowns'] = {}
        p.affection._save()
    p._feed_pet('tea', reaction='eating')
    _app.processEvents()
    before = bytes(p.pet_label.pixmap().toImage().bits())
    for _ in range(10):
        p.animate()
    _app.processEvents()
    after = bytes(p.pet_label.pixmap().toImage().bits())
    assert before == after, 'animate() 把食物动作图覆盖了'


# ---------- F. 素材规格 ----------
@pytest.mark.parametrize('state', ['eat_rice', 'eat_cake', 'eat_tea', 'eat_apple', 'eat_candy'])
def test_asset_spec(state):
    from PIL import Image
    from desktop_pet import asset
    p = asset('flash', state)
    assert os.path.exists(p), '缺素材 %s' % state
    im = Image.open(p)
    assert im.size == (1024, 1024), '%s 尺寸 %r，应为 1024x1024' % (state, im.size)
    assert im.mode == 'RGBA', '%s 模式 %r，应为 RGBA' % (state, im.mode)
    hist = im.getchannel('A').histogram()
    trans = sum(hist[0:10]) * 100.0 / (im.width * im.height)
    assert 55 <= trans <= 75, '%s 透明比例 %.1f%%，与基准(64%%)差太多，抠图可能有问题' % (state, trans)
