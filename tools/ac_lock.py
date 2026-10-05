# -*- coding: utf-8 -*-
"""⭐ B3：跨进程**文件锁** —— 台账写入 ＋ 测试运行**共用一把** ✓（含 E14.9 ✓）

⭐ 为什么需要（2026-10-04 真实事故 ✓）：
  · ⭐ **同一份台账被两线并发追加** ✗（⭐ 异常行虽 0，但"谁先谁后"无法保证 ✓）
  · ⭐ ⭐ **两个 `pytest` 并发** ✗ ⇒ 临时目录／端口／状态文件互撞 ⇒ ⭐ 我方实测 **11 条红** ✗
  ⇒ ⭐ ⭐ **不只文件会撞，"测试运行"也会撞** ✓（E14.9 ✓）

⭐ 设计（⭐ 采纳微信侧 `WX-…-20261004-36` §二 意见 ✓）：
  · ⭐ 锁文件里 ⭐ **写入 `pid` ＋ 时间戳** ✗ —— ⛔ **不用"文件存在即锁"** ✗（⭐ 崩溃会留死锁 ✓）
  · ⭐ 持锁进程**已不存在** ⇒ ⭐ **自动回收** ✓（⭐ 记痕 ✓）
  · ⭐ 超过 `stale` 秒未刷新 ⇒ ⭐ 视为死锁、**可抢占** ✓（⭐ 记痕 ✓）
  · ⭐ **自己拿的锁只能自己放** ✓（⛔ 不误删他人的 ✓）

用法（⭐ 命令行 ✓ 最省事 ✓）：
    python tools/ac_lock.py --name 台账 --wait 20 -- <命令...>
    python tools/ac_lock.py --name 测试 --wait 60 -- python -m pytest -q

用法（⭐ 代码内 ✓）：
    from tools.ac_lock import file_lock
    with file_lock('台账', wait=20):
        ...写台账...
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import time

DEFAULT_STALE = 300.0          # ⭐ 超过这么久未刷新 ⇒ 视为死锁、可抢占 ✓


def _lock_dir() -> str:
    """⭐ 锁文件目录：⭐ `AC_LOCK_DIR` → 系统临时目录 ✓（⛔ 不写进仓库 ✗）。"""
    d = (os.environ.get('AC_LOCK_DIR') or '').strip()
    if not d:
        d = os.path.join(os.environ.get('TEMP') or os.environ.get('TMP') or '/tmp', 'ac_locks')
    os.makedirs(d, exist_ok=True)
    return d


def lock_path(name: str) -> str:
    safe = ''.join(ch if (ch.isalnum() or ch in '-_.') else '_' for ch in str(name or 'default'))
    return os.path.join(_lock_dir(), '%s.lock' % safe)


def _pid_alive(pid: int) -> bool:
    """⭐ 该 pid 是否还活着 ✓（⭐ 判不了就**当活着** ✗ ⇒ 宁可等待也不误抢 ✓）。"""
    if not pid or pid <= 0:
        return False
    try:
        if os.name == 'nt':
            out = subprocess.run(['tasklist', '/FI', 'PID eq %d' % pid],
                                 capture_output=True, text=True, timeout=8)
            return str(pid) in (out.stdout or '')
        os.kill(pid, 0)
        return True
    except Exception:
        return True


def acquire(name: str, wait: float = 0.0, stale: float = DEFAULT_STALE,
            poll: float = 0.2, note: str = ''):
    """⭐ 拿锁 ✓。返回锁文件路径；⭐ 拿不到 ⇒ 抛 `TimeoutError` ✗（⛔ 不静默继续 ✗）。"""
    p = lock_path(name)
    me = os.getpid()
    deadline = time.time() + max(0.0, float(wait))
    while True:
        try:
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            # ⭐ 已被占：⭐ 看持有者是否还活着 ✗ / 是否超时 ✗
            info = {}
            try:
                with io.open(p, encoding='utf-8') as fh:
                    info = json.load(fh) or {}
            except Exception as exc:
                print('  \u26a0\ufe0f 读锁信息失败（按"可能有主"处理）：%r' % (exc,))
            holder = int(info.get('pid') or 0)
            born = float(info.get('ts') or 0)
            dead = not _pid_alive(holder)
            old = (time.time() - born) > stale if born else True
            if dead or old:
                # ⭐ 回收（⭐ 记痕 ✓ 明说为什么抢 ✓）
                why = '持有者已退出' if dead else '超过 %ds 未刷新' % int(stale)
                print('  \u2139\ufe0f 回收锁 %r（%s ✓；原持有者 pid=%s）' % (name, why, holder or '?'))
                try:
                    os.remove(p)
                except OSError as exc:
                    print('  \u26a0\ufe0f 删旧锁失败：%r' % (exc,))
                continue
            if time.time() >= deadline:
                raise TimeoutError('锁 %r 被 pid=%s 占用（等 %.1fs 超时；⛔ 不静默继续 ✗）'
                                   % (name, holder or '?', wait))
            time.sleep(poll)
            continue
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump({'pid': me, 'ts': time.time(), 'note': note,
                       'who': '%s@%s' % (os.getpid(), os.environ.get('AC_COLLAB_LINE') or '')},
                      fh)
        return p


def release(name: str, path: str = ''):
    """⭐ 放锁 ✓ —— ⭐ **只放自己的** ✗（⛔ 不误删他人的 ✓）。"""
    p = path or lock_path(name)
    try:
        with io.open(p, encoding='utf-8') as fh:
            info = json.load(fh) or {}
        if int(info.get('pid') or 0) != os.getpid():
            print('  \u26a0\ufe0f 锁 %r 不是本进程持有（不删 ✓）' % (name,))
            return False
    except Exception as exc:
        print('  \u26a0\ufe0f 读锁失败（不删 ✓）：%r' % (exc,))
        return False
    try:
        os.remove(p)
        return True
    except OSError as exc:
        print('  \u26a0\ufe0f 删锁失败：%r' % (exc,))
        return False


class file_lock:
    """⭐ 上下文管理器 ✓：`with file_lock('台账', wait=20): ...` ✓"""

    def __init__(self, name: str, wait: float = 0.0, stale: float = DEFAULT_STALE,
                 note: str = ''):
        self.name, self.wait, self.stale, self.note = name, wait, stale, note
        self.path = ''

    def __enter__(self):
        self.path = acquire(self.name, wait=self.wait, stale=self.stale, note=self.note)
        return self.path

    def __exit__(self, *exc):
        release(self.name, self.path)
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='⭐ 跨进程文件锁（台账写入 / 测试运行 共用）')
    ap.add_argument('--name', required=True, help='锁名（如 台账 / 测试）')
    ap.add_argument('--wait', type=float, default=0.0, help='最多等多少秒（默认 0）')
    ap.add_argument('--stale', type=float, default=DEFAULT_STALE, help='死锁判定秒数')
    ap.add_argument('--note', default='', help='备注（写进锁文件）')
    ap.add_argument('cmd', nargs=argparse.REMAINDER, help='-- 之后是要在锁内跑的命令')
    a = ap.parse_args(argv)
    cmd = [c for c in a.cmd if c != '--']
    if not cmd:
        print('⛔ 没给命令 ✗（用法：--name X -- <命令...>）')
        return 2
    try:
        with file_lock(a.name, wait=a.wait, stale=a.stale, note=a.note):
            print('🔒 已拿锁 %r ✓ 开始执行：%s' % (a.name, ' '.join(cmd[:4])))
            r = subprocess.run(cmd)
            print('🔓 释放锁 %r ✓（子进程 rc=%d）' % (a.name, r.returncode))
            return r.returncode
    except TimeoutError as e:
        print('⛔ %s' % e)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
