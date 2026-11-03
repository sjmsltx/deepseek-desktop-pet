# -*- coding: utf-8 -*-
"""星图 v2 视觉验证：多规模 + 多缩放（2026-11-03）

性能已经量化过了，这里只验「好不好看」和「LOD 是否可感知」：
  · 三种规模（27 / 206 / 1411）
  · 1411 在 zoom=1 / 2 / 3 下的 LOD 揭示（放大后可见星应变多）
  · 打印每档可见数，确认「显示 N / 共 M」不是空话
"""
import io
import json
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

_HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(_HERE)
DATA = os.path.join(EXP, 'data')
REPO = os.path.dirname(os.path.dirname(os.path.dirname(EXP)))
DATA = os.path.join(EXP, 'data')
OUT_DIR = os.path.join(EXP, 'shots')
os.makedirs(OUT_DIR, exist_ok=True)
sys.path.insert(0, REPO)

from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
for f in (r'C:\Windows\Fonts\msyh.ttc', r'C:\Windows\Fonts\simhei.ttf'):
    if os.path.exists(f):
        QFontDatabase.addApplicationFont(f)

import memory_starmap as sms  # noqa: E402

def _wjson(path, obj, **kw):
    """写 JSON（产品代码禁止一行式 open：长驻进程里是真实句柄泄漏）。"""
    kw.setdefault('ensure_ascii', False)
    kw.setdefault('indent', 1)
    with io.open(path, 'w', encoding='utf-8', newline='\n') as _f:
        _f.write(json.dumps(obj, **kw) + '\n')



NONE = os.path.join(OUT_DIR, '_none.json')


def stars_of(n):
    real = [f for f in json.loads(io.open(os.path.join(REPO, 'memory.json'),
                                         encoding='utf-8').read())['facts']
            if f.get('status') == 'active']
    exp = json.loads(io.open(os.path.join(DATA, 'memories-1411.json'),
                             encoding='utf-8').read())['facts']
    merged = real + exp[:max(0, n - len(real))]
    tmp = os.path.join(OUT_DIR, '_tmp.json')
    _wjson(tmp, {'facts': merged, 'summaries': [], 'updated_at': ''}, indent=None)
    out = sms.load_stars(tmp, os.path.join(REPO, 'memories.json'))
    os.remove(tmp)
    return out


def render(stars, dead, raw, tag, zoom=1.0, size=(1500, 940)):
    w = sms.MemoryStarMap(stars=stars, dead=dead, raw_events=raw,
                          facts_path=os.path.join(REPO, 'memory.json'),
                          events_path=os.path.join(REPO, 'memories.json'))
    w.resize(*size)
    w._compute_layout()
    w._layout_cached_size = (w.width(), w.height())
    w.zoom = zoom
    w._lod_cache = None
    app.processEvents()
    vis = w._lod_visible()
    p = os.path.join(OUT_DIR, 'v2-%s.png' % tag)
    w.grab().save(p)
    print('  %-18s %4d 星  LOD可见 %4d  视野内 %4d  格 %4.1fpx 符号x%.2f  → %s (%d KB)'
          % (tag, len(stars), len(vis), getattr(w, '_onview_n', -1),
             sms.LOD_CELL_BASE, w._sym_scale(),
             os.path.basename(p), os.path.getsize(p) // 1024))
    return w, len(vis)


print('=== 渲染 ===')
s1, d1, r1 = stars_of(27)
render(s1, d1, r1, 'n27')

s2, d2, r2 = stars_of(206)
render(s2, d2, r2, 'n206')

s3, d3, r3 = stars_of(1411)
render(s3, d3, r3, 'n1411-z1', zoom=1.0)
render(s3, d3, r3, 'n1411-z2', zoom=2.0)
render(s3, d3, r3, 'n1411-z3', zoom=3.0)

print()
print('=== 类团半径（√n 分配结果）===')
w = sms.MemoryStarMap(stars=s3, dead=d3, raw_events=r3,
                      facts_path=os.path.join(REPO, 'memory.json'),
                      events_path=os.path.join(REPO, 'memories.json'))
w.resize(1500, 940)
w._compute_layout()
for cat in sms.ORDER:
    n = len(w._groups.get(cat) or [])
    r = w._cat_r.get(cat, 0)
    if n:
        import math
        dens = n / (math.pi * r * r) * 1000 if r else 0
        print('  %-8s %4d 颗  半径 %5.1fpx  密度 %.3f 颗/千px²' % (cat, n, r, dens))
print()
print('  R = %.1f  （类团中心距 R*0.80 = %.1f）' % (w._R, w._R * 0.80))
