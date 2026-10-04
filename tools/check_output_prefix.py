# -*- coding: utf-8 -*-
"""tools/check_output_prefix.py —— ⭐ **产出线名前缀护栏**（D4-1 ③ · 可移植性 P3）

## 为什么（真实事故 ⇒ 不是假想）
两条 AI 线**共用同一个目录**产出文件；⭐ 一旦文件名不带**线名**，
⭐ 后写者会**静默覆盖**前者 ✗（2026-10-04 已真实发生：当日笔记被另一条线覆盖，
约 4 万字**不可取回** ✗）。

⭐ 判据很朴素但很硬：**产出文件名必须带线名前缀** ✓（`WX-`／`PC-` ✓）。
⛔ 例外要**显式登记**（如 `COLLAB.md`／台账／索引 ✓）—— ⛔ 不许"看着像就算了" ✗。

## 为什么不做成"只查某个固定目录"
⭐ **可移植性要点**（`PC-…-135` §五）：⛔ 不许把某台机器上的绝对路径写死进产品/测试 ✗
⇒ 本工具**只接受 `--dir` 参数** ✓；⭐ 测试用**临时目录**证"护栏有牙" ✓，不依赖外部路径 ✓。

用法（PowerShell ✓）:
    python tools\\check_output_prefix.py --dir <通道目录>               # 只看报告（0=干净 1=有违规）
    python tools\\check_output_prefix.py --dir <通道目录> --recursive   # 连子目录一起查
    python tools\\check_output_prefix.py --dir <通道目录> --baseline base.json   # 只判"新增"（存量豁免）
    python tools\\check_output_prefix.py --dir <通道目录> --freeze base.json     # 冻结当前状态为基线

退出码：0 = 干净 ✓ ｜ 1 = 有**未登记的无前缀产出** ✗ ｜ 2 = 用法/IO 错
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys

DEFAULT_PREFIXES = ('WX-', 'PC-')
# ⭐ 显式豁免（非"产出件"的约定文件 ✓）—— 维护它就是要**动手登记** ✓ 而不是放过 ✗
ALLOW_NAMES = {
    'COLLAB.md', 'README.md', '通道-收发台账.md', '日志互链-20261004.md',
}
ALLOW_PATTERNS = (
    r'^\d{4}-\d{2}-\d{2}.*\.(md|html|json)$',     # 旧的无归属日期件：先豁免，见 --strict-dates
)


def has_prefix(name: str, prefixes) -> bool:
    return any(name.startswith(p) for p in prefixes)


def is_allowed(name: str) -> bool:
    if name in ALLOW_NAMES:
        return True
    return any(re.match(p, name) for p in ALLOW_PATTERNS)


def scan(root: str, prefixes=DEFAULT_PREFIXES, recursive=False, strict_dates=False):
    """返回违规文件相对路径列表 ✓（⛔ 不改任何文件 ✗）。"""
    bad = []
    if not os.path.isdir(root):
        raise FileNotFoundError('目录不存在：%s' % root)
    # ⚠️ 自纠（2026-10-04）：第一版写成 `[('', [], …)]` ✗ → `os.path.join('', fn)` 相对**当前工作目录**
    #   而不是 `root` ✗ ⇒ `isfile` 全假 ⇒ **一律返回空** ✗（＝跛脚护栏：永远全绿 ✗）
    it = os.walk(root) if recursive else [(root, [], sorted(os.listdir(root)))]
    for dp, _dns, fns in it:
        for fn in fns:
            if not os.path.isfile(os.path.join(dp, fn)):
                continue
            if has_prefix(fn, prefixes):
                continue
            if not strict_dates and is_allowed(fn):
                continue
            if strict_dates and is_allowed(fn) and fn not in ALLOW_NAMES:
                pass
            rel = os.path.relpath(os.path.join(dp, fn), root).replace(os.sep, '/')
            bad.append(rel)
    return sorted(bad)


def split_new(items, baseline):
    """⭐ 基线冻结：只判**新增**违规 ✓（存量不判红 —— 否则一上来就红一片 ✗ 没人看 ✗）。"""
    if baseline is None:
        return list(items), []
    known = set(baseline.get('known', []))
    new = [i for i in items if i not in known]
    return new, sorted(known)


def main() -> int:
    ap = argparse.ArgumentParser(description='产出线名前缀护栏（默认只报告 ✓）')
    ap.add_argument('--dir', required=True, help='要检查的目录（⛔ 不写死路径 ✗）')
    ap.add_argument('--prefix', action='append', default=None, help='允许的线名前缀（可多次 ✓）')
    ap.add_argument('--recursive', action='store_true', help='连子目录一起查 ✓')
    ap.add_argument('--baseline', help='基线 json（只判新增 ✓）')
    ap.add_argument('--freeze', help='把当前违规冻结为基线（写 json ✓）')
    ap.add_argument('--strict-dates', action='store_true', help='日期件也不再豁免 ✓')
    args = ap.parse_args()

    prefixes = tuple(args.prefix) if args.prefix else DEFAULT_PREFIXES
    try:
        bad = scan(args.dir, prefixes, args.recursive, args.strict_dates)
    except FileNotFoundError as exc:
        print('✗ %s' % exc)
        return 2

    if args.freeze:
        with io.open(args.freeze, 'w', encoding='utf-8') as fh:
            json.dump({'known': bad}, fh, ensure_ascii=False, indent=1)
        print('已冻结基线：%s（%d 条存量）' % (args.freeze, len(bad)))
        return 0

    base = None
    if args.baseline and os.path.isfile(args.baseline):
        with io.open(args.baseline, encoding='utf-8') as fh:
            base = json.load(fh)
    new, known = split_new(bad, base)

    print('目录：%s' % os.path.abspath(args.dir))
    print('允许前缀：%s' % ' '.join(prefixes))
    if base is not None:
        print('基线内已知：%d 条 ✓；本次新增：%d 条' % (len(known), len(new)))
    if not new:
        print('⭐ 无未登记的无前缀产出 ✓')
        return 0
    print('⛔ 新增无前缀产出 %d 条 ✗（同名易被另一条线静默覆盖 ✗）：' % len(new))
    for it in new:
        print('   %s' % it)
    print('⭐ 处置：改名带线名前缀 ✓ 或**显式登记**到允许清单（须有理由 ✓）；⛔ 不许直接 freeze 了事 ✗')
    return 1


if __name__ == '__main__':
    sys.exit(main())
