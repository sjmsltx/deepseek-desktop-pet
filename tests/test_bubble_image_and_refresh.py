# -*- coding: utf-8 -*-
"""图片倍率 + 星图自动刷新 的回归测试

A 图片：Owner 实测「相当之糊」—— 原来 bubble.grab() 只出逻辑像素（360x98）。
   3 种高倍方案实测只有 render(QPaintDevice)+dpr 有效：
      A_render_device  非背景 55.4%（与 1x 的 55.7% 一致 ⇒ 真按 3x 渲染）
      B_painter_scale  非背景  3.3%（缩放没生效）
      C_smooth_upscale 非背景  8.7%（等于糊图）
   本测试锁「出图像素 = 逻辑 × 倍率」，这正是清晰度的必要条件。

B 星图：原来只在打开时读一次盘，窗口开着永远是旧数据。
"""
import json
import os
import sys
import time

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PySide6.QtWidgets import QApplication  # noqa: E402

import memory_events as me  # noqa: E402
import memory_starmap as sm  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)


# ---------------- A. 图片倍率 ----------------
def _bubble_pet():
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p.show()
    _app.processEvents()
    txt = ('好呀，那我们先把你说的那条记忆整理一下：第一，确认它是不是可重算的；'
           '第二，确认它该进哪一层。你觉得呢？')
    bubble, content = p._new_bubble('小蓝', '18:20', False, txt)
    content.addWidget(p._bubble_text_label(txt, is_user=False))
    bubble.setFixedWidth(360)
    for _ in range(4):
        _app.processEvents()
        bubble.adjustSize()
    return p, bubble


def test_bubble_image_is_high_resolution():
    """出图像素必须是 逻辑尺寸 × 倍率（原实现等于 1x，这是糊的根因）"""
    p, bubble = _bubble_pet()
    pm = p._render_bubble_pixmap(bubble)
    assert pm is not None
    s = int(p.BUBBLE_IMAGE_SCALE)
    assert s >= 2, '倍率至少 2x，否则贴进文档会糊'
    assert pm.devicePixelRatio() == float(s)
    expect_w, expect_h = bubble.width() * s, bubble.height() * s
    assert pm.width() == expect_w, '出图宽 %d 应为 %d' % (pm.width(), expect_w)
    assert pm.height() == expect_h, '出图高 %d 应为 %d' % (pm.height(), expect_h)


def test_bubble_image_content_actually_rendered():
    """不能是空白：必须有足够多的非背景像素（防「尺寸对了但内容是空」）"""
    p, bubble = _bubble_pet()
    pm = p._render_bubble_pixmap(bubble)
    img = pm.toImage()
    bg = (20, 20, 30)
    total = img.width() * img.height()
    non_bg = 0
    step = 3
    sampled = 0
    for y in range(0, img.height(), step):
        for x in range(0, img.width(), step):
            c = img.pixelColor(x, y)
            sampled += 1
            if (c.red(), c.green(), c.blue()) != bg:
                non_bg += 1
    ratio = non_bg / max(1, sampled)
    assert ratio > 0.30, '非背景占比仅 %.1f%%，内容可能没画出来' % (ratio * 100)


def test_bubble_image_scale_override():
    p, bubble = _bubble_pet()
    pm1 = p._render_bubble_pixmap(bubble, scale=1)
    pm2 = p._render_bubble_pixmap(bubble, scale=2)
    assert pm1.width() * 2 == pm2.width()
    assert pm1.height() * 2 == pm2.height()


def test_bubble_image_scale_clamped():
    p, bubble = _bubble_pet()
    pm = p._render_bubble_pixmap(bubble, scale=99)
    assert pm.devicePixelRatio() <= 6.0, '倍率未夹取，可能炸内存'


# ---------------- B. 星图自动刷新 ----------------
@pytest.fixture()
def tmp_maps(tmp_path):
    mp = str(tmp_path / 'memory.json')
    ep = str(tmp_path / 'memories.json')
    with open(mp, 'w', encoding='utf-8') as f:
        json.dump({'facts': [{'content': '测试事实一', 'importance': 3,
                              'status': 'active', 'roles': 'both', 'id': 'a1'}],
                   'summaries': []}, f, ensure_ascii=False)
    with open(ep, 'w', encoding='utf-8') as f:
        json.dump([], f)
    return mp, ep


def _map(mp, ep):
    stars, dead, raw = sm.load_stars(mp, ep)
    w = sm.MemoryStarMap(stars=stars, dead=dead, raw_events=raw,
                         facts_path=mp, events_path=ep)
    w.resize(900, 620)
    w.show()
    _app.processEvents()
    return w


def test_reload_picks_up_new_memory(tmp_maps):
    mp, ep = tmp_maps
    w = _map(mp, ep)
    assert len(w.stars) == 1
    time.sleep(1.05)          # 让 mtime 真的变化（文件系统时间粒度）
    ev = me.MemoryEvents(ep)
    ev.add('flash', 'event', '新发生：一起看了流星雨', '')
    w._maybe_reload()
    assert len(w.stars) == 2, '写盘后星图没自动更新：%d' % len(w.stars)
    assert any('流星雨' in s['text'] for s in w.stars)


def test_reload_clears_stale_layout(tmp_maps):
    """新数据必须重排布局，否则会接着用旧坐标画"""
    mp, ep = tmp_maps
    w = _map(mp, ep)
    old_keys = set(w._layout)
    time.sleep(1.05)
    ev = me.MemoryEvents(ep)
    ev.add('flash', 'event', '另一件事', '')
    w._maybe_reload()
    assert w._layout == {}, '重载后应清空布局缓存（布局是懒计算的）'
    w._compute_layout()          # 等价于下一次 paintEvent
    assert set(w._layout) != old_keys, '布局未随新数据重算'
    assert len(w._layout) == len(w.stars)


def test_no_reload_when_files_unchanged(tmp_maps):
    mp, ep = tmp_maps
    w = _map(mp, ep)
    before = dict(w._layout)
    w._maybe_reload()
    assert w._layout == before, '文件没变却重排了（会白抖一下）'


def test_reload_uses_instance_paths(tmp_maps):
    """刷新必须读实例自己的文件，不能回落到仓库默认路径"""
    mp, ep = tmp_maps
    w = _map(mp, ep)
    assert w._facts_path == mp and w._events_path == ep
    src = open(os.path.join(BASE, 'memory_starmap.py'), encoding='utf-8').read()
    assert 'load_stars(self._facts_path, self._events_path)' in src, \
        'reload 没使用实例路径'


def test_auto_timer_is_running(tmp_maps):
    mp, ep = tmp_maps
    w = _map(mp, ep)
    assert w._auto_timer.isActive(), '自动刷新定时器没启动'
    assert w._auto_timer.interval() >= 1000, '轮询间隔过短会耗 CPU'


def test_pinned_cleared_when_its_star_disappears(tmp_maps):
    """钉住的那条被删后不能继续显示已不存在的详情"""
    mp, ep = tmp_maps
    w = _map(mp, ep)
    w.pinned = dict(w.stars[0])
    time.sleep(1.05)
    with open(mp, 'w', encoding='utf-8') as f:
        json.dump({'facts': [], 'summaries': []}, f, ensure_ascii=False)
    w._maybe_reload()
    assert w.pinned is None, '钉住的条目已不存在，详情卡应清掉'
