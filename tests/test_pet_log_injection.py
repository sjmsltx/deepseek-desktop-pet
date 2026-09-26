# -*- coding: utf-8 -*-
"""S2 护栏：`pet_log` **测试日志注入**（Owner 2026-09-26 16:21 批「根治」）

唯一判据（Owner ✓）：**桌宠在跑时全量也能全绿** ✓
做法（Owner ✓）：用例改用**临时日志目录** ✓ → `pet_log` 提供**最小注入入口** ✓
禁止（Owner ✗）：不改默认日志路径 ✗ 不改轮转阈值 ✗ 不改既有行为 ✗
"""
from __future__ import annotations

import io
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_FILE = os.path.join(str(ROOT), 'logs', 'pet.log')


# ── ① 注入生效 ✓ ────────────────────────────────────────────────
def test_set_log_file_redirects_writes(tmp_path):
    import pet_log
    target = tmp_path / 'sub' / 'pet.log'
    got = pet_log.set_log_file(target)
    try:
        assert got == str(target) and pet_log.LOG_FILE == str(target)
        pet_log.get_logger('s2probe').warning('S2-注入探针-%d', 7)
        txt = io.open(target, encoding='utf-8').read() if target.is_file() else ''
        assert 'S2-注入探针-7' in txt, txt[-300:]
    finally:
        pet_log.reset()
    # 复位后回到**默认路径** ✓
    assert pet_log.LOG_FILE == DEFAULT_LOG_FILE, pet_log.LOG_FILE


# ── ② 默认行为一字不变 ✓（路径 / 阈值 / 份数）────────────────────
def test_defaults_untouched():
    import pet_log
    assert os.path.join(str(ROOT), 'logs') == pet_log.LOG_DIR
    assert pet_log.LOG_FILE == DEFAULT_LOG_FILE
    src = io.open(ROOT / 'pet_log.py', encoding='utf-8').read()
    assert 'maxBytes=512 * 1024' in src, '⛔ 轮转阈值被改动 ✗'
    assert 'backupCount=3' in src, '⛔ 轮转份数被改动 ✗'
    assert "os.path.join(LOG_DIR, 'pet.log')" in src, '⛔ 默认日志路径被改动 ✗'


# ── ③ 注入不依赖环境变量 ✓（显式调用才生效 ✓ 正常启动不受影响 ✓）──
def test_injection_is_explicit_not_env_driven():
    src = io.open(ROOT / 'pet_log.py', encoding='utf-8').read()
    for bad in ('PET_LOG_FILE', 'PET_LOG_DIR', 'PET_LOG_PATH'):
        assert bad not in src, '⛔ 不应引入环境变量开关 ✗（%s）' % bad
    # `set_log_file` 只在被调用时改变路径 ✓
    import pet_log
    before = pet_log.LOG_FILE
    pet_log.get_logger('s2probe2').info('x')     # 只用 logger 不注入 → 路径不变 ✓
    assert pet_log.LOG_FILE == before
