# -*- coding: utf-8 -*-
"""tools/quick_check.py —— ⭐ 「快集」一键（⭐ 秒级反馈 ✓ vs 全量分钟级 ✓）

## 为什么（承我方 `-51` §三 观察 2 ✓）
⭐ 全量已 **1200+ 条 / 4.5 分钟** ✗ 且仍在涨 ⇒ ⭐ 若每次改完都跑全量，⭐ 一天跑不了几轮 ✗。
⇒ ⭐ **分两层**：⭐ **快集**（静态护栏 ＋ 契约用例，⭐ 秒级 ✓）日常用 ✓；⭐ **全量**（含端到端）⭐ 提交前用 ✓。

## 口径（⭐ 快集必须"够快且不骗人" ✗）
- ⭐ 快集只放 ⭐ **纯静态／无副作用** 的用例 ✓（⛔ 不起服务 ✗ ⛔ 不起进程 ✗）＝ 与"⭐ 用例不得真起服务"纪律一致 ✓
- ⭐ 快集**绿 ≠ 全量绿** ✗ —— ⭐ 所以必须**明说**"⭐ 快集不替代全量" ✓（⛔ 不得让人误以为过了就能提交 ✗）

用法（PowerShell ✓）:
    python tools\\quick_check.py                  # 快集（秒级 ✓）
    python tools\\quick_check.py --list           # 只列快集包含哪些 ✓
    python tools\\quick_check.py --full           # 直接转全量（拿锁 ✓ 分钟级）
退出码：0 = 快集全绿 ✓ ｜ 1 = 有红 ✗
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ⭐ 快集内容（⭐ 全部静态／无副作用 ✓）—— 新增请**先确认不起服务/不起进程** ✗
FAST_SELFTESTS = [
    'tests/test_collab_conn_lamp.py',
    'tests/test_collab_starter.py',
    'tests/test_collab_terms.py',
    'tests/test_output_prefix_guard.py',
]
FAST_TESTS = [
    'tests/test_collab_init_channel.py',
    'tests/test_collab_endpoints.py',
    'tests/test_term_consistency.py',
    'tests/test_product_open_hygiene.py',
    'tests/test_silent_guard.py',
]


def sh(args, cwd=REPO, **kw):
    return subprocess.run(args, cwd=cwd, **kw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--list', action='store_true', help='只列快集内容 ✓')
    ap.add_argument('--full', action='store_true', help='转全量（拿锁 ✓）')
    ap.add_argument('--port', type=int, default=8899)
    a = ap.parse_args()

    if a.full:
        print('=== 转全量（⭐ 拿"测试"锁 ✓ 分钟级 ✓）===')
        return sh([sys.executable, os.path.join(REPO, 'tools', 'ac_lock.py'),
                   '--name', '测试', '--wait', '180', '--',
                   sys.executable, '-m', 'pytest', '-q']).returncode

    if a.list:
        print('快集 · 静态护栏自测（--selftest ✓）：')
        for f in FAST_SELFTESTS:
            print('   ' + f)
        print('快集 · 静态用例（pytest ✓）：')
        for f in FAST_TESTS:
            print('   ' + f)
        print('\n⭐ 快集不替代全量 ✗ —— 提交前请 `python tools\\quick_check.py --full` ✓')
        return 0

    bad = 0
    print('=== 快集（秒级 ✓）| ⭐ 不替代全量 ✗ ===')
    for f in FAST_SELFTESTS:
        p = os.path.join(REPO, f)
        if not os.path.isfile(p):
            print('   ⚠️ 缺件，跳过：%s' % f)
            continue
        r = sh([sys.executable, p, '--selftest'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        ok = (r.returncode == 0)
        print('   %s %-46s %s' % ('✓' if ok else '✗', f, '有牙自测通过 ✓' if ok else '判红 ✗'))
        if not ok:
            bad += 1
            print((r.stdout or '')[-400:])

    exist = [f for f in FAST_TESTS if os.path.isfile(os.path.join(REPO, f))]
    if exist:
        r = sh([sys.executable, '-m', 'pytest', '-q'] + exist, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        # ⚠️ 自纠：⭐ `-p tools.aclock_plugin` 默认开启后 ⇒ 末行可能是插件的“已放锁” ✗
        #    ⇒ ⭐ 只取含 passed/failed 的那行 ✓（否则汇总行看不清 ✓）
        lines = [l.strip() for l in (r.stdout or '').splitlines() if l.strip()]
        summ = [l for l in lines if ('passed' in l or 'failed' in l or 'error' in l.lower())]
        tail = (summ[-1:] or lines[-1:] or [''])[0]
        print('   %s 静态用例 %d 个文件 ⇒ %s' % ('✓' if r.returncode == 0 else '✗', len(exist), tail[:90]))
        if r.returncode != 0:
            bad += 1
            print((r.stdout or '')[-600:])

    print('\n=== 快集结论：%s ===' % ('⭐ 全绿 ✓' if not bad else '✗ 有红 %d 处' % bad))
    print('⭐ 提醒：⭐ 快集不替代全量 ✗ —— 提交前跑 `python tools\\quick_check.py --full` ✓（拿锁 ✓）')
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
