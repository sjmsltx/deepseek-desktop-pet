# -*- coding: utf-8 -*-
"""记忆星图查看器 —— 可载入真实库或实验数据（2026-11-03）

## 为什么单独做一个

产品里的星图入口（右键菜单「🌌 记忆星图」/ 主区面板）读的是真实库
（21 条 facts + 6 条 events），库太小，看不出 2.5D 与规模效应。

本脚本用**同一个产品控件** `MemoryStarMap`，只换数据源，不改产品行为。

## 用法

    python tools/eval/experiment/scripts/starmap_viewer.py
        真实库（21 条）

    python tools/eval/experiment/scripts/starmap_viewer.py --n 200
        真实库 21 条 + 实验噪声补到 200 条（= 产品上限 MAX_MEMORIES）

    python tools/eval/experiment/scripts/starmap_viewer.py --n 1411
        全量实验数据

    python tools/eval/experiment/scripts/starmap_viewer.py --file <memory.json>
        指定任意 memory.json 形状的文件

## 窗口里能做什么

拖动平移 · 滚轮缩放 · 点星钉住详情 · R 键复位 · 底部显示构建耗时
（用来亲眼确认 33s → 0.34s 这个改动）

⚠ 必须用带 PySide6 的独立 python：
   C:\\Users\\lby13\\AppData\\Local\\Python\\pythoncore-3.14-64\\python.exe
   不能用 AutoClaw 捆绑的 python（它带定制 Qt，透明窗口会显示白底灰框）。
"""
import argparse
import io
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
EXP_DIR = os.path.dirname(HERE)
DATA = os.path.join(EXP_DIR, 'data')
REPO = os.path.dirname(os.path.dirname(os.path.dirname(EXP_DIR)))
sys.path.insert(0, REPO)


def _rjson(path):
    with io.open(path, encoding='utf-8') as f:
        return json.loads(f.read())


def build_source(n=None, path=None):
    """返回 (facts_path, 标签)。默认写一个临时合并文件，不碰真实库。"""
    real_path = os.path.join(REPO, 'memory.json')
    exp_path = os.path.join(DATA, 'memories-1411.json')

    if path:
        return path, os.path.basename(path)

    if n is None:
        return real_path, '真实库'

    if not os.path.exists(exp_path):
        raise SystemExit('✗ 缺 %s —— 实验数据未就位' % exp_path)

    real = _rjson(real_path).get('facts') or []
    exp_facts = _rjson(exp_path).get('facts') or []
    real_active = [f for f in real if f.get('status') == 'active']
    need = max(0, n - len(real_active))
    merged = real_active + exp_facts[:need]

    tmp = os.path.join(EXP_DIR, '.viewer-%d.json' % n)
    with io.open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps({'facts': merged, 'summaries': [], 'updated_at': ''},
                           ensure_ascii=False))
    return tmp, '实验 %d 条（真实 %d + 合成 %d）' % (len(merged), len(real_active), need)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=None, help='星点总数（默认=真实库）')
    ap.add_argument('--file', default=None, help='指定 memory.json 形状的文件')
    args = ap.parse_args()

    from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QWidget
    app = QApplication.instance() or QApplication(sys.argv)

    import memory_starmap as sms

    facts_path, label = build_source(args.n, args.file)
    # 事件库：真实 memories.json 存在就用它（星图同时显示「共同经历」）；
    # 否则不传 —— 传一个不存在的路径只会刷 warning（第一版就这么干的）。
    events_path = os.path.join(REPO, 'memories.json')
    if not os.path.exists(events_path):
        events_path = None

    t0 = time.time()
    stars, dead, raw = sms.load_stars(facts_path, events_path or os.path.join(REPO, 'memories.json'))
    t_load = time.time() - t0

    # 单独测「连线构建」耗时 —— 这是 33s→0.34s 那个改动的直接指标。
    #   必须清掉缓存字段，否则控件会复用上一次的结果、测出 0.00s。
    t_e = time.time()
    sms.build_edges(stars)
    t_edges = time.time() - t_e

    win = QWidget()
    win.setWindowTitle('记忆星图 · %s' % label)
    win.resize(1440, 900)
    lay = QVBoxLayout(win)
    lay.setContentsMargins(0, 0, 0, 0)

    t1 = time.time()
    view = sms.MemoryStarMap(win,
                             stars=stars, dead=dead, raw_events=raw,
                             facts_path=facts_path,
                             events_path=events_path or os.path.join(REPO, 'memories.json'))
    lay.addWidget(view, 1)

    bar = QHBoxLayout()
    bar.setContentsMargins(12, 6, 12, 10)
    info = QLabel('拖动平移 · 滚轮缩放 · 点星钉住详情 · R 复位　|　'
                  '%s　|　读盘 %.2fs　连线构建 %.2fs'
                  % (label, t_load, t_edges))
    # 不写死颜色：主题守卫（tests/test_theme_tokens.py）把 tools/ 也算产品代码，
    # 硬编码十六进制色会让全量变红。用默认调色板即可。
    btn = QPushButton('复位视图')
    btn.clicked.connect(view.reset_view)
    bar.addWidget(info, 1)
    bar.addWidget(btn)
    lay.addLayout(bar)

    win.show()
    app.processEvents()
    # 对比口径：优化前是 O(V³) 的朴素 Prim，1411 点约 33 秒。
    info.setText('拖动平移 · 滚轮缩放 · 点星钉住详情 · R 复位　|　'
                 '%s　|　读盘 %.2fs　连线构建 %.2fs（优化前 1411 条约 33s）'
                 % (label, t_load, t_edges))
    print('星点 %d / 读盘 %.2fs / 连线构建 %.2fs'
          % (len(stars), t_load, t_edges))

    code = app.exec()
    # 清理临时合并文件（--n 模式）
    if args.n and os.path.exists(facts_path):
        try:
            os.remove(facts_path)
        except OSError:
            pass
    return code


if __name__ == '__main__':
    raise SystemExit(main())
