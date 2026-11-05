# -*- coding: utf-8 -*-
"""通道台账自检脚本的回归测试（评审-161 的两个已知坑）

C1. 更正行/状态更新行不能被当成件行
    —— 它们的件号格长这样：`—（更正行，指向 PC-桌宠-20261023-237）`
       用 search 会把括号里的件号抓出来，和真正的件行算成「同号两次」。
       实测（2026-10-31）误报 4 个。
C2. 号段多线共用：同一号是别的线发的，不能算本线漏记
    —— 273/274/275 是 PC-量化的号。
C3. 真漏记要能抓到（用「通道有件、台账无行」构造）
"""
import io
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'tools'))

import check_channel_ledger as ck  # noqa: E402

HEADER = '| 日期时间 | 件号 | 方向 | 类型 | 标题 | 状态 | 备注 | 件所属线 |'


def _w(tmp_path, name, text):
    p = tmp_path / name
    io.open(str(p), 'w', encoding='utf-8', newline='\n').write(text)
    return str(p)


def _row(ts, item, typ='回件', title='t', status='已发出', note='n', line='桌宠线'):
    return '| %s | %s | PC→WX | %s | %s | %s | %s | %s |' % (ts, item, typ, title, status, note, line)


# ---------- C1 ----------
def test_correction_row_not_counted_as_item(tmp_path):
    txt = '\n'.join([
        HEADER,
        _row('2026-10-23 10:00', 'PC-桌宠-20261023-237'),
        # 更正行：件号格里是被指向的件号（括号内），不该算件行
        '| 2026-10-23 11:00 | —（更正行，指向 PC-桌宠-20261023-237） | — | 更正 | x | 已更正 | y | 桌宠线 |',
    ])
    p = _w(tmp_path, 'led.md', txt)
    rows, total = ck.read_ledger(p)
    assert len(rows) == 1, '更正行被算成件行了：%r' % [r['item'] for r in rows]
    assert rows[0]['item'] == 'PC-桌宠-20261023-237'


def test_no_false_duplicate_from_correction_row(tmp_path):
    """C1 的直接后果：撞号检测不许把「件行 + 指向它的更正行」报成撞号"""
    txt = '\n'.join([
        HEADER,
        _row('2026-10-23 10:00', 'PC-桌宠-20261023-237'),
        '| 2026-10-23 11:00 | —（更正行，指向 PC-桌宠-20261023-237） | — | 更正 | x | 已更正 | y | 桌宠线 |',
    ])
    p = _w(tmp_path, 'led.md', txt)
    rows, _ = ck.read_ledger(p)
    seen = {}
    for r in rows:
        seen.setdefault(r['item'], []).append(r['line'])
    dups = {k: v for k, v in seen.items() if len(v) > 1}
    assert not dups, '误报撞号：%r' % dups


def test_row_with_wrong_column_count_skipped(tmp_path):
    """列数不足的说明区行不算件行（161 原文的坑②）"""
    txt = '\n'.join([
        HEADER,
        '| 拆分依据 | `评审-148` §2.1 |',        # 2 列
        _row('2026-10-29 10:00', 'PC-桌宠-20261029-287'),
    ])
    p = _w(tmp_path, 'led.md', txt)
    rows, _ = ck.read_ledger(p)
    assert len(rows) == 1, '说明区行被算进件行了'
    assert rows[0]['item'] == 'PC-桌宠-20261029-287'


# ---------- C2 ----------
def test_other_line_same_number_detected(tmp_path, monkeypatch):
    """C2：同号是别的线的件 → 不算本线漏记"""
    ch = tmp_path / 'channel'
    pc = ch / '01-PC-to-WX' / '桌宠'
    pc.mkdir(parents=True)
    # 只有量化线有这个号的文件
    q = ch / '01-PC-to-WX' / '量化'
    q.mkdir(parents=True)
    io.open(str(q / 'PC-量化-20261029-273-x.md'), 'w', encoding='utf-8').write('x')

    monkeypatch.setattr(ck, 'PC_DIR', str(ch / '01-PC-to-WX'))
    hits = ck.other_line_same_no('桌宠', '20261029', '273')
    assert hits == ['PC-量化-20261029-273'], '没认出这是别的线的号：%r' % hits


def test_same_number_on_own_line_is_not_other_line(tmp_path, monkeypatch):
    ch = tmp_path / 'channel'
    pc = ch / '01-PC-to-WX' / '桌宠'
    pc.mkdir(parents=True)
    io.open(str(pc / 'PC-桌宠-20261029-300-x.md'), 'w', encoding='utf-8').write('x')
    monkeypatch.setattr(ck, 'PC_DIR', str(ch / '01-PC-to-WX'))
    assert ck.other_line_same_no('桌宠', '20261029', '300') == [], \
        '本线的号被误判成别的线'


# ---------- C3 ----------
def test_missing_item_is_detected(tmp_path, monkeypatch):
    """C3：通道有件、台账无行 → 必须报出来"""
    ch = tmp_path / 'channel'
    pc = ch / '01-PC-to-WX' / '桌宠'
    pc.mkdir(parents=True)
    io.open(str(pc / 'PC-桌宠-20261031-298-a.md'), 'w', encoding='utf-8').write('x')
    io.open(str(pc / 'PC-桌宠-20261031-299-b.md'), 'w', encoding='utf-8').write('x')

    led = _w(tmp_path, 'led.md', '\n'.join([
        HEADER,
        _row('2026-10-31 12:00', 'PC-桌宠-20261031-297'),
    ]))
    monkeypatch.setattr(ck, 'PC_DIR', str(ch / '01-PC-to-WX'))
    rc = ck.main(['--ledger', led, '--line', '桌宠', '--max-gap-h', '999'])
    assert rc == 1, '有漏记时退出码应为 1（红）'


def test_complete_ledger_is_green(tmp_path, monkeypatch):
    ch = tmp_path / 'channel'
    pc = ch / '01-PC-to-WX' / '桌宠'
    pc.mkdir(parents=True)
    io.open(str(pc / 'PC-桌宠-20261031-298-a.md'), 'w', encoding='utf-8').write('x')
    led = _w(tmp_path, 'led.md', '\n'.join([
        HEADER,
        _row('2026-10-31 12:00', 'PC-桌宠-20261031-298'),
    ]))
    monkeypatch.setattr(ck, 'PC_DIR', str(ch / '01-PC-to-WX'))
    rc = ck.main(['--ledger', led, '--line', '桌宠', '--max-gap-h', '999'])
    assert rc == 0, '台账齐全时退出码应为 0'
