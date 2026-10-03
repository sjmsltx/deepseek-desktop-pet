# -*- coding: utf-8 -*-
"""`asset_op` 真执行（条款 VI/E6 · Owner 2026-10-04 00:15「我批准」✓）

⭐ 三条口径（微信侧 `WX-…-20261004-02` §二 ✓ 我方采纳 ✓）：
  ① **先备份后写入** ✓（原件进 `_raw_backup/` ✓；`replace` ⛔ 绝不覆盖原件 ✗）
  ② **逐文件 ＋ 逐张探针** ✓（⛔ 不按目录跑 ✗ —— 免得重压已完成那批 ✗）
  ③ **dry-run 也落结果** ✓（标 `dry_run:true` ✓）

v1 已实现：`insert`／`replace`／`add_state`／`run_pipeline` ✓
v1 明报未实现：`add_role` ✗（要改**档案** = 用户配置 ✓ 另走一步 ✓）／`delete_state` ✗（受内置状态护栏管 ✓）

⛔ 本模块**不自动跑** ✗ —— 只由 `run_pending.py`（人触发 ✓）调用 ✓
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys

POOL_NAME = 'assets_3.0'
EFF_NAME = 'assets'
BACKUP_NAME = '_raw_backup'
PIPELINE = os.path.join('tools', 'norm_and_variants.py')
PY = sys.executable                      # ⭐ 用当前解释器（独立 python ✓ 不用 PATH 里的 ✗）


def _backup(src: str, base: str) -> str:
    """⭐ 先备份后写入：把原件复制到 `<pool>/_raw_backup/<role>/` ✓（已存在则不覆盖 ✓）。"""
    role = os.path.basename(os.path.dirname(src))
    d = os.path.join(base, POOL_NAME, BACKUP_NAME, role)
    os.makedirs(d, exist_ok=True)
    dst = os.path.join(d, os.path.basename(src))
    if not os.path.exists(dst):
        shutil.copy2(src, dst)
    return dst


def probe_alpha(path: str) -> tuple:
    """逐张探针 → `(前景%, 内部空洞占主体%, 主体均不透明度, 半透明%)` ✓。

    ⭐ 判据同 `PC-…-108`：**内部空洞**＝不与图像边缘连通的透明像素 ✓
      （＝"白大褂被抠穿" ✗ 的 signature ✓）
    """
    import numpy as np
    from PIL import Image
    from scipy import ndimage
    a = np.array(Image.open(path).convert('RGBA'))[..., 3]
    fg = a > 8
    if not fg.any():
        return (0.0, 100.0, 0.0, 0.0)
    bg = ~fg
    lab, n = ndimage.label(bg)                       # ⭐ 连通域（比纯 Python BFS 快得多 ✓）
    edge = set(lab[0, :]) | set(lab[-1, :]) | set(lab[:, 0]) | set(lab[:, -1])
    edge.discard(0)
    holes = bg & ~np.isin(lab, list(edge))
    hole_in_fg = 100.0 * holes.sum() / max(1, int(holes.sum() + fg.sum()))
    ma = float(a[fg].mean())
    semi = 100.0 * float(((a > 8) & (a < 200)).sum()) / max(1, int(fg.sum()))
    return (100.0 * float(fg.mean()), hole_in_fg, ma, semi)


def _probe_ok(p) -> tuple:
    fg, hole, ma, semi = p
    return (hole < 0.5 and ma > 230 and semi < 25), \
        '前景%.1f%% 空洞%.3f%% 均不透明%.1f 半透明%.1f%%' % (fg, hole, ma, semi)


def _find_source(base: str, role: str, state: str, source: str, source_ref: str) -> str:
    """定位要用的源图 ✓（白底裸图 ✓）。"""
    if source_ref:
        rel = str(source_ref).replace('\\', '/')
        if rel.startswith('assets_3.0/'):
            return os.path.join(base, rel.replace('/', os.sep))
        if rel.startswith('assets/'):               # 从生效目录取（也可能是"补三件套"场景 ✓）
            return os.path.join(base, rel.replace('/', os.sep))
    root = os.path.join(base, POOL_NAME if source == 'pool' else EFF_NAME, role)
    cand = [p for p in sorted(glob.glob(os.path.join(root, '%s_%s.png' % (role, state))))
            if not p.endswith(('_chroma.png', '_alpha.png'))]
    return cand[0] if cand else ''


def _run_pipeline(base: str, src: str, dry: bool) -> tuple:
    """⭐ 逐文件跑三合一（出 `_alpha` / `_chroma` ✓）；返回 `(ok, detail)` ✓。"""
    tool = os.path.join(base, POOL_NAME, PIPELINE)
    if not os.path.isfile(tool):
        return False, '管线脚本缺失：%s' % PIPELINE
    if dry:
        return True, '（dry-run）将跑管线：%s' % os.path.basename(src)
    r = subprocess.run([PY, tool, src], capture_output=True, text=True,
                       encoding='utf-8', timeout=300)
    if r.returncode != 0:
        return False, '管线失败(%d)：%s' % (r.returncode, (r.stderr or '')[-200:])
    ap = src[:-4] + '_alpha.png'
    if not os.path.isfile(ap):
        return False, '管线未产出 _alpha ✗（%s）' % os.path.basename(src)
    ok, info = _probe_ok(probe_alpha(ap))
    if not ok:
        return False, '⭐ 探针不过（可能抠穿/半透明 ✗）：%s' % info
    return True, '管线完成 ＋ 探针 ✓：%s' % info


def _backup_file(path: str, base: str, subdir: str = BACKUP_NAME) -> str:
    """把**任意文件**备份到 `<base>/<subdir>/`（帶时间戳 ✓ 不覆盖旧备份 ✓）。"""
    import time as _t
    d = os.path.join(base, subdir)
    os.makedirs(d, exist_ok=True)
    stamp = _t.strftime('%Y%m%d-%H%M%S')
    dst = os.path.join(d, '%s.%s.bak' % (os.path.basename(path), stamp))
    shutil.copy2(path, dst)
    return dst


def do_set_portrait(base: str, payload: dict, dry: bool = False) -> tuple:
    """⭐ `set_portrait`（Owner 2026-10-04 00:36「同意」✓）：**只改 `appearance.portrait` 一个字段** ✓

    ⛔ 不改其它档案字段 ✗ ⛔ 不新建角色 ✗（`role` 必须是**档案里已有**的 key ✓）
    ⭐ 改前**先备份档案** ✓（可回滚 ✓）
    ⚠️ 生效时机：条款 **③-1 启动读一次、运行中不热加载** → ⭐ **重启桌宠后生效** ✓（如实写进结果 ✓）
    """
    role = str(payload.get('role') or '').strip()
    pfx = str(payload.get('portrait_prefix') or '').strip()
    # ⭐ 单段目录名（或空 ＝ 解绑 ✓）；含分隔符 / `..` 一律拒 ✗
    if pfx and ('/' in pfx or '\\' in pfx or '..' in pfx):
        return False, 'portrait_prefix 只允许单段目录名（或留空解绑）✗', []
    cfg = os.path.join(base, 'models.json')
    if not os.path.isfile(cfg):
        return False, '找不到档案 models.json ✗', []
    try:
        import model_registry
    except Exception as exc:
        return False, '档案模块不可用：%r' % exc, []
    reg = model_registry.ModelRegistry(cfg)
    p = reg.get(role)
    if p is None:
        return False, '角色 %r 不在档案里 ✗（本 op 只改**已有**角色，⛔ 不新建 ✗）' % role, []
    # ⚠️ 实测踩坑 ✗：`ModelProfile` 把 `appearance` **拍平**存为 `self.color/self.portrait/self.sub` ✓
    #    （`to_dict()` 再拼回嵌套形状 ✓）→ ⭐ 没有 `p.appearance` 这个属性 ✗
    #    （我第一版写成 `p.appearance['portrait']` ✗ → 跑真机验证当场判红 ✓ 未进提交 ✓）
    if not hasattr(p, 'portrait'):
        return False, '角色 %r 无 portrait 字段 ✗（未做任何改动 ✓）' % role, []
    old = str(getattr(p, 'portrait', '') or '')
    if dry:
        return True, '（dry-run）将改 %s：appearance.portrait %r → %r' % (role, old, pfx), []
    # ⭐ 改前备份档案 ✓
    _backup_file(cfg, base)
    p.portrait = pfx                                          # ⭐ 只改这一个字段 ✓
    if not reg.save():
        return False, '档案保存失败：%s' % (getattr(reg, 'last_error', '') or '未知'), []
    detail = ('已设 %s → portrait=%r（原 %r）｜ ⚠️ **重启桌宠后生效**'
              '（契约 ③-1：启动读一次、运行中不热加载 ✓）') % (role, pfx, old)
    # ⭐ 目录暂不存在：**只登记不拦** ✓（照微信侧口径 ✓）—— 但要**提示** ✓ 不静默 ✗
    if pfx:
        ex = any(os.path.isdir(os.path.join(base, r, pfx)) for r in (EFF_NAME, POOL_NAME))
        if not ex:
            detail += '｜ 提示：目录 %r 暂不存在（渲染会回落角色 key ✓ 不算失败 ✓）' % pfx
    return True, detail, ['models.json']


def do_asset_op(base: str, payload: dict, dry: bool = False) -> tuple:
    """执行一条 `asset_op` ✓ 返回 `(ok, detail, artifacts)` ✓。"""
    role = str(payload.get('role') or '').strip()
    state = str(payload.get('state') or '').strip()
    op = str(payload.get('op') or '')
    source = str(payload.get('source') or 'pool')
    ref = str(payload.get('source_ref') or '')
    want_pipeline = bool(payload.get('run_pipeline', True))
    artifacts = []

    if op == 'set_portrait':                                  # ⭐ Owner 00:36 已批 ✓
        return do_set_portrait(base, payload, dry=dry)
    if op == 'add_role':
        return False, ('add_role 在 v1 **尚未实现** ✗ —— 它要写**档案**（`models.json` ＝ '
                       '用户配置 ✓ 属另一个领域 ✓）→ 另走一步 ✓ 本条已记录、未做任何改动 ✓'), []
    if op == 'delete_state':
        return False, ('delete_state 在 v1 **尚未实现** ✗（牵涉内置状态护栏 ✓ 需逐条确认 ✓）；'
                       '本条已记录、未做任何改动 ✓'), []
    if op not in ('insert', 'replace', 'add_state', 'run_pipeline', 'set_portrait'):
        return False, '未知 op：%r（枚举外 ✓）' % op, []

    src = _find_source(base, role, state, source, ref)
    if not src or not os.path.isfile(src):
        return False, '找不到源图（role=%s state=%s source=%s ref=%s）' % (
            role, state, source, ref or '-'), []

    # ① 先备份后写入 ✓（原件一律保留 ✓）
    if not dry:
        _backup(src, base)
    arts = [os.path.relpath(src, base).replace(os.sep, '/')]

    # ② 生效目录：`replace`／`insert` 时把源图作为该状态的**白底主图**放进去 ✓
    if op in ('insert', 'replace', 'add_state'):
        tgt_dir = os.path.join(base, EFF_NAME, role)
        tgt = os.path.join(tgt_dir, '%s_%s.png' % (role, state))
        if os.path.exists(tgt):                     # ⛔ 绝不静默覆盖 ✗
            if not dry:
                _backup(tgt, base)
        if not dry:
            os.makedirs(tgt_dir, exist_ok=True)
            shutil.copy2(src, tgt)
        arts.append(os.path.relpath(tgt, base).replace(os.sep, '/'))

    # ③ 跑管线（逐文件 ✓）
    if want_pipeline or op == 'run_pipeline':
        okp, info = _run_pipeline(base, src, dry)
        if not okp:
            return False, info, arts
        arts.append(os.path.relpath(src[:-4] + '_alpha.png', base).replace(os.sep, '/'))

    return True, ('（dry-run）' if dry else '') + '完成：%s %s/%s ｜ 产物 %d 个' % (
        op, role, state, len(arts)), arts
