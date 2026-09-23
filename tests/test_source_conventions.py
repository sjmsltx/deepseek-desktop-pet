# -*- coding: utf-8 -*-
"""源码约定护栏（A 类新增文件 · 范本：tests/test_foreground_privacy.py）

设计原则（与范本一致 ✓）：
  · **只扫源码文本**，不 import 产品模块、不依赖 Qt / 运行环境 ✓
  · 一条约定 = 一条断言 ✓ 失败即"约定被破坏"✓
  · **独立文件，删掉即回退** ✓ 不影响其它任何测试 ✓
  · 断言对象是"**项目当前真实存在**的约定"（均已实测 ✔）✗ 不是我新发明的规矩 ✓
"""
from __future__ import annotations

import io
import os
import re
from pathlib import Path

import pytest

# 默认以本文件所在项目的上一级为仓库根；可用 PET_REPO_ROOT 覆盖（便于在未安装时对真实仓库验证）
ROOT = Path(os.environ.get("PET_REPO_ROOT") or Path(__file__).resolve().parent.parent)


def read(name: str) -> str:
    return io.open(ROOT / name, encoding="utf-8", errors="ignore").read()


# ── 1. UI 文件里的颜色字面量只允许"哨兵色" ──────────────────────────────
UI_FILES = ["desktop_pet.py", "settings_ui.py", "pet_bubble.py", "chat_render.py",
            "chat_cards.py", "side_panel.py", "pet_minigames.py"]
SENTINEL = "#ff00ff"          # 缺键时的"肉眼可见"兜底色（有意写死）
COLOR_RE = re.compile(r"#[0-9a-fA-F]{6}\b")


def test_ui_files_only_allow_sentinel_color():
    """主题 token 化的成果不能悄悄退化：UI 文件里只允许出现哨兵色 #ff00ff。"""
    bad = {}
    for f in UI_FILES:
        found = set(COLOR_RE.findall(read(f))) - {SENTINEL}
        if found:
            bad[f] = sorted(found)
    assert not bad, f"UI 文件出现硬编码颜色（应改用 pet_theme 的 token）：{bad}"


# ── 2. 不得出现混合行尾（同一文件既 CRLF 又 LF）────────────────────────
def test_no_mixed_line_endings():
    bad = []
    for p in list(ROOT.glob("*.py")) + list((ROOT / "tests").glob("*.py")) + list((ROOT / "tools").glob("*.py")):
        b = p.read_bytes()
        if b.count(b"\r\n") and b.replace(b"\r\n", b"").count(b"\n"):
            bad.append(p.name)
    assert not bad, f"这些文件同时含 CRLF 与 LF（会污染 diff / 触发脚本改写）：{bad}"


# ── 3. conftest 必须排除手工回归器 ────────────────────────────────────
def test_conftest_excludes_manual_regression_runner():
    t = read("conftest.py")
    assert "collect_ignore" in t, "conftest.py 必须声明 collect_ignore"
    assert "regression_test.py" in t, "手工回归器 regression_test.py 必须被显式排除（否则退出码会被误判为 1）"


# ── 4. pytest 收集范围必须收口 ───────────────────────────────────────
def test_pytest_collection_scope_pinned():
    t = read("pytest.ini")
    assert "testpaths" in t and "tests" in t, "pytest.ini 必须把 testpaths 限定到 tests"
    for d in ("assets_3.0", "release_build"):
        assert d in t, f"norecursedirs 必须排除 {d}（否则会重复收集 / 收进整份项目副本）"


# ── 5. 发布包禁止项不得缩水 ──────────────────────────────────────────
def test_release_forbid_list_intact():
    t = read("tools/check_release_package.py")
    for item in ("logs/", "memories.json", "models.json", "config.json"):
        assert item in t, f"发布包禁止项缺少 {item}（会把作者本地状态发出去）"


# ── 6. 立绘事故护栏：qt.conf 与 qjpeg.dll 必须被要求 ────────────────────
def test_release_requires_qt_conf_and_jpeg_plugin():
    t = read("tools/check_release_package.py")
    assert "qt.conf" in t, "校验器必须要求包内存在 qt.conf（否则 Qt 找不到插件目录）"
    assert "qjpeg.dll" in t, "校验器必须要求 qjpeg.dll（立绘是 jpg，缺它会被静默解码为 null）"


# ── 7. 永禁清单不可缩水 ──────────────────────────────────────────────
def test_forever_forbidden_not_shrunk():
    t = read("skill_pack.py")
    i = t.index("FOREVER_FORBIDDEN = [")
    blk = t[i:]
    blk = blk[:blk.index("\n]")]
    items = re.findall(r"'([^']+)'", blk)
    assert len(items) >= 14, f"永禁项少于 14 条（现有 {len(items)}）"
    for must in ("os.system", "eval("):
        assert must in items, f"永禁清单必须保留 {must}"


# ── 8. 权限类别契约 ────────────────────────────────────────────────
def test_permission_categories_pinned():
    t = read("skill_pack.py")
    blk = t[t.index("PERMISSIONS = {"):]
    blk = blk[:blk.index("\n}")]
    keys = re.findall(r"^\s*'([^']+)':\s*\(", blk, re.M)
    assert len(keys) == 8, f"权限类别应为 8 类（现有 {len(keys)}）：{keys}"
    for must in ("files.read", "files.write", "network"):
        assert must in keys, f"权限类别必须保留 {must}"


# ── 9. core 工具不可误删 ────────────────────────────────────────────
def test_core_tools_not_removed():
    t = read("tools_registry.py")
    blk = t[t.index("CORE_TOOLS = ("):]
    blk = blk[:blk.index("\n)")]
    ks = re.findall(r"'([a-z_]+)'", blk)
    assert len(ks) >= 15, f"core 工具数异常偏少（现有 {len(ks)}）"
    for must in ("get_time", "query_weather", "set_reminder", "manage_todo",
                 "memorize", "offer_choices", "read_file", "write_file"):
        assert must in ks, f"core 必须保留 {must}（默认暴露给模型的陪伴高频能力）"


# ── 10. assets_3.0 不得裸奔（第 0 步已落地 ✓ 现为正式断言）────────────────
def test_assets_3_0_is_ignored():
    """3.0 素材库体量大且仍在迭代，必须被 .gitignore 挡住（一次 git add -A 就会把 1.5 GB 吞进历史·不可逆）"""
    if not (ROOT / "assets_3.0").exists():
        pytest.skip("本机无 assets_3.0，跳过")
    gi = read(".gitignore") if (ROOT / ".gitignore").exists() else ""
    assert "assets_3.0" in gi, "assets_3.0/ 存在但 .gitignore 未忽略它 → 一次 git add -A 就会把 1.5 GB 素材吞进历史（不可逆）"
