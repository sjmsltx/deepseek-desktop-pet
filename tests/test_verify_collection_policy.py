# -*- coding: utf-8 -*-
"""R1 护栏：**脚本式检查模块**不得被 pytest 收集（否则断言失败会炸整套测试 ✗）

背景：2026-09-25 微信侧独立核验时撞到 `INTERNALERROR`（`tests/test_pet_selfcode.py:82` 的
`sys.exit(1)`）→ **整套测试一条都跑不起来** ✗（外部看成"测试挂了"）。

根因：这些文件是**脚本**（模块级代码 + `sys.exit()`），却被 `pytest.ini` 的 `testpaths = tests`
收集；它们只在 import 期跑一次，一旦断言失败就是收集期失败 ✗。

处置（R1）：① `conftest.collect_ignore` 显式排除 ✓ ② `tools/verify.py` **单独调用**它们 ✓
（避免"移出收集即丢失检查" ✗）③ 本护栏保证 ①②**长期成立** ✓
"""
from __future__ import annotations

import io
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFTEST = ROOT / 'conftest.py'
VERIFY = ROOT / 'tools' / 'verify.py'
TESTS = ROOT / 'tests'

# 由 verify.py 在 --with-ui 时才跑的脚本（不在默认步骤里 ✓）
GATED_BY_FLAG = {'tests/golden_ui.py'}

# 显式登记：不入收集 **且** 不由 verify 跑（附理由 ✓ 防以后被当成遗漏 ✗）
NOT_RUN_BY_VERIFY = {
    'regression_test.py': '手动回归器脚本（def test(name, fn) 需人工传参 ✓ 不属自动检查）',
}


def _script_style_modules():
    """脚本式模块：含**模块级** sys.exit( 且**没有** def test_ （即不是 pytest 用例）"""
    out = []
    for p in sorted(TESTS.glob('*.py')):
        src = io.open(p, encoding='utf-8', errors='replace').read()
        if 'def test_' in src:
            continue
        if not re.search(r'(?m)^\s*sys\.exit\(', src):
            continue
        out.append('tests/' + p.name)
    return out


def test_script_style_modules_are_not_collected():
    """护栏①：所有脚本式模块都必须在 conftest.collect_ignore 里 ✓（否则会炸整套 ✗）"""
    conf = io.open(CONFTEST, encoding='utf-8').read()
    ignored = set(re.findall(r"'([^']+\.py)'", conf))
    missing = [m for m in _script_style_modules() if m not in ignored]
    assert not missing, f'脚本式模块未排除出 pytest 收集 ✗（会炸整套测试）：{missing}'


def test_ignored_scripts_are_still_run_by_verify():
    """护栏②：被排除的脚本仍必须由 verify.py 单独调用 ✓（防"移出收集即丢失检查" ✗）"""
    ver = io.open(VERIFY, encoding='utf-8').read()
    conf = io.open(CONFTEST, encoding='utf-8').read()
    ignored = [p for p in re.findall(r"'([^']+\.py)'", conf)]
    lost = []
    for rel in ignored:
        if rel in GATED_BY_FLAG or rel in NOT_RUN_BY_VERIFY:
            continue
        name = Path(rel).name
        if name not in ver and rel not in ver:
            lost.append(rel)
    assert not lost, f'这些脚本已移出收集但 verify.py 没跑 ✗（检查被悄悄丢掉）：{lost}'


def test_verify_runs_script_checks_and_keeps_exit_code():
    """护栏③：verify.py 的脚本步骤要**参与总退出码**（不能被静默忽略 ✗）"""
    ver = io.open(VERIFY, encoding='utf-8').read()
    assert 'SCRIPT_CHECKS' in ver, '缺少脚本式检查步骤 ✗'
    assert 'steps += [(n, [PY, p]) for n, p in SCRIPT_CHECKS]' in ver, \
        '脚本式检查未并入 steps（不会参与总退出码）✗'
