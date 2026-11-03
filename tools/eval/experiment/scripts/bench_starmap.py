# -*- coding: utf-8 -*-
"""星图渲染性能测量 + 热点定位（2026-11-03）

## 为什么要先量

Owner 反馈「一千多条就非常卡」。卡可能是：
  · 每颗星建一个 QRadialGradient（1417 个/帧）
  · 2663 条连线的 drawLine
  · 520 颗背景星尘的 drawEllipse
  · 每帧排序 1417 个星点
  · 标签文本测量
只能量了才知道该改哪个，不能猜。

## 指标

  ms/帧（连续渲染 30 帧取均值与中位数）+ cProfile 热点 top20
"""
import io
import json
import os
import statistics
import sys
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(HERE)
DATA = os.path.join(EXP, 'data')
REPO = os.path.dirname(os.path.dirname(os.path.dirname(EXP)))
sys.path.insert(0, REPO)

from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

import memory_starmap as sms  # noqa: E402

def _wjson(path, obj, **kw):
    """写 JSON（产品代码禁止一行式 open：长驻进程里是真实句柄泄漏）。"""
    kw.setdefault('ensure_ascii', False)
    kw.setdefault('indent', 1)
    with io.open(path, 'w', encoding='utf-8', newline='\n') as _f:
        _f.write(json.dumps(obj, **kw) + '\n')



N = 30


def make_stars(n):
    real = [f for f in json.loads(io.open(os.path.join(REPO, 'memory.json'),
                                         encoding='utf-8').read())['facts']
            if f.get('status') == 'active']
    exp_facts = json.loads(io.open(os.path.join(DATA, 'memories-1411.json'),
                                  encoding='utf-8').read())['facts']
    merged = real + exp_facts[:max(0, n - len(real))]
    tmp = os.path.join(EXP, '.bench-%d.json' % n)
    _wjson(tmp, {'facts': merged, 'summaries': [], 'updated_at': ''}, indent=None)
    stars, dead, raw = sms.load_stars(tmp, os.path.join(REPO, 'memories.json'))
    os.remove(tmp)
    return stars, dead, raw


def bench(n, size=(1440, 900)):
    stars, dead, raw = make_stars(n)
    w = sms.MemoryStarMap(stars=stars, dead=dead, raw_events=raw,
                          facts_path=os.path.join(REPO, 'memory.json'),
                          events_path=os.path.join(REPO, 'memories.json'))
    w.resize(*size)
    w._compute_layout()
    w._layout_cached_size = (w.width(), w.height())
    app.processEvents()

    img = QImage(size[0], size[1], QImage.Format_ARGB32_Premultiplied)
    times = []
    for _ in range(N):
        t0 = time.perf_counter()
        # 关键：走真正的 paintEvent（用 render 会另走一套路径）
        w.render(img)
        times.append((time.perf_counter() - t0) * 1000)
    return {
        'n': len(stars),
        'mean': statistics.mean(times),
        'median': statistics.median(times),
        'min': min(times),
        'max': max(times),
        'p90': sorted(times)[int(len(times) * 0.9)],
    }


def main():
    print('=' * 74)
    print('帧耗时（%d 帧，1440x900，offscreen）' % N)
    print('=' * 74)
    print('  %-8s %-10s %-10s %-10s %-10s %s'
          % ('星点', '均值ms', '中位ms', '最小', 'p90', '理论fps'))
    results = []
    for n in (27, 200, 600, 1417):
        r = bench(n)
        results.append(r)
        print('  %-8d %-10.1f %-10.1f %-10.1f %-10.1f %.1f'
              % (r['n'], r['mean'], r['median'], r['min'], r['p90'], 1000 / max(r['mean'], 0.01)))

    # ---- 热点剖析 ----
    print()
    print('=' * 74)
    print('cProfile 热点（1417 星，10 帧）')
    print('=' * 74)
    import cProfile
    import pstats

    stars, dead, raw = make_stars(1417)
    w = sms.MemoryStarMap(stars=stars, dead=dead, raw_events=raw,
                          facts_path=os.path.join(REPO, 'memory.json'),
                          events_path=os.path.join(REPO, 'memories.json'))
    w.resize(1440, 900)
    w._compute_layout()
    w._layout_cached_size = (1440, 900)
    app.processEvents()
    img = QImage(1440, 900, QImage.Format_ARGB32_Premultiplied)

    pr = cProfile.Profile()
    pr.enable()
    for _ in range(10):
        w.render(img)
    pr.disable()

    st = pstats.Stats(pr)
    st.sort_stats('cumulative')
    buf = io.StringIO()
    st.stream = buf
    st.print_stats(22)
    text = buf.getvalue()
    # 只打关键行
    for line in text.splitlines():
        if ('memory_starmap' in line or 'drawEllipse' in line or 'Gradient' in line
                or 'drawLine' in line or 'sorted' in line or 'paintEvent' in line
                or 'ncalls' in line or 'function calls' in line):
            print('  ' + line.strip()[:118])
    return 0


if __name__ == '__main__':
    sys.exit(main())
