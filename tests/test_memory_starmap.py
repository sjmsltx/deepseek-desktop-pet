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


def _widget_with(stars):
    """用指定星点构造控件（不读盘）。

    ⚠ 必须 resize + show + 显式 _compute_layout：布局与 LOD 都依赖窗口尺寸，
    不布局的话 _layout 为空 ⇒ _lod_visible 返回空 ⇒ 任何「边」的断言都是假空。
    """
    w = sm.MemoryStarMap(stars=stars, dead=[], raw_events=0,
                         facts_path=os.path.join(BASE, 'memory.json'),
                         events_path=os.path.join(BASE, 'memories.json'))
    w.resize(1500, 940)
    w.show()
    _app.processEvents()
    w._compute_layout()
    w._layout_cached_size = (w.width(), w.height())
    return w

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

    for _ in range(60):
        wheel(120)
    # ⚠ 2026-11-03：这里原来写死 4.0 / 0.35。Owner「放大上限再调高一点」把上限
    #   改成常量 ZOOM_MAX（4.0 → 30），硬编码数值属于契约漂移，改为引用单一源。
    #   **本测试的契约是「有钳制」**，不是「钳制在某个具体数」。
    assert w.zoom <= sm.ZOOM_MAX + 1e-9, '放大未被钳制：%r (上限 %r)' % (w.zoom, sm.ZOOM_MAX)
    for _ in range(200):
        wheel(-120)
    assert w.zoom >= sm.ZOOM_MIN - 1e-9, '缩小未被钳制：%r (下限 %r)' % (w.zoom, sm.ZOOM_MIN)
    # 反向守护：上限必须留够「放大看单颗」的余地 —— 否则这条设计意图会被悄悄改回去
    assert sm.ZOOM_MAX >= 8.0, '放大上限太小（%r），几万条数据集无法放大到单颗' % sm.ZOOM_MAX


def _press(w, pos):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(pos[0], pos[1]), QPointF(pos[0], pos[1]),
                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    w.mousePressEvent(ev)


def _move(w, pos):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    ev = QMouseEvent(QEvent.MouseMove, QPointF(pos[0], pos[1]), QPointF(pos[0], pos[1]),
                     Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    w.mouseMoveEvent(ev)


def _release(w, pos):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    ev = QMouseEvent(QEvent.MouseButtonRelease, QPointF(pos[0], pos[1]), QPointF(pos[0], pos[1]),
                     Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
    w.mouseReleaseEvent(ev)


def test_drag_over_star_does_not_pin():
    """防误触：按在星上拖动画面，松手不能把星钉住。

    Owner 原话：「拖动时难免点到星上进行拖拽，这不是真的要钉住」。
    原先 mousePressEvent 一按到星就钉住，拖动永远逃不掉。
    """
    w = _widget()
    s = max(w.stars, key=lambda x: x.get('imp', 3))
    k = s.get('key') or s['text']
    sp = w._to_screen(*w._layout[k])
    _press(w, (sp.x(), sp.y()))
    _move(w, (sp.x() + 40, sp.y() + 30))      # 明显拖动
    _release(w, (sp.x() + 40, sp.y() + 30))
    assert w.pinned is None, '拖动时误把星钉住了 ✗'
    # 而且画面确实平移了（拖动没有白做）
    assert w.pan.x() != 0 or w.pan.y() != 0, '拖动没有平移画面'


def test_click_on_star_pins():
    """对照：按下就松开（位移小于阈值）应正常钉住 —— 防误触不能把点击也废掉。"""
    w = _widget()
    s = max(w.stars, key=lambda x: x.get('imp', 3))
    k = s.get('key') or s['text']
    sp = w._to_screen(*w._layout[k])
    _press(w, (sp.x(), sp.y()))
    _release(w, (sp.x(), sp.y()))
    assert w.pinned is not None, '单击星点未能钉住 ✗（防误触做过头了）'


def test_small_jitter_still_pins():
    """按下后轻微抖动（小于 DRAG_THRESHOLD）仍算点击 —— 手抖不该丢点击。"""
    w = _widget()
    s = max(w.stars, key=lambda x: x.get('imp', 3))
    k = s.get('key') or s['text']
    sp = w._to_screen(*w._layout[k])
    _press(w, (sp.x(), sp.y()))
    _move(w, (sp.x() + 2, sp.y() + 2))
    _release(w, (sp.x() + 2, sp.y() + 2))
    assert w.pinned is not None, '手抖 2px 就丢点击 ✗'


def test_layout_deterministic_with_jitter():
    """抖动必须确定性（crc32 而非 hash()）—— 否则每次开窗位置都变。"""
    w = _widget()
    a = dict(w._layout)
    w._layout = {}
    w._compute_layout()
    b = dict(w._layout)
    assert a == b, '加了抖动后布局不再确定（可能用了内置 hash()）'


def test_edges_computed_on_visible_set_not_filtered():
    """联系性回归：LOD 启用时，边必须在**可见集**上算，不是「全量算完再过滤」。

    2026-11-04 实测：1417 点按「全量算边 → 要求两端都可见」只留下 49 条强边
    （保留 17% 的点 ⇒ 边留下约 p²≈3%），可见星里 64% 一条边都没有 —— 表现为
    「节点之间的联系性没体现」。改成在可见集上重算后：强边 172、有边星 83%。

    本用例用「30 组、每组 10 条同文」造强边：
      · 在可见集上算 ⇒ 同组内必有边，有边星比例高
      · 全量算完过滤 ⇒ 同组 10 条里大约只剩 1~2 条可见，比例很低
    """
    stars = []
    for g in range(30):
        for k in range(10):
            # ⚠ age 必须在组内拉开：布局按 age 排序定半径，age 相近的点
            #   会挤在同一处、被 LOD 去重掉 ⇒ 看不到组内同文应有的边。
            stars.append({'text': '第%d组 用户喜欢遥感课程 组内同文 %d' % (g, k),
                          'imp': 3, 'age': 1.0 + k * 25.0 + g * 0.7, 'kind': 'fact',
                          'cat': 'study', 'detail': '', 'time': '',
                          'key': 'k%d_%d' % (g, k)})
    w = _widget_with(stars)
    vis = w._lod_visible()
    assert len(vis) < len(stars), '此用例要求 LOD 生效（否则测不到过滤问题）'
    se, _we = w._edges_for(vis)
    assert se, '可见集上一条强边都没有 —— 边可能还在全量上算'
    linked = set()
    vkeys = [(x.get('key') or x['text']) for x in vis]
    for i, j, _wt in se:
        linked.add(vkeys[i])
        linked.add(vkeys[j])
    ratio = len(linked) / float(len(vis))
    assert ratio >= 0.5, (
        '可见星里只有 %.0f%% 有强边 —— 边可能是「全量算完再过滤」而不是在可见集上算'
        % (ratio * 100))


def test_small_library_edges_unchanged():
    """小库零回归：≤LOD_MIN_N 时 vis 就是 self.stars 本身，边与全量一致。"""
    w = _widget()
    assert len(w.stars) <= sm.LOD_MIN_N, '真实库应小于 LOD 阈值'
    vis = w._lod_visible()
    assert vis is w.stars, '小库时 _lod_visible 应原样返回 self.stars'
    se, we = w._edges_for(vis)
    ref_s, ref_w = sm.build_edges(w.stars)
    assert len(se) == len(ref_s) and len(we) == len(ref_w), '小库边数与全量算不一致'


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
