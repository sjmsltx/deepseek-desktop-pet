# -*- coding: utf-8 -*-
"""⭐ B4 护栏：产出线名前缀（`tools/check_output_prefix.py`）—— D4-1 ③ · 可移植性 P3

缺陷原形 ✗（真实事故）：两条线共用同一目录产出文件 ⇒ ⭐ 文件名不带线名 ⇒
**后写者静默覆盖** ✗（2026-10-04 当日笔记被覆盖，约 4 万字不可取回 ✗）。

本护栏钉住的契约：
    ① ⭐ 带线名前缀（`WX-`／`PC-`）的产出**一律通过** ✓
    ② ⭐ 无前缀产出**必须判红** ✓（并**列出文件名** ✓ ⛔ 不静默 ✗）
    ③ ⭐ 例外**只能显式登记** ✓（`COLLAB.md`／台账 等 ✓）；⛔ 不许"看着像就放过" ✗
    ④ ⭐ 基线冻结：⭐ **只判"新增"** ✓（存量不判红 ✗ 否则一上来红一片没人看 ✗）
    ⑤ ⭐ ⛔ **不写死任何机器路径** ✗（只吃 `--dir` ✓）—— 测试全用**临时目录** ✓
"""
from __future__ import annotations

import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, 'tools'))

import check_output_prefix as chk  # noqa: E402


def _mk(tmp_path, *names):
    for n in names:
        p = tmp_path / n
        p.parent.mkdir(parents=True, exist_ok=True)
        io.open(p, 'w', encoding='utf-8').write('x\n')
    return str(tmp_path)


def test_带前缀全绿(tmp_path):
    root = _mk(tmp_path, 'WX-桌宠-20261004-30-提请.md', 'PC-桌宠-20261004-134-回件.md', 'COLLAB.md')
    assert chk.scan(root) == [], '带前缀 ＋ 显式登记的约定文件竟然判红 ✗'


def test_无前缀判红且列出文件名(tmp_path):
    root = _mk(tmp_path, 'WX-a.md', '随手写的笔记.md')
    bad = chk.scan(root)
    assert bad == ['随手写的笔记.md'], bad


def test_日期件默认豁免_strict_下判红(tmp_path):
    root = _mk(tmp_path, '2026-10-05.md')
    assert chk.scan(root) == [], '日期件默认应豁免（旧件很多 ✓）✗'
    assert chk.scan(root, strict_dates=True) == ['2026-10-05.md'], '--strict-dates 下应判红 ✗'


def test_基线只判新增(tmp_path):
    root = _mk(tmp_path, 'old.md', 'WX-new.md')
    base = {'known': ['old.md']}
    new, known = chk.split_new(chk.scan(root), base)
    assert new == [] and known == ['old.md'], (new, known)
    _mk(tmp_path, 'another.md')
    new2, _ = chk.split_new(chk.scan(root), base)
    assert new2 == ['another.md'], new2


def test_递归可选(tmp_path):
    root = _mk(tmp_path, 'sub/无前缀.md', 'WX-top.md')
    assert chk.scan(root) == [], '非递归时不该进子目录 ✗'
    assert chk.scan(root, recursive=True) == ['sub/无前缀.md'], chk.scan(root, recursive=True)


def test_freeze_落盘且可复用(tmp_path):
    # ⚠️ 自纠：基线文件**不能放在被扫目录里** ✗ —— 否则它自己就是一条"无前缀产出" ✗
    root = _mk(tmp_path / 'chan', 'a.md', 'b.md')
    bp = str(tmp_path / '_base.json')
    sys.argv = ['x', '--dir', root, '--freeze', bp]
    assert chk.main() == 0
    with io.open(bp, encoding='utf-8') as fh:
        assert json.load(fh)['known'] == ['a.md', 'b.md']
    sys.argv = ['x', '--dir', root, '--baseline', bp]
    assert chk.main() == 0, '基线内应全绿 ✗'


def test_目录不存在返回2():
    sys.argv = ['x', '--dir', 'Z:\\不存在的目录-xyz']
    assert chk.main() == 2
