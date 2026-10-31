# -*- coding: utf-8 -*-
"""通道台账自检：停更 + 漏记 + 撞号

为什么需要它（WX-桌宠-20261031-161 指出）：
    台账原有的三类校验（自述数 / sha256 / 件号连号性）**对照物都在表内部**。
    一个只依赖自身的校验，永远证明不了自己完整。
    实测事故：298~305 八件发出后，台账从 297 直接停更 7.4 小时，
    而那 8 件里有 7 件正是当时双方在讨论的内容 —— 表绿着，同时缺件。

三条判据（都拿表去对表外的东西）：
    A 停更：台账最后一个件行的时刻 vs 通道该线最新文件 mtime
    B 漏记：通道里存在的件，台账没有对应件行
    C 撞号：同一件号在台账里出现多次

⚠ 两个已知坑（161 原文提醒，已处理）：
    ① 号段多线共用 —— 273/274/275 是 PC-量化的号，桌宠表里本来就不该有。
       必须先判断「这个号的件是不是别的线发的」。
    ② 说明区行 / 引用行 列数不足 —— 不能当件行统计。只认 8 列或 7 列的表格行。

用法：
    python tools/check_channel_ledger.py                # 默认查桌宠线
    python tools/check_channel_ledger.py --ledger X.md --line 桌宠
    python tools/check_channel_ledger.py --max-gap-h 12 # 停更阈值

退出码：0 绿 / 1 红（红=漏记或停更超阈值）
"""
import argparse
import datetime
import io
import os
import re
import sys

CHANNEL = r'C:\Users\lby13\AutoClaw\Channel'
DEFAULT_LEDGER = os.path.join(CHANNEL, '00-台账', 'PC-桌宠-收发-202610.md')
PC_DIR = os.path.join(CHANNEL, '01-PC-to-WX')

#: 件行里件号的形状：PC-<线>-<YYYYMMDD>-<NNN>
RE_ITEM = re.compile(r'(PC-([\u4e00-\u9fa5A-Za-z]+)-(\d{8})-(\d{3}))')
#: 通道文件名里同样形状（桌宠线目录下）
RE_FILE = re.compile(r'^(PC-([\u4e00-\u9fa5A-Za-z]+)-(\d{8})-(\d{3}))')


def read_ledger(path):
    """返回 (件行列表, 全部行数)。件行 = 以 | 开头、7 或 8 列、含 PC-* 件号"""
    with io.open(path, encoding='utf-8', newline='') as _f:
        txt = _f.read()
    rows = []
    lines = txt.splitlines()
    for i, line in enumerate(lines, 1):
        if not line.startswith('|'):
            continue
        cells = [c.strip() for c in line.split('|')[1:-1]]
        if len(cells) not in (7, 8):
            continue                     # 坑②：说明区/引用行，不算件行
        item_cell = cells[1] if len(cells) > 1 else ''
        # ⛔ 只认「整格就是一个件号」的行。更正行的件号格长这样：
        #     —（更正行，指向 PC-桌宠-20261023-237）
        #   用 search 会把括号里的件号抓出来，和真正的件行算成同号两次（实测 4 个误报）。
        if not item_cell.startswith('PC-'):
            continue
        m = RE_ITEM.fullmatch(item_cell)
        if not m:
            continue
        rows.append({'line': i, 'ts': cells[0], 'item': m.group(1),
                     'line_name': m.group(2), 'date': m.group(3),
                     'no': m.group(4), 'status': cells[5] if len(cells) > 5 else ''})
    return rows, len(lines)


def scan_channel(line_name):
    """扫通道里该线的所有 PC 件文件 → {件号: (path, mtime)}"""
    out = {}
    for root, _dirs, files in os.walk(PC_DIR):
        for fn in files:
            m = RE_FILE.match(fn)
            if not m:
                continue
            if m.group(2) != line_name:
                continue
            p = os.path.join(root, fn)
            out[m.group(1)] = (p, os.path.getmtime(p))
    return out


def other_line_same_no(line_name, date, no):
    """坑①：这个号是不是别的线的件"""
    hits = []
    for root, _dirs, files in os.walk(PC_DIR):
        for fn in files:
            m = RE_FILE.match(fn)
            if not m:
                continue
            if m.group(2) == line_name:
                continue
            if m.group(3) == date and m.group(4) == no:
                hits.append(m.group(1))
    return hits


def parse_ts(s):
    for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.datetime.strptime(s.strip(), fmt)
        except (ValueError, TypeError):
            continue
    return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--ledger', default=DEFAULT_LEDGER)
    ap.add_argument('--line', default='桌宠', help='线名，用于匹配 PC-<线>- 前缀')
    ap.add_argument('--max-gap-h', type=float, default=12.0)
    args = ap.parse_args(argv)

    if not os.path.exists(args.ledger):
        print('✗ 台账不存在：%s' % args.ledger)
        return 1

    rows, total_lines = read_ledger(args.ledger)
    files = scan_channel(args.line)
    print('台账 %s' % os.path.basename(args.ledger))
    print('  总行 %d，识别到件行 %d 条' % (total_lines, len(rows)))
    print('  通道里 %s线 的件文件 %d 个' % (args.line, len(files)))
    print()

    problems = []

    # ---------- A. 停更 ----------
    stamps = [parse_ts(r['ts']) for r in rows]
    stamps = [t for t in stamps if t]
    print('=== A. 停更检测 ===')
    if not stamps:
        print('  ⚠ 台账里没有可解析的时间戳')
    elif not files:
        print('  ⚠ 通道里没有该线的件文件')
    else:
        last_ledger = max(stamps)
        last_file_ts = max(v[1] for v in files.values())
        last_file = datetime.datetime.fromtimestamp(last_file_ts)
        gap = (last_file - last_ledger).total_seconds() / 3600.0
        print('  台账最后件行：%s' % last_ledger.strftime('%Y-%m-%d %H:%M'))
        print('  通道最新件  ：%s（%s）' % (
            last_file.strftime('%Y-%m-%d %H:%M'),
            os.path.basename(max(files.items(), key=lambda kv: kv[1][1])[0])))
        print('  差值        ：%.1f 小时（阈值 %.0f）' % (gap, args.max_gap_h))
        if gap > args.max_gap_h:
            print('  ✗ 红：台账停更')
            problems.append('停更 %.1f 小时' % gap)
        elif gap > 1.0:
            print('  ⚠ 黄：有间隔，但未超阈值')
        else:
            print('  ✓ 绿')
    print()

    # ---------- B. 漏记 ----------
    print('=== B. 漏记检测：通道有件、台账无行 ===')
    ledger_items = {r['item'] for r in rows}
    missing = []
    for item, (p, _mt) in sorted(files.items()):
        if item in ledger_items:
            continue
        m = RE_ITEM.search(item)
        date, no = m.group(3), m.group(4)
        others = other_line_same_no(args.line, date, no)
        if others:
            print('  · 跳过 %s（同号是别的线：%r）' % (item, others))
            continue
        missing.append((item, p))
    if missing:
        for item, p in missing:
            print('  ✗ %s  %s' % (item, os.path.basename(p)))
        print('  共漏记 %d 件' % len(missing))
        problems.append('漏记 %d 件' % len(missing))
    else:
        print('  ✓ 无漏记')
    print()

    # ---------- C. 撞号 ----------
    print('=== C. 撞号检测：同一件号出现多次 ===')
    seen = {}
    for r in rows:
        seen.setdefault(r['item'], []).append(r['line'])
    dups = {k: v for k, v in seen.items() if len(v) > 1}
    if dups:
        for k, v in dups.items():
            print('  ✗ %s 出现在 L%r' % (k, v))
        problems.append('撞号 %d 个' % len(dups))
    else:
        print('  ✓ 无撞号')

    print()
    if problems:
        print('结论：✗ 红 —— ' + '；'.join(problems))
        return 1
    print('结论：✓ 绿（三条判据全过）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
