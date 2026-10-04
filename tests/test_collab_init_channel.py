# -*- coding: utf-8 -*-
"""⭐ A3+ 护栏：通道初始化（`collab/init_channel.py`）

沿革：Owner 2026-10-04 18:39 第二问 ⇒ 电脑侧 `PC-…-135` §五 **可移植性要害** ——
      协作靠的是**产品之外的一批约定** ✗（通道目录／台账／线名／写前查 …）⇒ 换机器就没了 ✗。

本护栏钉住的**契约**（行为 ✓ 不写死实现细节 ✗）：
    ① ⭐ **默认不写盘** ✗ —— 不加 `--apply` **一个字节都不产生** ✓（dry-run 是默认 ✓）
    ② ⭐ **绝不覆盖** ✗ —— `COLLAB.md` 已存在 ⇒ **原样保留** ✓ 且**明报跳过** ✓（⛔ 不静默 ✗）
    ③ ⭐ **幂等** ✓ —— 连跑两次结果一致 ✓（第二次全部跳过 ✓）
    ④ ⭐ **只在通道目录内创建** ✓（⛔ 不越界写其它路径 ✗）
    ⑤ ⭐ `COLLAB.md` 必须**写全四条硬约定**（线名 ✓ 写前查 mtime·大小 ✓ 非自建文件不覆写 ✓ 只追加 ✓）
       ＋ **三条别踩**（不假定外部库 ✗ 不拿工作区当队列 ✗ 删除进回收站 ✓）
    ⑥ ⭐ **只读检查**（`--check`）可用 ✓：未就绪时**报出缺什么** ✗ 不静默 ✓
"""
from __future__ import annotations

import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, 'collab'))

import init_channel as ic  # noqa: E402


def test_check_报告缺失(tmp_path):
    base = str(tmp_path)
    ok, missing, cdir, collab = ic.check(base)
    assert not ok, '空目录竟然报"已就绪" ✗'
    assert any('通道目录' in m for m in missing), missing
    assert cdir.endswith(ic.DEFAULT_OUTPUTS), cdir
    assert collab.endswith(ic.COLLAB_MD), collab


def test_默认不写盘(tmp_path, monkeypatch, capsys):
    base = str(tmp_path)
    monkeypatch.setattr(sys, 'argv', ['init_channel.py', '--base', base])
    rc = ic.main()
    out = capsys.readouterr().out
    assert rc == 3, '未就绪时 dry-run 应返回 3 ✗（实际 %r）' % rc
    assert not os.path.isdir(os.path.join(base, ic.DEFAULT_OUTPUTS)), '⭐ dry-run 竟然建了目录 ✗'
    assert 'dry-run' in out, out


def test_apply_建成并写全约定(tmp_path):
    base = str(tmp_path)
    ok, actions = ic.apply_(base)
    assert ok and actions, actions
    ok2, missing, cdir, collab = ic.check(base)
    assert ok2 and not missing, missing
    txt = io.open(collab, encoding='utf-8').read()
    for key in ('线名前缀', 'mtime', '大小', '覆写', '只追加', '不假定', '工作区当队列', '回收站'):
        assert key in txt, '约定文件缺关键条款：%s ✗' % key
    # ④ 只在通道目录内
    created = [os.path.join(dp, f) for dp, _, fs in os.walk(base) for f in fs]
    assert all(os.path.abspath(p).startswith(cdir) for p in created), created


def test_绝不覆盖且幂等(tmp_path):
    base = str(tmp_path)
    ic.apply_(base)
    _, _, cdir, collab = ic.check(base)
    io.open(collab, 'w', encoding='utf-8').write('人工改过的内容 ✓')
    ok, actions = ic.apply_(base)          # 再跑一次
    assert ok, actions
    assert io.open(collab, encoding='utf-8').read() == '人工改过的内容 ✓', \
        '⭐ 竟然覆盖了已存在的约定文件 ✗'
    assert any('不覆盖' in a or '跳过' in a for a in actions), actions


def test_档案_root_outputs_生效(tmp_path):
    base = tmp_path
    (base / 'rt').mkdir()
    io.open(base / 'rt' / 'project.json', 'w', encoding='utf-8').write(
        '{"id":"t","name":"t","outputs":"我的通道"}')
    proj = ic.load_project(str(base))
    assert ic.channel_dir(str(base), proj).endswith('我的通道'), ic.channel_dir(str(base), proj)
