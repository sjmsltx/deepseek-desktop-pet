# -*- coding: utf-8 -*-
"""⭐ B3：跨进程文件锁护栏（台账写入 ＋ 测试运行 共用 ✓ 含 E14.9 ✓）。

⭐ 口径（⭐ 采纳微信侧 `WX-…-20261004-36` §二 意见 ✓）：
  · ⭐ 锁文件**写 `pid`** ✗ —— ⛔ 不用"文件存在即锁" ✗（崩溃会留死锁 ✓）
  · ⭐ 持锁进程**已退出** ⇒ 自动回收 ✓；⭐ 超时未刷新 ⇒ 可抢占 ✓
  · ⭐ **自己拿的锁只能自己放** ✗（⛔ 不误删他人的 ✓）
  · ⭐ 锁文件 ⛔ **不写进仓库** ✗（在系统临时目录 ✓）
"""
import io
import json
import os
import subprocess
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ⭐ `tools/` **不是包** ✗（无 `__init__.py` ✓）⇒ ⭐ 按文件路径加载 ✓（⛔ 不为此加 `__init__.py` ✗
#   —— ⭐ 那会改变打包语义 ✓）
import importlib.util as _ilu  # noqa: E402

_spec = _ilu.spec_from_file_location('ac_lock', os.path.join(ROOT, 'tools', 'ac_lock.py'))
ac_lock = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(ac_lock)


@pytest.fixture(autouse=True)
def _tmp_lock_dir(tmp_path, monkeypatch):
    """⭐ 每个用例用**自己的**锁目录 ✓（⛔ 不污染真实临时目录 ✗；monkeypatch 自动还原 ✓）。"""
    monkeypatch.setenv('AC_LOCK_DIR', str(tmp_path / 'locks'))


def test_acquire_release_roundtrip():
    """⭐ 拿锁 ⇒ 锁文件里**必须有 pid** ✗（⛔ 不是空文件 ✓）⇒ 放锁后消失 ✓。"""
    p = ac_lock.acquire('roundtrip', wait=1)
    assert os.path.isfile(p), '⭐ 锁文件应存在 ✗'
    info = json.loads(io.open(p, encoding='utf-8').read())
    assert int(info.get('pid') or 0) == os.getpid(), '⭐ 锁文件必须写 pid ✗'
    assert info.get('ts'), '⭐ 必须写时间戳 ✓'
    assert ac_lock.release('roundtrip') is True
    assert not os.path.exists(p), '⭐ 放锁后文件应消失 ✓'


def test_held_lock_makes_others_wait_then_timeout():
    """⭐ 有牙：⭐ 已被占用 ⇒ ⭐ **必须超时抛错** ✗（⛔ 不得静默继续 ✗）。"""
    ac_lock.acquire('busy', wait=1)
    with pytest.raises(TimeoutError):
        ac_lock.acquire('busy', wait=0.5)
    ac_lock.release('busy')


def test_dead_holder_is_reclaimed():
    """⭐ 持锁进程**已退出** ⇒ ⭐ 自动回收 ✓（⭐ 这条正是"⛔ 不用文件存在即锁"的意义 ✓）。"""
    p = ac_lock.lock_path('dead')
    with io.open(p, 'w', encoding='utf-8') as fh:
        fh.write(json.dumps({'pid': 999999, 'ts': time.time()}))
    got = ac_lock.acquire('dead', wait=1)
    assert got, '⭐ 死锁必须能被回收 ✓'
    assert json.loads(io.open(got, encoding='utf-8').read())['pid'] == os.getpid()
    ac_lock.release('dead')


def test_stale_holder_is_reclaimed():
    """⭐ 超过 `stale` 秒未刷新 ⇒ ⭐ 可抢占 ✓（⭐ 防"进程活着但卡死" ✓）。"""
    p = ac_lock.lock_path('stale')
    with io.open(p, 'w', encoding='utf-8') as fh:
        fh.write(json.dumps({'pid': os.getpid(), 'ts': time.time() - 9999}))
    got = ac_lock.acquire('stale', wait=1, stale=10)
    assert got, '⭐ 超时必须能被抢占 ✓'


def test_release_only_own_lock():
    """⭐ ⭐ **只放自己的** ✗：⭐ 别人持有时调用 release ⇒ ⭐ **不得删** ✓。"""
    p = ac_lock.lock_path('other')
    with io.open(p, 'w', encoding='utf-8') as fh:
        fh.write(json.dumps({'pid': 999998, 'ts': time.time()}))
    assert ac_lock.release('other') is False, '⭐ 不得删他人持有的锁 ✗'
    assert os.path.exists(p), '⭐ 文件必须还在 ✓'
    os.remove(p)


def test_lock_dir_not_in_repo(tmp_path):
    """⭐ 锁文件 ⛔ **不得写进仓库** ✗（⭐ 在系统临时目录 ✓）。"""
    p = ac_lock.lock_path('where')
    repo = os.path.abspath(ROOT).lower()
    assert not os.path.abspath(p).lower().startswith(repo), \
        '⭐ 锁文件不得落在仓库内 ✗：%s' % p


def test_cli_runs_command_under_lock():
    """⭐ 端到端：⭐ CLI 在锁内跑命令 ✓ ⇒ ⭐ rc 透传 ＋ 自动放锁 ✓。"""
    r = subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'ac_lock.py'),
                        '--name', 'cli', '--wait', '10', '--',
                        sys.executable, '-c', 'print("under-lock")'],
                       capture_output=True, text=True, encoding='utf-8', cwd=ROOT)
    assert r.returncode == 0, '⭐ 锁内命令应成功 ✗：%s' % (r.stdout or r.stderr or '')[-200:]
    assert 'under-lock' in (r.stdout or ''), '⭐ 命令输出应透传 ✓'
    assert not os.path.exists(ac_lock.lock_path('cli')), '⭐ 跑完必须放锁 ✓'
