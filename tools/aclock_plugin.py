# -*- coding: utf-8 -*-
"""tools/aclock_plugin.py —— ⭐ pytest 插件：**全量测试自动拿「测试」锁**（E14.9 自动化 ✓）

## 为什么（把"约定"变成"机制" ✓）
`tools/ac_lock.py` 提供了机器锁 ✓，但 ⭐ **要用它得靠人记得** ✗（＝仍是"省一步就会翻车"✗）。
本插件把这一步**焊死在测试入口**：⭐ 只要启用 ⇒ ⭐ **跑全量前自动拿锁** ✓ 跑完自动放 ✓。

## 用法（⭐ 两种，**二选一** ✗ —— ⛔ 别叠加 ✗）
    A) 插件自己拿锁 ✓（推荐 ✓）:
        python -m pytest -p tools.aclock_plugin -q
        AC_LOCK_WAIT=180 python -m pytest -p tools.aclock_plugin -q    # 自定义等待秒数 ✓
    B) 外层 CLI 已拿锁 ✓ ⇒ ⭐ **不要再传 `-p`** ✗（⭐ 叠加会在内层重复抢 ⇒ 等超时 ✗）:
        python tools\\ac_lock.py --name 测试 --wait 120 -- python -m pytest -q
    ⭐ 容错：⭐ 万一叠加了（外层抢着 ✓ 内层又传 `-p` ✓）⇒ ⭐ 插件**会识别“锁被我的父进程持有”并跳过** ✓
        （⛔ 免自我死锁 ✗）

## 行为（⛔ 三条都不静默 ✗）
1. ⭐ 拿不到锁 ⇒ **明确报错并中止** ✗（默认等 `AC_LOCK_WAIT`＝120s ✓），⛔ 不会"悄悄跑"✗
2. ⭐ 已经在锁内（外层 `ac_lock.py` 拿着 ✓）⇒ **识别并跳过** ✗ 重复拿（⛔ 不自我死锁 ✗）
3. ⭐ 结束时**释放自己拿的那把** ✓（⛔ 不放别人的 ✓ —— 由 `ac_lock` 自己保证 ✓）
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.ac_lock import file_lock, lock_path  # noqa: E402

LOCK_NAME = '测试'

_state = {'ctx': None, 'why': ''}


def _holder_pid():
    """⭐ 当前持锁者 pid ✓（读锁文件里的 pid ✓ **只看不抢** ✗）。"""
    p = lock_path(LOCK_NAME)
    try:
        with open(p, encoding='utf-8') as fh:
            txt = fh.read()
    except Exception:
        return None
    import json
    import re
    m = re.search(r'\{.*\}', txt, re.S)
    if not m:
        return None
    try:
        return int(json.loads(m.group(0)).get('pid', -1))
    except Exception:
        return None


def _held_by_me_or_parent() -> bool:
    """⭐ 锁是不是**本进程或我父进程**拿着 ✓

    ⚠️ 自纠：⭐ 第一版只比 `os.getpid()` ✗ ⇒ ⭐ 被 `ac_lock.py` 套着跑时（pytest 是**子进程** ✓）
        ⇒ 认不出来 ⇒ ⛔ 内层重复抢 ⇒ 等超时 **rc=3** ✗（实测逮到 ✓）
        ⇒ ⭐ 加上 `os.getppid()` ✓ 恰好覆盖“`ac_lock.py` 套 pytest”这一真实用法 ✓
    """
    holder = _holder_pid()
    return holder is not None and holder in (os.getpid(), os.getppid())


def pytest_configure(config):
    if _held_by_me_or_parent():
        _state['why'] = '锁已由本进程/父进程持有 ⇒ 跳过重复获取 ✓'
        print('\n🔒 [aclock] %s' % _state['why'])
        return
    wait = float(os.environ.get('AC_LOCK_WAIT', '120') or 120)
    ctx = file_lock(LOCK_NAME, wait=wait)      # ⭐ 拿不到会抛 TimeoutError ✓
    try:
        ctx.__enter__()
    except TimeoutError as e:
        # ⚠️ 自纠：⭐ 第一版用 `raise SystemExit` ✗ ⇒ pytest 把它当 **INTERNALERROR** 打出大段堆栈 ✗
        #    ⇒ ⭐ 改用 `pytest.exit(...)` ✓：**一行清话 ＋ 非零退出码** ✓（⛔ 不静默 ✗）
        import pytest
        pytest.exit('⛔ [aclock] 拿不到「%s」锁 ⇒ 中止本次全量 ✗（%s）'
                    '｜⭐ 另一边正在跑测试 ✓ 等它跑完（或改 AC_LOCK_WAIT ✓）' % (LOCK_NAME, e),
                    returncode=3)
    _state['ctx'] = ctx
    print('\n🔒 [aclock] 已拿锁「%s」✓（等待上限 %ss ✓）' % (LOCK_NAME, wait))


def pytest_unconfigure(config):
    ctx = _state.get('ctx')
    if ctx is not None:
        ctx.__exit__(None, None, None)
        print('\n🔓 [aclock] 已放锁「%s」✓（只放自己那把 ✓）' % LOCK_NAME)
    elif _state.get('why'):
        print('\n🔓 [aclock] 无需放锁：%s' % _state['why'])
