# -*- coding: utf-8 -*-
"""星图离屏渲染截图 + 深度数值核对（2026-11-03）

⚠ 必须用带 PySide6 的独立 python（GUI 项目规矩）：
   C:\\Users\\<user>\\AppData\\Local\\Python\\pythoncore-3.14-64\\python.exe

⚠ offscreen 平台不加载 Windows 系统字体 ⇒ 中文全变方框，看不出效果。
   这里显式 addApplicationFont 注入 msyh.ttc，让截图可判读。
"""
import io
import json
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

REPO = os.path.dirname(os.path.dirname(os.path.dirname(BASE)))  # 仓库根（上溯 3 层）
_HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(_HERE)              # experiment/
DATA = os.path.join(BASE, 'data')
OUT_DIR = os.path.join(BASE, 'shots')
os.makedirs(OUT_DIR, exist_ok=True)
sys.path.insert(0, REPO)

from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

# 注入中文字体（offscreen 下默认没有）
for f in (r'C:\Windows\Fonts\msyh.ttc', r'C:\Windows\Fonts\simhei.ttf'):
    if os.path.exists(f):
        fid = QFontDatabase.addApplicationFont(f)
        fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
        print('字体 %s → %s' % (os.path.basename(f), fams or '加载失败'))

import memory_starmap as msm  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402,F401

def _rjson(path):
    """读 JSON。with 包裹 —— 产品代码禁止一行式 open（长驻进程里是真实句柄泄漏）。"""
    with io.open(path, encoding='utf-8') as _f:
        return json.loads(_f.read())


def _wjson(path, obj, **kw):
    """写 JSON（同 _rjson 的理由）。默认 ensure_ascii=False、indent=1。"""
    kw.setdefault('ensure_ascii', False)
    kw.setdefault('indent', 1)
    with io.open(path, 'w', encoding='utf-8', newline='\n') as _f:
        _f.write(json.dumps(obj, **kw) + '\n')



NONE = os.path.join(OUT_DIR, '_none.json')


def stars_of(facts):
    tmp = os.path.join(OUT_DIR, '_tmp_memory.json')
    _wjson(tmp, {'facts': facts, 'summaries': [], 'updated_at': ''}, indent=None)
    stars, dead, n_raw = msm.load_stars(tmp, NONE)
    os.remove(tmp)
    return stars, dead, n_raw


def render(stars, dead, n_raw, tag, size=(1500, 940)):
    w = msm.MemoryStarMap(stars=stars, dead=dead, raw_events=n_raw,
                          facts_path=os.path.join(REPO, 'memory.json'),
                          events_path=os.path.join(REPO, 'memories.json'))
    w.resize(*size)
    w._compute_layout()
    w._layout_cached_size = (w.width(), w.height())
    app.processEvents()
    p = os.path.join(OUT_DIR, 'starmap-%s.png' % tag)
    w.grab().save(p)
    return w, p


def check_depth(w, tag):
    """深度线索的数值核对 —— 不靠肉眼"""
    if not w.stars:
        return
    W, H = w.width(), w.height()
    items = sorted(w.stars, key=lambda s: s.get('age') or 0.0)
    def info(s):
        k = s.get('key') or s['text']
        z = w._depth.get(k, 0.0)
        x, y = w._layout[k]
        base = (2.0 + 1.5 * s.get('imp', 3))
        rad_k = 1.0 - (1.0 - msm.DEPTH_RAD) * z
        glow = 5.5 * (1.0 - (1.0 - msm.DEPTH_GLOW) * z)
        ga = 1.0 - 0.55 * z
        return z, x, y, rad_k, glow, ga
    n = max(1, min(3, len(items)))
    new, old = items[:n], items[-n:]
    print('  --- %s（%d 星）---' % (tag, len(w.stars)))
    for label, grp in (('最新', new), ('最老', old)):
        for s in grp:
            z, x, y, rad_k, glow, ga = info(s)
            print('     %s age=%7.1f z=%.3f  (x=%6.1f, y=%6.1f)  半径×%.2f 光晕×%.2f α×%.2f'
                  % (label, s.get('age') or 0, z, x, y, rad_k, glow, ga))
    ys = [w._layout[s.get('key') or s['text']][1] for s in w.stars
          if (s.get('key') or s['text']) in w._layout]
    xs = [w._layout[s.get('key') or s['text']][0] for s in w.stars
          if (s.get('key') or s['text']) in w._layout]
    out_top = sum(1 for y in ys if y < 84)
    out_bot = sum(1 for y in ys if y > H - 30)
    out_x = sum(1 for x in xs if x < 6 or x > W - 6)
    print('     y 范围 %.0f~%.0f（画面 %d）/ x 范围 %.0f~%.0f（画面 %d）'
          % (min(ys), max(ys), H, min(xs), max(xs), W))
    print('     出界：顶部标题区 %d 颗 / 底部 %d 颗 / 左右 %d 颗  %s'
          % (out_top, out_bot, out_x,
             '✓ 无越界' if (out_top + out_bot + out_x) == 0 else '⚠ 有越界'))
    return out_top + out_bot + out_x


print()
print('=' * 74)
print('渲染')
print('=' * 74)
real_facts = json.loads(io.open(os.path.join(REPO, 'memory.json'),
                                encoding='utf-8').read())['facts']
st1, d1, r1 = stars_of(real_facts)
w1, p1 = render(st1, d1, r1, 'real-21')
print('  21 条 → %s（%d KB）' % (p1, os.path.getsize(p1) // 1024))

exp = json.loads(io.open(os.path.join(DATA, 'memories-1411.json'), encoding='utf-8').read())
st2, d2, r2 = stars_of(exp['facts'])
w2, p2 = render(st2, d2, r2, 'exp-1411')
print('  1411 条 → %s（%d KB）' % (p2, os.path.getsize(p2) // 1024))

st3, d3, r3 = stars_of(exp['facts'][:180])
w3, p3 = render(st3, d3, r3, 'exp-200')
print('  200 条（产品上限）→ %s（%d KB）' % (p3, os.path.getsize(p3) // 1024))

print()
print('=' * 74)
print('深度数值核对')
print('=' * 74)
bad = 0
for w, tag in ((w1, 'real-21'), (w3, 'exp-200'), (w2, 'exp-1411')):
    bad += check_depth(w, tag) or 0
print()
print('越界合计 %d 颗' % bad)
