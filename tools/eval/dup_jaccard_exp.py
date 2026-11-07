# -*- coding: utf-8 -*-
"""近重复判据实验：原始 Jaccard vs 去泛用词 Jaccard（2026-11-06，2026-11-08 入库）

## 它回答的问题

「要不要在写入时自动合并近重复记忆？」——想合，得先有一个能分开「真重复」与
「只是措辞像」的判据。本脚本量的是：这个词面判据到底分不分得开。

## 当时的结论（用本脚本可复现）

三对人工判定过的样本，去泛用词后：

    真重复  日语梗 ↔ 日语谐音梗                 原始 0.321 → 0.208
    假配对  日语梗 ↔ 主流 AI 模型（都在讲开玩笑）  原始 0.212 → 0.107
    假配对  我的名字 ↔ 姐姐的名字                原始 0.176 → 0.188

真假间隔从 0.109 缩到 **0.020** ⇒ **判据分不开**。
所以产品里没有做「按词面阈值自动合并」，而是交给抽取阶段的 `update_facts`
（模型看着已有记忆判断），并在下一轮复核。

⚠ 这是 2026-11-06 在 21 条真实库上量的结果。**库变了就要重量**：
   本次结论的正确表述是「该判据在当时那批数据上分不开」，
   不是「近重复永远不能按词面判断」。

## 用法

    python tools/eval/dup_jaccard_exp.py                     # 全库分布 + 最像的若干对
    python tools/eval/dup_jaccard_exp.py --top 15            # 多看几对
    python tools/eval/dup_jaccard_exp.py --pairs 14:15,2:3   # 指定下标的配对

⚠ `--pairs` 用的是**库内下标**（从 0 起，只数 active 条目），换库后下标会漂移；
   所以默认不给指定配对，只按相似度列出最像的那些对，由人判断真假。
"""
import argparse
import io
import itertools
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import memory_engine as me      # noqa: E402

#: 泛用词：在人对桌宠的日常对话里几乎每条都会出现，不携带「是哪件事」的信息
GENERIC = set("""
用户 桌宠 会话 我 你 的 了 是 会 和 与 及 等 如 对 向 把 被 让 给 从 到 为 以 或 但 而 且 并
一下 一些 有点 比较 觉得 认为 可以 什么 怎么 这个 那个 他们 我们 自己
玩笑 开玩笑 逗 玩 说 聊 提到 记录 相关 涉及 进行 使用 通过 方式 习惯 经常 常常 总是 主动 关注
有 在 也 都 还 就 很 更 最 太 不 没 中 上 下 后 前 里 时 时候 能 要 做 用
""".split())

#: 同义归并：把同族词折成一个键，否则「日语梗」与「日语谐音梗」不算共享
SYNONYM = {
    '谐音': '梗', '谐音梗': '梗', 'meme': '梗',
}


def toks(text):
    """去泛用词 + 同义归并后的 token 集合"""
    out = set()
    for t in me.tokenize(text or ''):
        if t in GENERIC:
            continue
        out.add(SYNONYM.get(t, t))
    return out


def jac(a, b):
    """Jaccard；任一为空返回 0.0"""
    return 0.0 if not a or not b else len(a & b) / float(len(a | b))


def load_facts(path):
    data = json.load(io.open(path, encoding='utf-8'))
    return [f for f in data.get('facts', []) if f.get('status') == 'active']


def report_pairs(facts, raw, flt, pairs):
    """打印指定配对（下标 → 内容 → 两个口径的相似度 → 共享实词）"""
    for i, j, truth in pairs:
        if not (0 <= i < len(facts) and 0 <= j < len(facts)):
            print('  [跳过] 下标越界 %d:%d（当前 active 只有 %d 条）'
                  % (i, j, len(facts)))
            continue
        print('%s  [%d]↔[%d]' % (truth, i, j))
        print('    A: %r' % (facts[i].get('content') or '')[:80])
        print('    B: %r' % (facts[j].get('content') or '')[:80])
        print('    原始 %.3f → 去泛用词 %.3f' % (jac(raw[i], raw[j]), jac(flt[i], flt[j])))
        print('    共享实词：%r' % sorted(flt[i] & flt[j]))
        print()


def main(argv=None):
    ap = argparse.ArgumentParser(description='近重复判据实验（Jaccard）')
    ap.add_argument('--memory', default=os.path.join(ROOT, 'memory.json'))
    ap.add_argument('--top', type=int, default=10, help='列出最像的前 N 对')
    ap.add_argument('--pairs', default='',
                    help='指定下标配对，如 14:15,2:3（可带 :真重复/:假配对 标签）')
    args = ap.parse_args(argv)

    if not os.path.exists(args.memory):
        raise SystemExit('库文件不存在：%s' % args.memory)

    facts = load_facts(args.memory)
    if len(facts) < 2:
        raise SystemExit('active facts 只有 %d 条，至少要 2 条才能配对' % len(facts))

    raw = [set(me.tokenize(f.get('content') or '')) for f in facts]
    flt = [toks(f.get('content') or '') for f in facts]

    print('库文件：%s' % args.memory)
    print('active facts：%d 条 ⇒ 待比对数 %d' % (len(facts), len(facts) * (len(facts) - 1) // 2))
    print()

    if args.pairs:
        pairs = []
        for chunk in args.pairs.split(','):
            chunk = chunk.strip()
            if not chunk:
                continue
            spec, _, label = chunk.partition(':')
            i, _, j = spec.partition(':') if ':' in spec else spec.partition('=')
            try:
                pairs.append((int(i), int(j), label or '未标注'))
            except ValueError:
                raise SystemExit('配对格式不对：%r（应为 14:15 或 14:15:真重复）' % chunk)
        print('=' * 100)
        print('指定配对')
        print('=' * 100)
        report_pairs(facts, raw, flt, pairs)

    allf = sorted((jac(flt[i], flt[j]), i, j)
                  for i, j in itertools.combinations(range(len(facts)), 2))
    vals = [v for v, _i, _j in allf]

    print('=' * 100)
    print('全库分布（去泛用词后）')
    print('=' * 100)
    print('  中位 %.3f   最大 %.3f   配对总数 %d' % (vals[len(vals) // 2], max(vals), len(vals)))
    print()

    print('=' * 100)
    print('最像的 %d 对（去泛用词口径；真假由人判断，脚本不判）' % args.top)
    print('=' * 100)
    for v, i, j in list(reversed(allf))[:args.top]:
        print('  %.3f  [%d]↔[%d]  共享实词=%r' % (v, i, j, sorted(flt[i] & flt[j])))
        print('        A: %r' % (facts[i].get('content') or '')[:70])
        print('        B: %r' % (facts[j].get('content') or '')[:70])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
