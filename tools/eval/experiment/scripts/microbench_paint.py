# -*- coding: utf-8 -*-
"""剩余成本微基准（2026-11-03）

已经砍掉了 gradient 与大部分 drawLine/drawEllipse，剩 19~32ms/帧。
要判断下一步该改哪个，必须先分别量出：

  · 缩放 drawPixmap 的单价（smooth on/off）
  · 不缩放 drawPixmap 的单价
  · drawEllipse 单价
  · 实际画了多少颗星（LOD 后）
  · 视窗剔除能省多少（zoom>1 时大部分在窗外）
"""
import io
import json
import math
import os
import statistics
import sys
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

_HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(_HERE)
DATA = os.path.join(EXP, 'data')
REPO = os.path.dirname(os.path.dirname(os.path.dirname(EXP)))
DATA = os.path.join(EXP, 'data')
sys.path.insert(0, REPO)

from PySide6.QtCore import QPointF, QRectF  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
import memory_starmap as sms  # noqa: E402

def _wjson(path, obj, **kw):
    """写 JSON（产品代码禁止一行式 open：长驻进程里是真实句柄泄漏）。"""
    kw.setdefault('ensure_ascii', False)
    kw.setdefault('indent', 1)
    with io.open(path, 'w', encoding='utf-8', newline='\n') as _f:
        _f.write(json.dumps(obj, **kw) + '\n')



W, H = 1440, 900


def stars_of(n):
    real = [f for f in json.loads(io.open(os.path.join(REPO, 'memory.json'),
                                         encoding='utf-8').read())['facts']
            if f.get('status') == 'active']
    exp_facts = json.loads(io.open(os.path.join(DATA, 'memories-1411.json'),
                                  encoding='utf-8').read())['facts']
    merged = real + exp_facts[:max(0, n - len(real))]
    tmp = os.path.join(EXP, '.mb.json')
    _wjson(tmp, {'facts': merged, 'summaries': [], 'updated_at': ''}, indent=None)
    out = sms.load_stars(tmp, os.path.join(REPO, 'memories.json'))
    os.remove(tmp)
    return out


def timeit(fn, n=20):
    ts = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t) * 1000)
    return statistics.median(ts)


def main():
    print('=' * 70)
    print('微基准：单次绘制操作单价（%dx%d）' % (W, H))
    print('=' * 70)
    img = QImage(W, H, QImage.Format_ARGB32_Premultiplied)

    stars, dead, raw = stars_of(1417)
    w = sms.MemoryStarMap(stars=stars, dead=dead, raw_events=raw,
                          facts_path=os.path.join(REPO, 'memory.json'),
                          events_path=os.path.join(REPO, 'memories.json'))
    w.resize(W, H)
    w._compute_layout()
    w._layout_cached_size = (W, H)

    vis = w._lod_visible()
    print('  LOD 可见 %d / %d 颗（zoom=%.2f，格边长 %.1fpx）'
          % (len(vis), len(w.stars), w.zoom,
             max(sms.LOD_CELL_MIN, sms.LOD_CELL_BASE / w.zoom)))

    pm = w._star_sprite('like', 0.9)
    print('  sprite 尺寸 %dx%d' % (pm.width(), pm.height()))

    N = len(vis)

    def loop_pixmap_scaled(smooth):
        def run():
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setRenderHint(QPainter.SmoothPixmapTransform, smooth)
            for i in range(N):
                x, y = (i * 7) % W, (i * 13) % H
                r = 20.0
                p.drawPixmap(QRectF(x - r, y - r, r * 2, r * 2), pm, QRectF(pm.rect()))
            p.end()
        return run

    def loop_ellipse():
        def run():
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setPen(sms.Qt.NoPen)
            for i in range(N):
                x, y = (i * 7) % W, (i * 13) % H
                p.setBrush(QColor(108, 204, 255, 120))
                p.drawEllipse(QPointF(x, y), 8.0, 8.0)
            p.end()
        return run

    print()
    print('  %-34s %s' % ('操作（%d 次）' % N, '中位 ms'))
    print('  ' + '-' * 52)
    print('  %-34s %.2f' % ('drawPixmap 缩放 + smooth', timeit(loop_pixmap_scaled(True))))
    print('  %-34s %.2f' % ('drawPixmap 缩放 无 smooth', timeit(loop_pixmap_scaled(False))))
    print('  %-34s %.2f' % ('drawEllipse（旧做法的一部分）', timeit(loop_ellipse())))

    # 按深度/imp 的实际尺寸分布
    sizes = []
    for s in vis:
        z = w._depth.get(s.get('key') or s['text'], 0.0)
        rad = (2.0 + 1.5 * s['imp']) * w.zoom * (1.0 - (1.0 - sms.DEPTH_RAD) * z)
        glow = 5.5 * (1.0 - (1.0 - sms.DEPTH_GLOW) * z)
        sizes.append(rad * glow * 2)
    print()
    print('  实际绘制方框边长：min %.1f / 中位 %.1f / max %.1f px'
          % (min(sizes), statistics.median(sizes), max(sizes)))

    # 视窗剔除潜力：zoom=4 时有多少在窗外
    print()
    print('  视窗剔除潜力（LOD 可见星里超出台画面的比例）：')
    for z in (1.0, 2.0, 4.0):
        outside = 0
        for s in vis:
            xy = w._layout.get(s.get('key') or s['text'])
            if not xy:
                continue
            sx = w._cx + (xy[0] - w._cx) * z
            sy = w._cy + (xy[1] - w._cy) * z
            if sx < -40 or sx > W + 40 or sy < -40 or sy > H + 40:
                outside += 1
        print('    zoom=%.1f  窗外 %d / %d 颗' % (z, outside, len(vis)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
