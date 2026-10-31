# -*- coding: utf-8 -*-
"""星图：数据只读 + 控件行为

锁住三件事：
1. 只读 —— 打开星图不能改动任何记忆文件（哈希前后一致）
2. 布局确定 —— 同尺寸两次布局结果一致（重绘不闪、可复现）
3. 交互可用 —— 命中测试、缩放夹取、复位
"""
import hashlib
import os
import sys

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import memory_starmap as sm  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)


def _sha(p):
    if not os.path.exists(p):
        return None
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def test_load_stars_readonly():
    """打开星图不得改动记忆文件"""
    f1, f2 = sm.FACTS_PATH, sm.EVENTS_PATH
    before = (_sha(f1), _sha(f2), os.path.getmtime(f1), os.path.getmtime(f2))
    stars, dead, raw = sm.load_stars()
    after = (_sha(f1), _sha(f2), os.path.getmtime(f1), os.path.getmtime(f2))
    assert before == after, '星图读取改动了记忆文件！'
    assert stars, '没读到星'


def test_load_stars_no_noise():
    stars, dead, raw = sm.load_stars()
    bad = [s['text'] for s in stars if '别处用了' in s['text'] or '余额 ¥' in s['text']]
    assert not bad, '噪音进了星图：%r' % bad[:3]


def test_load_stars_fields():
    stars, dead, raw = sm.load_stars()
    for s in stars:
        assert set(('text', 'imp', 'age', 'cat', 'kind')) <= set(s), '字段缺失：%r' % (s,)
        assert s['age'] >= 0
        assert s['cat'] in ('core', 'human', 'like', 'study', 'work', 'mile', 'dead')


def _widget():
    stars, dead, raw = sm.load_stars()
    w = sm.MemoryStarMap(stars=stars, dead=dead, raw_events=raw)
    w.resize(1200, 800)
    w.show()
    _app.processEvents()
    return w


def test_layout_deterministic():
    w = _widget()
    a = dict(w._layout)
    w._layout = {}
    w._compute_layout()
    b = dict(w._layout)
    assert a.keys() == b.keys()
    for k in a:
        assert abs(a[k][0] - b[k][0]) < 0.01 and abs(a[k][1] - b[k][1]) < 0.01, \
            '同尺寸布局不一致：%s' % k


def test_hit_test_finds_node():
    w = _widget()
    from PySide6.QtCore import QPointF
    # 布局现在按唯一 key 索引（同名条目不会互相覆盖）
    s = w.stars[0]
    k = s.get('key') or s['text']
    x, y = w._layout[k]
    sp = w._to_screen(x, y)
    hit = w._hit(sp)
    assert hit is not None and (hit.get('key') or hit['text']) == k, '命中测试失败'


def test_zoom_clamped():
    """走真实 wheelEvent（原来内联复算，删掉组件里的钳制仍会绿）"""
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QWheelEvent

    w = _widget()

    def wheel(dy):
        ev = QWheelEvent(QPointF(600, 400), QPointF(600, 400),
                         QPoint(0, 0), QPoint(0, dy),
                         Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        w.wheelEvent(ev)

    for _ in range(40):
        wheel(120)
    assert w.zoom <= 4.0, '放大未被钳制：%r' % w.zoom
    for _ in range(120):
        wheel(-120)
    assert w.zoom >= 0.35, '缩小未被钳制：%r' % w.zoom


def test_reset_view():
    w = _widget()
    w.zoom = 2.0
    w.pinned = object()
    w.reset_view()
    assert w.zoom == 1.0 and w.pinned is None


def test_render_smoke():
    """能真的画出来（离屏截图非空）"""
    w = _widget()
    pix = w.grab()
    assert pix.width() == 1200 and pix.height() == 800
    img = pix.toImage()
    assert not img.isNull()


def test_settings_entry_present():
    """设置页必须有入口 —— 否则功能等于不存在"""
    src = open(os.path.join(BASE, 'settings_ui.py'), encoding='utf-8').read()
    assert '记忆星图' in src and '_open_memory_starmap' in src, '设置页缺星图入口'
    dsrc = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    assert 'def _open_memory_starmap' in dsrc, 'PetWidget 缺 _open_memory_starmap'


# ---------- 审核（WX-153 后）抓出的崩溃场景，必须逐条钉住 ----------
def test_render_with_hover_does_not_crash():
    """M1：悬停后绘制曾必崩（QFontMetrics.boundingRect 传 QRectF → TypeError）"""
    w = _widget()
    w.hover = w.stars[0]
    pix = w.grab()            # 崩会直接抛异常
    assert not pix.toImage().isNull()


def test_render_with_pinned_does_not_crash():
    w = _widget()
    w.pinned = w.stars[0]
    pix = w.grab()
    assert not pix.toImage().isNull()


def test_render_hover_then_clear():
    w = _widget()
    w.hover = w.stars[0]
    w.grab()
    w.hover = None
    assert not w.grab().toImage().isNull()


def test_l0_core_follows_pan():
    """M2：拖动后中心核必须跟着走（曾留在屏幕正中 → 与辐条脱钩）"""
    from PySide6.QtCore import QPointF
    w = _widget()
    before = w._to_screen(w._cx, w._cy)
    w.pan = QPointF(150, 90)
    after = w._to_screen(w._cx, w._cy)
    assert abs((after.x() - before.x()) - 150) < 0.01
    assert abs((after.y() - before.y()) - 90) < 0.01


def test_hit_radius_scales_with_zoom():
    """C1：放大后 18px 固定半径会点不中"""
    from PySide6.QtCore import QPointF
    w = _widget()
    s = max(w.stars, key=lambda x: x.get('imp', 3))
    x, y = w._layout[s.get('key') or s['text']]
    sp = w._to_screen(x, y)
    w.zoom = 4.0
    sp = w._to_screen(x, y)
    # 偏离 20px 在 zoom=4 下应仍算命中该星
    hit = w._hit(QPointF(sp.x() + 20, sp.y()))
    assert hit is not None, 'zoom=4 时 20px 外点不中（命中半径没有随缩放放大）'


def test_stars_have_unique_keys():
    """布局以 key 为索引，key 重复会互相覆盖（只画一条）"""
    stars, dead, raw = sm.load_stars()
    keys = [s.get('key') for s in stars]
    assert all(keys), '有星点缺 key'
    assert len(set(keys)) == len(keys), 'key 重复：%d 颗只有 %d 个唯一 key' % (len(keys), len(set(keys)))


def test_layout_keys_match_star_keys():
    w = _widget()
    for s in w.stars:
        assert (s.get('key') or s['text']) in w._layout, '有星点没进布局：%r' % (s.get('key'),)


def test_raw_events_disclosed_in_subtitle():
    """C3：滤掉多少要说出来，不能把 3/200 说成「真实数据」而不披露"""
    src = open(os.path.join(BASE, 'memory_starmap.py'), encoding='utf-8').read()
    assert 'self.raw_events' in src and '滤除可重算播报' in src, '副标题未披露过滤量'


def test_detail_box_uses_qrect_not_qrectf():
    """结构钉：QRectF 传 boundingRect 在 PySide6 6.11 必抛 TypeError"""
    src = open(os.path.join(BASE, 'memory_starmap.py'), encoding='utf-8').read()
    assert 'fm.boundingRect(QRectF' not in src, '仍用 QRectF 调 boundingRect（会崩）'
