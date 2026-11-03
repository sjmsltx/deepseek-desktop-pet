# -*- coding: utf-8 -*-
"""时间戳回填（2026-11-03）

## 做什么

把 `timeline_plan.json` 里那 1200 个年龄（跨 730 天）分配给 `experiment.json` 里的
facts/events，写进 `created_at` 与 `age_days`。

## 为什么要回填

Owner：「人工加快时间进展，不然那个测试不出来」

不压缩时间，就得真等两年才能看到「幂律 vs 指数」的差别。
回填后一次生成就有「1 天 ~ 730 天」的完整分布。

## 分配策略

| 原则 | 理由 |
|---|---|
| **按 batch 顺序对年龄**（早期批 = 更老） | 真实使用是「越早的事越老」，随机撒会让同一次对话里的事实年龄相差两年，不真实 |
| batch 内**轻微抖动**（±1 天） | 同一段对话里的几条不该秒级同刻 |
| `importance` **不影响年龄** | 这只是重要度，不是新近度 |

## ⚠ 关键：这不是真实时间流逝

回填出的数据能回答「不同年龄的记忆，权重/亮度差多少」（灵敏度分析），
**不能**回答「人真正会怎么忘」（那需要真人两年的使用记录）。
两者差别必须写进实验文档，否则以后有人会拿它当"实证"。
"""
import datetime
import io
import json
import os
import random
import sys

OUT = r'D:\AutoClawworkspace\桌宠记忆实验-20261103'
EXP = os.path.join(OUT, 'experiment.json')
PLAN = os.path.join(OUT, 'timeline_plan.json')


def main():
    if not os.path.exists(EXP):
        print('✗ 缺少 experiment.json —— 先跑 run_experiment.py')
        return 1
    exp = json.loads(io.open(EXP, encoding='utf-8').read())
    plan = json.loads(io.open(PLAN, encoding='utf-8').read())
    ages = plan['ages']

    n_item = len(exp['facts']) + len(exp['events'])
    print('条目 %d（facts %d + events %d）/ 可用年龄 %d'
          % (n_item, len(exp['facts']), len(exp['events']), len(ages)))
    if n_item > len(ages):
        print('⚠ 条目比年龄多 %d 个，多出的会重复用最老段' % (n_item - len(ages)))

    # 年龄升序（小=新）；batch 越小 → 用越老的年龄 → 从尾部取
    ages_sorted = sorted(ages, reverse=True)      # 大在前 = 老
    n_batch = max(len(exp['batches']), 1)
    batch_span = max(1, len(ages_sorted) // n_batch)
    rnd = random.Random(20261103)
    now = datetime.datetime(2026, 11, 3, 12, 0, 0)

    def assign_batch(bi):
        """该批用哪一段年龄"""
        lo = min(bi * batch_span, len(ages_sorted) - 1)
        hi = min(lo + batch_span, len(ages_sorted))
        return ages_sorted[lo:hi] or [ages_sorted[-1]]

    cursor = {}
    for coll in ('facts', 'events'):
        for it in exp[coll]:
            bi = int(it.get('batch') or 0)
            pool = assign_batch(bi)
            k = cursor.get(bi, 0)
            cursor[bi] = k + 1
            base = pool[k % len(pool)]
            # 批内抖动（小时级），避免同秒
            age = max(0.1, base + rnd.uniform(-0.5, 0.5))
            it['age_days'] = round(age, 2)
            it['created_at'] = (now - datetime.timedelta(days=age)).strftime('%Y-%m-%d %H:%M')

    # 统计
    from collections import Counter
    def bucket(a):
        for lo, hi, name in [(0, 7, '0-7天'), (7, 30, '7-30天'), (30, 90, '30-90天'),
                             (90, 180, '90-180天'), (180, 365, '180-365天'),
                             (365, 545, '365-545天'), (545, 9999, '545天+')]:
            if lo <= a < hi:
                return name
        return '其他'

    print()
    print('=== 回填后的年龄分布 ===')
    for coll in ('facts', 'events'):
        c = Counter(bucket(it['age_days']) for it in exp[coll])
        print('  %s（%d 条）：' % (coll, len(exp[coll])))
        for name in ('0-7天', '7-30天', '30-90天', '90-180天', '180-365天', '365-545天', '545天+'):
            n = c.get(name, 0)
            if n:
                print('     %-10s %4d  %s' % (name, n, '#' * int(n / max(len(exp[coll]), 1) * 50)))

    exp.setdefault('meta', {})
    exp['meta'].update({
        '时间回填': {
            '方式': '按 batch 顺序对年龄（早期批=更老）+ 批内 ±0.5 天抖动',
            '基准时间': now.strftime('%Y-%m-%d %H:%M'),
            '跨度': '%s ~ %s' % (
                min(it['created_at'] for it in exp['facts']) if exp['facts'] else '-',
                max(it['created_at'] for it in exp['facts']) if exp['facts'] else '-'),
            '⚠ 性质': '这是**合成时间轴**，不是真实时间流逝。能回答「不同年龄的权重差多少」，'
                     '不能回答「人真正怎么忘」。',
        },
    })

    io.open(EXP, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(exp, ensure_ascii=False, indent=1) + '\n')
    print()
    print('已写 %s (%d KB)' % (EXP, os.path.getsize(EXP) // 1024))
    print('  时间跨度：%s ~ %s' % (
        min(it['created_at'] for it in exp['facts']),
        max(it['created_at'] for it in exp['facts'])))
    return 0


if __name__ == '__main__':
    sys.exit(main())
