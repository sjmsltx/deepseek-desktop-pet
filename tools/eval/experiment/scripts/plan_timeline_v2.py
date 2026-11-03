# -*- coding: utf-8 -*-
"""时间轴规划 v2 —— 一次成型（2026-11-03）

## v1 的问题（两轮都没修干净）

保底逻辑「从最密的桶抢」会和别的保底抢同一批样本：
  · 先补 730 → 把远端抽干
  · 再补 1 天 → 从最密桶抢，结果 1 天只到 10 条
  · 7 天那档被 1 天抢走，只剩 14 条

⇒ 顺序执行必然互相干扰。**改成一次性算配额**：

1. 先给 7 个关键点 + 最近窗口**固定分配**名额（占总量的 40%）
2. 剩下的 60% 走指数分布填中间的空白
3. 最后统一洗牌 + 排序

这样每个关键点的条数是**预先确定**的，不受执行顺序影响。
"""
import datetime
import io
import json
import math
import os
import random
import sys

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



import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
OUT = _os.path.dirname(_HERE)                  # 本实验目录（data/ 与 results/ 的父目录）
DATA = _os.path.join(OUT, 'data')              # 只读：语料 / 时间轴 / 1411 条记忆
RESULTS = _os.path.join(OUT, 'results')        # 只写：各脚本的分析结果
REPO = _os.path.dirname(_os.path.dirname(_os.path.dirname(OUT)))  # 仓库根（上溯 3 层）
N = 1200
SPAN = 730

#: 每个关键点：目标条数（±10% 窗口内）
KEY_POINTS = {
    1.0: 40,      # 最近，曲线起点
    7.0: 35,
    30.0: 60,     # 半衰期那一点（两种模型在此重合，是对照锚）
    90.0: 60,
    180.0: 50,
    365.0: 45,    # 一年
    730.0: 40,    # 两年，展示幂律不归零
}
FILL_RATIO = None     # 其余走指数


def main():
    rnd = random.Random(20261103)
    ages = []

    # ① 关键点：每个点在其 ±10% 窗口内均匀撒 count 条
    for kp, cnt in KEY_POINTS.items():
        lo, hi = max(0.2, kp * 0.9), kp * 1.1
        for _ in range(cnt):
            ages.append(rnd.uniform(lo, hi))

    # ② 剩余走指数（近端密），保证中间不留空洞
    rest = N - len(ages)
    for _ in range(rest):
        u = rnd.random()
        age = -math.log(1 - u * 0.95) / 3.0 * SPAN * 0.6
        ages.append(min(SPAN, max(0.2, age)))

    # ③ 校验：若某关键点窗口仍不足（被指数样本挤占不影响，因为配额已固定）
    ages.sort()
    assert len(ages) == N, '条数不对：%d' % len(ages)

    now = datetime.datetime(2026, 11, 3, 12, 0, 0)

    print('=== 时间轴分布（%d 条 / 跨度 %d 天）===' % (N, SPAN))
    print()
    print('  %-14s %-8s %-8s %s' % ('年龄段', '条数', '占比', ''))
    print('  ' + '-' * 62)
    buckets = [(0, 7), (7, 30), (30, 90), (90, 180), (180, 365), (365, 545), (545, 731)]
    for lo, hi in buckets:
        c = sum(1 for a in ages if lo <= a < hi)
        print('  %-14s %-8d %5.1f%%  %s' % (
            '%d~%d 天' % (lo, hi), c, c / N * 100, '#' * int(c / N * 70)))

    print()
    print('  关键年龄点（衰减曲线的测量点）：')
    ok_all = True
    for kp, want in sorted(KEY_POINTS.items()):
        lo, hi = kp * 0.9, kp * 1.1
        c = sum(1 for a in ages if lo <= a <= hi)
        flag = '✓' if c >= want * 0.9 else '★不足'
        if c < want * 0.9:
            ok_all = False
        print('     %5.0f 天（±10%%）：目标 %2d → 实有 %3d  %s' % (kp, want, c, flag))
    print()
    print('  %s' % ('✓ 全部关键点达标' if ok_all else '★ 有关键点不足，曲线该点不可信'))

    print()
    print('  时间范围: %s ~ %s' % (
        (now - datetime.timedelta(days=ages[-1])).strftime('%Y-%m-%d'),
        (now - datetime.timedelta(days=ages[0])).strftime('%Y-%m-%d')))

    print()
    print('=== 两种模型的因子差（说明为什么必须跨两年）===')
    sys.path.insert(0, REPO)
    import memory_events as me
    print('  %-9s %-11s %-11s %-10s %s' % ('年龄', '指数', '幂律', '差', '差/指数'))
    for kp in (1, 7, 30, 90, 180, 365, 545, 730):
        me.DECAY_MODEL = 'exponential'
        e = me.decay_factor(kp)
        me.DECAY_MODEL = 'power'
        p = me.decay_factor(kp)
        ratio = ('%.1f×' % (p / e)) if e > 1e-9 else '∞'
        print('  %-9s %-11.6f %-11.6f %-10.4f %s' % ('%d 天' % kp, e, p, p - e, ratio))
    me.DECAY_MODEL = 'power'
    print()
    print('  ⇒ 30 天完全相同（半衰期锚点），90 天岔开 0.19，730 天岔开 0.12 但幂律是 106 倍。')
    print('     没有跨年样本，「幂律 vs 指数」永远看不出区别。')

    plan = {
        '_meta': {
            '生成时间': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
            '样本数': N, '跨度天': SPAN,
            '撒法': '关键点配额固定 + 其余指数填充（v2，一次性算配额，不顺序执行）',
            '为什么要时间压缩': 'Owner：人工加快时间进展，否则衰减测不出来',
            '关键点': {str(k): v for k, v in KEY_POINTS.items()},
            '基准时间': now.strftime('%Y-%m-%d %H:%M'),
        },
        'ages': [round(a, 2) for a in ages],
        'timestamps': [(now - datetime.timedelta(days=a)).strftime('%Y-%m-%d %H:%M')
                       for a in ages],
    }
    p = os.path.join(DATA, 'timeline_plan.json')
    _wjson(p, plan, indent=2)
    print()
    print('  已写 %s (%d B)' % (p, os.path.getsize(p)))
    return 0 if ok_all else 1


if __name__ == '__main__':
    sys.exit(main())
