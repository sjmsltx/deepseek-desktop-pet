# -*- coding: utf-8 -*-
"""⭐ CLI 路径护栏（微信侧 `WX-…-20261004-07` §二.4 建议 ✓）

教训：`run_pending.py` 只把 `collab/` 插进 `sys.path` ✗ → CLI 路径下
     `asset_ops` 的惰性 `import model_registry`（在**仓库根** ✓）**必然失败** ✗；
     而 pytest 跑时仓库根本来就在 `sys.path` ✓ → ⭐ **测试绿／CLI 红** ✗（"环境差异导致的假绿" ✓）

⭐ 本文件专治这一类：**用子进程跑真 CLI** ✗ 不靠 in-process 导入 ✓。
"""
import io
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable                      # ⭐ 当前解释器（独立 python ✓）


def _clean_repo(tmp_path):
    """造一个最小但**完整**的临时仓库 ✓（含档案 ＋ 素材池工具 ✓）。"""
    base = str(tmp_path)
    os.makedirs(os.path.join(base, 'collab', 'pending'))
    os.makedirs(os.path.join(base, 'assets_3.0'))
    # ⭐ 2026-10-10（外部评估指出）：`assets_3.0/` 被 .gitignore 排除 ⇒ 陌生人 clone 后
    #   ⭐ 该目录不存在 ⇒ 这里原样 `copytree` 会抛 ⇒ 整组用例 **fail**
    #   ⭐ 素材是本项目的"数据"而非"代码" ⇒ ⭐ **缺数据应 skip（并说明原因）** ✗，⛔ 不是失败 ✓
    _a3 = os.path.join(ROOT, 'assets_3.0', 'tools')
    if not os.path.isdir(_a3):
        pytest.skip('⭐ 本仓缺少 assets_3.0/tools（⭐ 该目录被 .gitignore 排除 ✓）'
                    '⇒ 素材相关用例跳过（⛔ 不是失败 ✗）')
    shutil.copytree(_a3, os.path.join(base, 'assets_3.0', 'tools'))
    cfg = json.load(io.open(os.path.join(ROOT, 'models.json'), encoding='utf-8'))
    for p in cfg['profiles']:
        p.setdefault('appearance', {})['portrait'] = ''
    io.open(os.path.join(base, 'models.json'), 'w', encoding='utf-8').write(
        json.dumps(cfg, ensure_ascii=False, indent=2))
    return base


def _drop_op(base, op_id, payload):
    fn = os.path.join(base, 'collab', 'pending', '20261004-010000-asset_op-%s.json' % op_id)
    io.open(fn, 'w', encoding='utf-8').write(
        json.dumps({'op_id': op_id, 'type': 'asset_op', 'payload': payload},
                   ensure_ascii=False))


def _run_cli(base):
    """⭐ 子进程跑真 CLI ✓（不传 PYTHONPATH ✗ 不预插路径 ✗）。"""
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    script = os.path.join(ROOT, 'collab', 'run_pending.py')
    return subprocess.run([PY, script, '--base', base], capture_output=True,
                          text=True, encoding='utf-8', cwd=ROOT, env=env, timeout=300)


# ── 1. ⭐⭐ 核心：`set_portrait` 走**真 CLI** 必须成功（旧版必然 ModuleNotFoundError ✗）──
def test_set_portrait_works_over_real_cli(tmp_path):
    base = _clean_repo(tmp_path)
    _drop_op(base, 'cli0001',
             {'role': 'flash', 'op': 'set_portrait', 'portrait_prefix': 'deepseek'})
    r = _run_cli(base)
    out = (r.stdout or '') + (r.stderr or '')
    assert 'ModuleNotFoundError' not in out, \
        '⛔ CLI 下不得出现 ModuleNotFoundError ✗（＝路径没插全 ✓）：%s' % out[-300:]
    assert '成功 1' in r.stdout, '⭐ 真 CLI 必须跑成功 ✗：%s' % (r.stdout or '')[-300:]
    cfg = json.load(io.open(os.path.join(base, 'models.json'), encoding='utf-8'))
    f = [p for p in cfg['profiles'] if p['key'] == 'flash'][0]
    assert f['appearance']['portrait'] == 'deepseek', '⭐ 效果必须真落地 ✓'


# ── 2. ⭐ 另一条 CLI 路径：`run_pipeline`（用真管线 ✓ 合成图 ✓）────────────────
def test_run_pipeline_works_over_real_cli(tmp_path):
    base = _clean_repo(tmp_path)
    from PIL import Image, ImageDraw
    d = os.path.join(base, 'assets_3.0', 'alpha')
    os.makedirs(d)
    im = Image.new('RGB', (120, 120), (255, 255, 255))
    ImageDraw.Draw(im).rectangle([30, 30, 90, 90], fill=(200, 60, 60))
    im.save(os.path.join(d, 'alpha_happy.png'))
    _drop_op(base, 'cli0002',
             {'role': 'alpha', 'state': 'happy', 'op': 'run_pipeline', 'source': 'pool'})
    r = _run_cli(base)
    out = (r.stdout or '') + (r.stderr or '')
    assert 'ModuleNotFoundError' not in out, '⛔ CLI 路径不得缺模块 ✗'
    assert os.path.isfile(os.path.join(d, 'alpha_happy_alpha.png')), '⭐ 应产出透明版 ✓'


# ── 3. ⭐ 反向护栏：CLI 必须在**没有** PYTHONPATH 的情况下也能跑（防空扫/防假绿 ✓）──
def test_cli_does_not_depend_on_pythonpath(tmp_path):
    base = _clean_repo(tmp_path)
    _drop_op(base, 'cli0003',
             {'role': 'flash', 'op': 'set_portrait', 'portrait_prefix': 'qwen'})
    r = _run_cli(base)                     # ⭐ 内部已 pop('PYTHONPATH') ✓
    assert r.returncode == 0, '⭐ CLI 退出码应为 0 ✓（实测 %s）' % r.returncode
    assert '档案模块不可用' not in (r.stdout or ''), '⛔ 不得再出现"档案模块不可用" ✗'


# ── 4. ⭐ 源码级：`run_pending` 必须**同时**插「仓库根 ＋ collab」（防回退 ✗）──
def test_run_pending_inserts_both_roots():
    s = io.open(os.path.join(ROOT, 'collab', 'run_pending.py'), encoding='utf-8').read()
    assert 'os.path.dirname(_HERE)' in s or 'dirname(os.path.dirname' in s, \
        '⭐ 必须把**仓库根**也插进 sys.path ✗（只插 collab/ 会重现本 bug ✗）'
