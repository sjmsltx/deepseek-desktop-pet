# -*- coding: utf-8 -*-
"""S3 防回归护栏：**产品代码**（非 tests/）不得出现"一行式未关闭 open" ✗。

口径（为什么只钉产品代码 ✓）：
  · 测试里的漏句柄只是卫生问题 ✓（已有 S3 多刀在清 ✓）
  · ⭐ **产品代码**跑在**长驻 GUI 进程**里 —— 每漏一个句柄都真占资源 ✓（`desktop_pet.py:5906` 就是实例 ✗）
  · ⛔ 不禁止"合理兜底"（读配置回落默认值那类 ✓）；只钉**一行式读写**这一种明确写法 ✓
"""
import io
import os
import re
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _find_git():
    """⭐ 解析 git 位置 —— ⛔ **不硬编码盘符** ✗。

    2026-10-07：项目从 `E:\ai工作站\desktop-pet`（E 是**可移动盘/U 盘** ⇒ 拔盘即不可用）
    迁到 `D:\ai工作站\desktop-pet`，⭐ git 也从**E 盘那份**换到 **D 盘** ✗ ⇒
    原硬编码的**旧位置**（在 E 盘那份 Git）**已不存在** ✗ ⇒ 本文件 3 条用例齐红（`FileNotFoundError` ✗）。
    ⇒ 改为**按候选顺序解析**，避免下次换盘再红 ✓。
    """
    for c in (os.environ.get('AC_GIT'),
              r'D:\Git\cmd\git.exe',
              r'C:\Program Files\Git\cmd\git.exe'):
        if c and os.path.isfile(c):
            return c
    return 'git'  # ⭐ 兑底：交给 PATH（找不到会抛错 ⇒ 可见 ✓，⛔ 不静默 ✗）


GIT = _find_git()
SKIP = ('.git', '__pycache__', 'backup', 'assets', 'assets_3.0', 'release_build', '输出',
        'tests', 'collab_verif')
PAT = re.compile(r"open\([^)]*\)(?!\s*as\b)\.(read|write|readlines|readline)\(")


def _product_py():
    out = subprocess.run([GIT, "-c", "core.quotepath=false", "ls-files", "*.py"],
                         cwd=ROOT, capture_output=True)
    for f in out.stdout.decode("utf-8", "replace").splitlines():
        f = f.strip()
        if not f or any(s in f for s in SKIP) or f.startswith('tests/'):
            continue
        p = os.path.join(ROOT, f)
        if os.path.isfile(p):
            yield f, p


def test_no_one_liner_open_in_product_code():
    bad = []
    for f, p in _product_py():
        with io.open(p, encoding="utf-8", errors="ignore") as fh:
            for i, l in enumerate(fh.read().splitlines(), 1):
                if PAT.search(l) and 'with open' not in l:
                    bad.append('%s:%d %s' % (f, i, l.strip()[:90]))
    assert bad == [], '⛔ 产品代码不得出现一行式未关闭 open ✗（长驻进程里是真实资源泄漏）：\n' + '\n'.join(bad)


def test_guard_actually_scans_something():
    """反向护栏：确认这个扫描**真的在看文件** ✓（别把空扫当通过 ✗）。"""
    files = list(_product_py())
    assert len(files) >= 5, '扫描到的产品 py 文件太少（%d）→ 说明扫描口径坏了 ✗' % len(files)
