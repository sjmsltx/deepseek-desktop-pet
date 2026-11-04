# -*- coding: utf-8 -*-
"""标签质量抽查（2026-11-04）—— 补上欠的账

## 为什么必须做

我在交接件里自己写了「1411 条标签未人工抽查」。
标出来的 topic/object/aspect 若不抽查就当结论用，等于把模型的输出当基准。

## 抽什么

  A 分层抽样：按 topic 大小分层取（大簇必须查，因为它影响归并）
  B 定向抽查：aspect 与文本明显矛盾的（关键词与枚举冲突）
  C 边界抽查：object 非空但看起来不是专名的

## 判据（机械，不靠主观）

  · aspect=habit 但文本里没有「坚持/一直/年/月/天/每周」类持续词 ⇒ 可疑
  · aspect=change 但文本里没有「以前/现在/变了/转变」类对比词 ⇒ 可疑
  · aspect=struggle 但没有「卡/难/纠结/不会/调很久」类困难词 ⇒ 可疑
  · object 非空但长度 >12 或含「用户/偏好/习惯」⇒ 可疑（不是专名）
  · topic 为空 ⇒ 缺失

抽查结果全部打印原文，供人工复核。
"""
import io
import json
import os
import random
import re
import sys
import collections

REPO = r'D:\ai工作站\desktop-pet'
EXP = os.path.join(REPO, 'tools', 'eval', 'experiment')
RES = os.path.join(EXP, 'results')

LAB = json.loads(io.open(os.path.join(RES, 'library-labels.json'), encoding='utf-8').read())
SYN = json.loads(io.open(os.path.join(EXP, 'data', 'memories-1411.json'),
                        encoding='utf-8').read())['facts']

HABIT_W = ('坚持', '一直', '已经', '年', '个月', '每周', '每天', '基本', '长期', '习惯')
CHANGE_W = ('以前', '现在', '变了', '转变', '不再', '改', '开始', '变化', '后来')
STRUG_W = ('卡', '难', '纠结', '不会', '调了', '弄不', '费劲', '磨', '头疼', '吃力')
BAD_OBJ = ('用户', '偏好', '习惯', '事情')


def suspicious(text, lab):
    """返回可疑原因列表（空 = 通过）"""
    out = []
    a = (lab.get('aspect') or '').strip()
    o = (lab.get('object') or '').strip()
    t = (lab.get('topic') or '').strip()
    if not t:
        out.append('topic 为空')
    if a == 'habit' and not any(w in text for w in HABIT_W):
        out.append('aspect=habit 但无持续词')
    if a == 'change' and not any(w in text for w in CHANGE_W):
        out.append('aspect=change 但无对比词')
    if a == 'struggle' and not any(w in text for w in STRUG_W):
        out.append('aspect=struggle 但无困难词')
    if o and (len(o) > 12 or any(w in o for w in BAD_OBJ)):
        out.append('object 不像专名：%r' % o)
    return out


def main():
    labs = LAB['synth']
    rows = []
    for i, f in enumerate(SYN):
        sid = 'syn-%04d' % i
        L = labs.get(sid) or {}
        if not L:
            continue
        rows.append((sid, (f.get('content') or '').strip(), L))

    print('=' * 100)
    print('总体：%d 条已标' % len(rows))
    print('=' * 100)
    n_bad = 0
    reasons = collections.Counter()
    for _sid, text, L in rows:
        r = suspicious(text, L)
        if r:
            n_bad += 1
            for x in r:
                reasons[x.split('：')[0]] += 1
    print('  机械判据标出可疑 %d 条 = %.1f%%' % (n_bad, 100.0 * n_bad / len(rows)))
    for k, v in reasons.most_common():
        print('    %-28s %d' % (k, v))

    # ---------- A 分层抽样：最大 6 个 topic 各抽 3 条 ----------
    print()
    print('=' * 100)
    print('A 分层抽样：最大 topic 各抽 3 条（人工看归并是否合理）')
    print('=' * 100)
    tc = collections.Counter((L.get('topic') or '') for _s, _t, L in rows)
    for topic, _n in tc.most_common(6):
        members = [(s, t, L) for s, t, L in rows if (L.get('topic') or '') == topic]
        print()
        print('  【%s】共 %d 条，抽 3 条：' % (topic, len(members)))
        for s, t, L in random.Random(hash(topic) & 0xFFFF).sample(
                members, min(3, len(members))):
            print('    [%-7s] %s' % (L.get('aspect', ''), t[:62]))
            print('               object=%r' % (L.get('object') or ''))

    # ---------- B 定向：aspect 可疑 ----------
    print()
    print('=' * 100)
    print('B aspect 可疑样本（前 10 条，看是否真矛盾）')
    print('=' * 100)
    shown = 0
    for s, t, L in rows:
        if any('aspect' in x for x in suspicious(t, L)):
            print('  %s [%s] %s' % (s, L.get('aspect'), t[:66]))
            print('        理由：%s' % '；'.join(x for x in suspicious(t, L) if 'aspect' in x))
            shown += 1
            if shown >= 10:
                break
    if not shown:
        print('  （无）')

    # ---------- C 定向：object 可疑 ----------
    print()
    print('=' * 100)
    print('C object 可疑样本（object 非空但全部列出）')
    print('=' * 100)
    objs = [(s, t, L) for s, t, L in rows if (L.get('object') or '').strip()]
    print('  有 object 的 %d 条（%.1f%%）' % (len(objs), 100.0 * len(objs) / len(rows)))
    for s, t, L in objs[:20]:
        flag = '★' if any('object' in x for x in suspicious(t, L)) else ' '
        print('  %s %-22s %s' % (flag, L.get('object'), t[:52]))

    # ---------- 真实库 21 条人工核 ----------
    print()
    print('=' * 100)
    print('真实库 21 条逐条核对（标错会直接影响结论）')
    print('=' * 100)
    real = [f for f in json.loads(io.open(os.path.join(REPO, 'memory.json'),
                                         encoding='utf-8').read())['facts']
            if f.get('status') == 'active']
    rl = LAB['real']
    rb = 0
    for f in real:
        L = rl.get(f['id']) or {}
        r = suspicious((f.get('content') or ''), L)
        if r:
            rb += 1
        print('  %s [%-10s] %-12s %s'
              % ('★' if r else ' ', L.get('aspect', '')[:10],
                 (L.get('topic') or '')[:12], (f.get('content') or '')[:46]))
        if r:
            print('       可疑：%s' % '；'.join(r))
    print()
    print('  真实库可疑 %d / %d' % (rb, len(real)))

    out = {
        'n_synth': len(rows),
        'synth_suspicious': n_bad,
        'synth_suspicious_pct': round(100.0 * n_bad / len(rows), 1),
        'reasons': dict(reasons),
        'real_suspicious': rb,
        'real_total': len(real),
        'object_coverage_pct': round(100.0 * len(objs) / len(rows), 1),
    }
    p = os.path.join(RES, 'label-audit.json')
    with io.open(p, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(json.dumps(out, ensure_ascii=False, indent=1) + '\n')
    print()
    print('  已写 %s' % p)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
