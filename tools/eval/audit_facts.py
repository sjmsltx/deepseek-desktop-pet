# -*- coding: utf-8 -*-
"""facts 库体检：内容自足性 / 一次性 / 可检索性（2026-11-06，2026-11-08 入库）

## 它解决什么问题

`memory_write_policy`（写入边界）的判据不是拍脑袋来的 —— 是先对真实库逐条过一遍、
把这些类别挑出来，再归纳成规则。本脚本就是那一步的工具。

如果只把结论写进代码、不把工具放出来，别人只能选择「信」或「不信」；
放出来之后，判据可以自己复现。

## 三个标记（都只认客观特征，不做语义猜测）

| 标记 | 判据 | 为什么要看 |
|---|---|---|
| 自足性 | 含指代词（这个/那个/它/上述…）且短 | 脱离这段对话读不懂 ⇒ 写进 facts 后永远检索不到正确语境 |
| 一次性 | 含时间词/一次性动作词（今天/刚才/第一次/聊到…） | 「某一次发生的事」该进时间线，不该进常驻检索池 |
| 可检索性 | 有没有具体实体（数字/英文/书名号/专名后缀） | 无实体条目任何话题都能靠虚词命中 ⇒ 制造「什么都匹配得到」 |

## 用法

    python tools/eval/audit_facts.py                    # 默认读仓库根的 memory.json
    python tools/eval/audit_facts.py --memory <路径>     # 指定库文件

## ⚠ 输出是**候选清单**，不是判决

标记命中只代表「值得人看一眼」。真实库里「用户是大二学生」不含数字也不含专名后缀，
但它显然是有效记忆 —— 所以本脚本只做筛子，最终判断要人来做。
"""
import argparse
import io
import json
import os
import re

#: 仓库根（本文件位于 tools/eval/ 下两层）
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PRONOUN = ('这个', '那个', '这些', '那些', '它', '他们', '她们', '该', '此',
           '上面', '上述', '刚才', '之前说的', '这件事', '那件事')

#: 一次性事件词：出现即强烈提示「这是某一次发生的事」
ONCE = ('今天', '昨天', '刚才', '刚刚', '这次', '那次', '上次',
        '早上', '晚上', '上午', '下午', '一起玩', '聊到', '说了', '提到')

#: 具体实体：数字 / 英文 / 书名号 / 中文专名后缀（行政区划、机构、产品类别）
#: ⚠ 刻意不用「用户本人的地名/校名」这类具体词 —— 那会把使用者画像写进公开代码，
#:   而且换个人用这套脚本就不准了。
ENTITY = re.compile(
    r'[0-9]'
    r'|[A-Za-z]{2,}'
    r'|《[^》]+》'
    r'|[\u4e00-\u9fff]{2,}(?:大学|学院|中学|公司|系统|平台|软件|语言|'
    r'课程|专业|城市|区|县|省|市|镇|路|街)'
)

#: 自足性判据里的「短」阈值（字符数）
SHORT = 20


def load_facts(path):
    """读库文件，返回 active facts 列表。文件缺失时抛 FileNotFoundError，不静默返回空。"""
    data = json.load(io.open(path, encoding='utf-8'))
    return [f for f in data.get('facts', []) if f.get('status') == 'active']


def audit(facts):
    """逐条打标记。返回 list[dict]，每条含原始字段与三个标记。"""
    rows = []
    for f in facts:
        c = (f.get('content') or '').strip()
        pron = [w for w in PRONOUN if w in c]
        once = [w for w in ONCE if w in c]
        rows.append({
            'id': f.get('id'),
            'content': c,
            'imp': f.get('importance', 3),
            'roles': f.get('roles', '<缺省>'),
            'len': len(c),
            'pron': pron,
            'once': once,
            'entity': bool(ENTITY.search(c)),
        })
    return rows


def summarize(rows):
    """统计。所有比例都由长度/计数插值生成，不写死。"""
    n = len(rows)
    denom = max(n, 1)
    return {
        'n': n,
        'pron': sum(1 for r in rows if r['pron']),
        'once': sum(1 for r in rows if r['once']),
        'no_entity': sum(1 for r in rows if not r['entity']),
        'any_flag': sum(1 for r in rows if r['pron'] or r['once'] or not r['entity']),
        'avg_len': sum(r['len'] for r in rows) / float(denom),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description='facts 库体检（候选清单，不替代人判断）')
    ap.add_argument('--memory', default=os.path.join(ROOT, 'memory.json'),
                    help='库文件路径（默认 <仓库根>/memory.json）')
    ap.add_argument('--only-flagged', action='store_true',
                    help='只打印命中标记的条目')
    args = ap.parse_args(argv)

    if not os.path.exists(args.memory):
        raise SystemExit('库文件不存在：%s' % args.memory)

    facts = load_facts(args.memory)
    rows = audit(facts)

    print('库文件：%s' % args.memory)
    print('active facts：%d 条' % len(rows))
    print()
    print('=' * 100)
    print('逐条')
    print('=' * 100)
    for i, r in enumerate(rows, 1):
        flags = []
        if r['pron']:
            flags.append('指代:%s' % ','.join(r['pron']))
        if r['once']:
            flags.append('一次性:%s' % ','.join(r['once'][:2]))
        if not r['entity']:
            flags.append('无具体实体')
        if args.only_flagged and not flags:
            continue
        print('%2d. [%s] imp=%s roles=%-4s len=%-3d %s' % (
            i, (r['id'] or '')[:14], r['imp'], r['roles'], r['len'],
            ('⚠ ' + ' / '.join(flags)) if flags else ''))
        print('    %r' % r['content'])

    s = summarize(rows)
    print()
    print('=' * 100)
    print('统计（分母 = active 条数）')
    print('=' * 100)
    for label, key in (('含指代词', 'pron'), ('含一次性标记', 'once'),
                       ('无具体实体', 'no_entity'), ('任一可疑标记', 'any_flag')):
        print('  %-12s %3d / %-3d = %3.0f%%'
              % (label, s[key], s['n'], 100.0 * s[key] / max(s['n'], 1)))
    print()
    print('  平均长度 %.1f 字符（短阈值 %d）' % (s['avg_len'], SHORT))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
