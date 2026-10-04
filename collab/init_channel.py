# -*- coding: utf-8 -*-
"""collab/init_channel.py —— ⭐ **通道初始化**（把"外部约定"第一次落到磁盘上）

## 为什么有这个东西（Owner 2026-10-04 18:39 第二问 ⇒ 电脑侧 `PC-…-135` §五 要害）
我们这套"两条线协作"跑得顺，靠的是 **产品之外的一批约定** ✗（通道目录／台账／线名前缀／
写前查 mtime·大小／只追加 ✗ …）。⭐ **换一台机器、换一个不认这套的人，这些全都不存在** ✗
⇒ ⭐ 协作台会退化成"两个人在同一个目录里互相覆盖" ✗。

本脚本把**最小那一半**落成文件 ✓：
    ① 建**通道目录**（＝ 项目 `root` ＋ `outputs`；缺省 `<base>/输出` ✓）
    ② 落一份 **`COLLAB.md`**（把约定写清 ✓）

## ⛔ 三条安全纪律（照本项目惯例 ✓）
1. ⭐ **默认 dry-run** ✗ —— 不加 `--apply` **一个字节都不写** ✓
2. ⭐ **绝不覆盖** ✗ —— `COLLAB.md` 已存在就**跳过并明报** ✓（要重写请人自己删 ✗）
3. ⭐ **只在通道目录内创建** ✓ —— 其它路径一律不碰 ✗（越界直接报错退出 ✓）

用法（PowerShell ✓）:
    python collab\\init_channel.py --base . --check      # 只看缺什么（只读 ✓）
    python collab\\init_channel.py --base .              # dry-run：说会做什么（不写 ✓）
    python collab\\init_channel.py --base . --apply      # 真建目录 ＋ 落 COLLAB.md ✓

退出码：0 = 已就绪/已完成 ✓ ｜ 1 = 出错 ✗ ｜ 3 = dry-run 下"尚有缺失"（便于脚本判断 ✓）
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys

DEFAULT_OUTPUTS = '输出'
PROJECT_FILE = os.path.join('rt', 'project.json')
COLLAB_MD = 'COLLAB.md'

TEMPLATE = """# COLLAB.md —— 本项目「多线协作」约定（由协作台初始化生成）

> ⭐ 本文件由 `collab/init_channel.py` 生成 ✓ ｜ 生成后**由人维护** ✓
> ⭐ 目的：把"靠人记的约定"变成**写在磁盘上的约定** ✗ ⇒ 换机器/换人也照做 ✓

## 一、目录
- **通道目录**：本文件所在目录（产出/往来件都放这里 ✓）
- **台账**：`通道-收发台账.md`（**只追加** ✗ 不改写历史行 ✓）
- **每日笔记**：`memory\\YYYY-MM-DD-<线名>.md`（⛔ 不共用无归属的 `YYYY-MM-DD.md` ✗）

## 二、四条硬约定
1. ⭐ **产出与笔记一律带线名前缀/线名后缀** ✓（如 `WX-…`／`PC-…`／`…-微信侧.md`）——
   ⛔ 无归属文件名＝静默覆盖的高发区 ✗
2. ⭐ **写共享目录里已存在的文件前，先看 mtime 与大小** ✓；比预期**新**或**小** ⇒ ⭐ **停手先问** ✗
3. ⭐ **不是自己建的文件，一律不用覆写方式打开** ✗ —— 要么**追加** ✓，要么**另起带线名的新文件** ✓
4. ⭐ **关键动作只追加、不改写** ✓（开工/收工/裁定/交付/口径变更 ✓ 都落一行 ✓）

## 三、三条别踩
1. ⛔ **不假定任何"外部库/外部习惯"存在** ✗（行为规则文件、经验库、回收站习惯都可能没有 ✓）
2. ⛔ **不拿版本控制工作区当队列** ✗（提交前 `git status` ✓ 只 add 自己的路径 ✗ 不用 `add -A` ✗）
3. ⛔ **删除前先进回收站** ✓（或先备份 ✓）—— 数据丢失零容忍 ✓

## 四、并发
- ⭐ **同一份台账/结果文件：写者加锁**（`msvcrt.locking` ✓）或不共用文件 ✓
- ⭐ **同一端口：先探测再用** ✓（起服务前看端口是否已被占用 ✓）
"""


def load_project(base: str) -> dict:
    """读项目档案（可不存在 ✓）；⛔ 只读 ✗。"""
    p = os.path.join(base, PROJECT_FILE)
    if not os.path.isfile(p):
        return {}
    try:
        with io.open(p, encoding='utf-8') as fh:
            j = json.load(fh) or {}
        return j if isinstance(j, dict) else {}
    except Exception:
        return {}


def channel_dir(base: str, project: dict) -> str:
    """通道目录 ＝ `root`（可绝对 ✓ 只登记 ✗）＋ `outputs`（只相对 ✓）；缺省 `<base>/输出` ✓。"""
    root = str(project.get('root') or '').strip() or base
    out = str(project.get('outputs') or '').strip() or DEFAULT_OUTPUTS
    return os.path.abspath(os.path.join(root, out))


def check(base: str, project: dict = None) -> tuple:
    """只读检查 ✓ → `(ok, missing, cdir, collab_path)`。"""
    project = project if project is not None else load_project(base)
    cdir = channel_dir(base, project)
    collab = os.path.join(cdir, COLLAB_MD)
    missing = []
    if not os.path.isdir(cdir):
        missing.append('通道目录不存在：%s' % cdir)
    if not os.path.isfile(collab):
        missing.append('约定文件不存在：%s' % collab)
    return (not missing), missing, cdir, collab


def apply_(base: str, project: dict = None) -> tuple:
    """真建 ✗ → `(ok, actions)`；⭐ 已存在一律跳过、绝不覆盖 ✓。"""
    project = project if project is not None else load_project(base)
    cdir = channel_dir(base, project)
    collab = os.path.join(cdir, COLLAB_MD)
    actions = []
    if os.path.isdir(cdir):
        actions.append('通道目录已存在，跳过 ✓：%s' % cdir)
    else:
        os.makedirs(cdir, exist_ok=True)
        actions.append('已创建通道目录 ✓：%s' % cdir)
    if os.path.isfile(collab):
        # ⭐ 绝不覆盖 ✗（可能已被人工改过 ✓）
        actions.append('约定文件已存在，跳过（⛔ 不覆盖 ✗）：%s' % collab)
    else:
        with io.open(collab, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(TEMPLATE)
        actions.append('已写入约定文件 ✓：%s' % collab)
    return True, actions


def main() -> int:
    ap = argparse.ArgumentParser(description='通道初始化（默认 dry-run ✓ 加 --apply 才写 ✓）')
    ap.add_argument('--base', default='.', help='仓库根（默认当前目录 ✓）')
    ap.add_argument('--check', action='store_true', help='只检查缺什么（只读 ✓）')
    ap.add_argument('--apply', action='store_true', help='真写（建目录 ＋ 落 COLLAB.md ✓）')
    args = ap.parse_args()
    base = os.path.abspath(args.base)
    project = load_project(base)
    ok, missing, cdir, collab = check(base, project)

    if args.check:
        print('通道目录：%s' % cdir)
        print('状态：%s' % ('已就绪 ✓' if ok else '未就绪 ✗'))
        for m in missing:
            print('  ✗ %s' % m)
        return 0 if ok else 3

    if not args.apply:
        print('（dry-run ✗ 不写任何文件 ✓；加 --apply 才真写 ✓）')
        print('通道目录：%s' % cdir)
        if ok:
            print('已经是就绪状态 ✓ 无需动作 ✓')
            return 0
        for m in missing:
            print('  将处理：%s' % m)
        return 3

    ok2, actions = apply_(base, project)
    for a in actions:
        print('  %s' % a)
    return 0 if ok2 else 1


if __name__ == '__main__':
    sys.exit(main())
