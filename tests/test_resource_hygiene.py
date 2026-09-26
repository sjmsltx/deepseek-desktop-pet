# -*- coding: utf-8 -*-
"""S1-B 护栏：**只把 `PytestUnraisableExceptionWarning` 升级为错误** ✓（绝不一刀切 ✗）

微信侧委托（`WX-桌宠-20260926-09`）：
  - B：护栏**只限**这一类警告 ✓（整体 `-W error` 会让数百条 ResourceWarning 立刻炸 ✗）
  - 验收 ④：**新增护栏用例**，证明"未关闭资源会红" ✓
"""
from __future__ import annotations

import io
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INI = ROOT / 'pytest.ini'


# ── ① 配置在位（且**只有这一条** ✓）────────────────────────────────────
def test_filterwarnings_limited_to_one_class():
    txt = io.open(INI, encoding='utf-8').read()
    assert 'error::pytest.PytestUnraisableExceptionWarning' in txt, '缺该护栏 ✗'
    # ⛔ 不得出现"一刀切"写法（如裸 `-W error` / `error::` 泛匹配 ✗）
    assert 'filterwarnings =\n    error\n' not in txt, '⛔ 不得把全部 warning 变 error ✗'
    assert 'error::ResourceWarning' not in txt, '⛔ ResourceWarning 未清理完前不得升级 ✗'


# ── ② 功能性证明：未关闭资源（unraisable）**必须使运行变红** ✓ ─────────
_LEAK_TEST = '''
class _Boom:
    def __del__(self):
        raise RuntimeError('unclosed resource leak（模拟未关闭资源 ✓）')


def test_leaky_resource():
    _Boom()
    import gc
    gc.collect()
    assert True
'''


def test_unraisable_leak_turns_run_red():
    """⭐ 确定性证明：带"未关闭资源"的用例在**本配置**下必须 **失败** ✓（而非仅警告 ✗）"""
    with tempfile.TemporaryDirectory() as td:
        tf = Path(td) / 'test_leaky_probe.py'
        tf.write_text(_LEAK_TEST, encoding='utf-8')
        p = subprocess.run([sys.executable, '-m', 'pytest', str(tf), '-q', '-p', 'no:cacheprovider', '-c', str(INI)],
                           cwd=str(ROOT), capture_output=True, text=True, encoding='utf-8', errors='replace')
    out = (p.stdout or '') + (p.stderr or '')
    assert p.returncode != 0, f'⭐ 未关闭资源**应当变红** ✗ 实际 rc={p.returncode}\n{out[-600:]}'
    assert 'PytestUnraisableExceptionWarning' in out or 'unraisable' in out.lower(), out[-600:]


def test_normal_test_still_green():
    """反向证明：普通用例（无泄漏）不应受影响 ✓（护栏只针对那一类 ✗）"""
    with tempfile.TemporaryDirectory() as td:
        tf = Path(td) / 'test_ok_probe.py'
        tf.write_text('def test_ok():\n    assert 1 + 1 == 2\n', encoding='utf-8')
        p = subprocess.run([sys.executable, '-m', 'pytest', str(tf), '-q', '-p', 'no:cacheprovider', '-c', str(INI)],
                           cwd=str(ROOT), capture_output=True, text=True, encoding='utf-8', errors='replace')
    assert p.returncode == 0, (p.stdout or '')[-400:]
