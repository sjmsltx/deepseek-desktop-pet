# -*- coding: utf-8 -*-
"""立绘解析护栏（2026-10-22 Owner 报的两个 bug）

背景：
  Owner 发现 ① 待机背景没抠透明 ② 待机与贴边不是同一个角色。
  根因都在 `asset()` 的取图规则上：
    ① 素材池里三份并存（裸版白底 / _alpha 透明 / _chroma 绿幕），旧逻辑只拼裸名；
    ② 素材池缺贴边图时，旧逻辑会**跨角色**回落到 assets/<role>/ 拿老角色的贴边图。

本文件钉住修好后的两条规则，以及「非贴边系仍然允许跨角色回落」这条不能误伤的旧行为。
"""
import ast
import io
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import desktop_pet as dp  # noqa: E402


class _P:
    def __init__(self, portrait=""):
        self.portrait = portrait


class _Reg:
    def __init__(self, mapping):
        self._m = mapping

    def get(self, k):
        return self._m.get(k)


def _env(monkeypatch, tmp_path, portrait):
    monkeypatch.setattr(dp, "ASSETS", str(tmp_path), raising=False)
    monkeypatch.setattr(dp, "ASSETS_POOL", str(tmp_path / "_pool"), raising=False)
    monkeypatch.setattr(dp, "MODEL_REGISTRY", _Reg({"flash": _P(portrait)}), raising=False)


# ── A：_alpha 变体优先（治「背景不透明」）────────────────────────────

def test_pick_asset_prefers_alpha_variant(tmp_path):
    """裸版与 _alpha 并存时，必须取 _alpha（素材池约定：裸版是白底/绿幕）"""
    d = tmp_path
    (d / "x_idle.png").write_bytes(b"bare")
    (d / "x_idle_alpha.png").write_bytes(b"alpha")
    got = dp._pick_asset(str(d), "x_idle")
    assert got == str(d / "x_idle_alpha.png"), "必须优先 _alpha，实测拿到 %r" % got


def test_pick_asset_falls_back_to_bare(tmp_path):
    """没有 _alpha 变体（flash/pro 老素材）→ 行为与从前一致，取裸名"""
    d = tmp_path
    (d / "x_idle.png").write_bytes(b"bare")
    assert dp._pick_asset(str(d), "x_idle") == str(d / "x_idle.png")


def test_pick_asset_only_alpha_exists(tmp_path):
    """只有 _alpha（裸版被删）也要能取到，不许因为缺裸名而判缺失"""
    d = tmp_path
    (d / "x_idle_alpha.png").write_bytes(b"alpha")
    assert dp._pick_asset(str(d), "x_idle") == str(d / "x_idle_alpha.png")


def test_pick_asset_none_when_absent(tmp_path):
    assert dp._pick_asset(str(tmp_path), "nothing") is None


def test_asset_prefers_alpha_through_public_api(monkeypatch, tmp_path):
    """走公开入口 asset() 也要优先 _alpha"""
    (tmp_path / "flash").mkdir()
    pool = tmp_path / "_pool" / "alt"
    pool.mkdir(parents=True)
    (pool / "alt_happy.png").write_bytes(b"white-bg")
    (pool / "alt_happy_alpha.png").write_bytes(b"transparent")
    _env(monkeypatch, tmp_path, "alt")
    got = dp.asset("flash", "happy")
    assert got == str(pool / "alt_happy_alpha.png"), "实得 %r" % got


# ── B：贴边系禁止跨角色回落（治「不是同一个人」）──────────────────────

def test_peek_never_crosses_role(monkeypatch, tmp_path):
    """前缀目录没有贴边图 → 只能在自己目录里回落，**不许**去角色 key 目录拿老角色的"""
    (tmp_path / "flash").mkdir()
    (tmp_path / "flash" / "flash_peek.png").write_bytes(b"OLD-CHARACTER")
    alt = tmp_path / "alt"
    alt.mkdir()
    (alt / "alt_idle.png").write_bytes(b"NEW-CHARACTER")

    _env(monkeypatch, tmp_path, "alt")
    got = dp.asset("flash", "peek")
    assert "flash_peek" not in got, "⛔ 贴边不许回落到老角色：%r" % got
    assert got == str(alt / "alt_idle.png"), "应落到本角色 idle，实得 %r" % got


def test_non_peek_still_crosses_role(monkeypatch, tmp_path):
    """回归：非贴边系**仍然**允许跨角色回落（旧行为，不许被这次修复误伤）"""
    (tmp_path / "flash").mkdir()
    (tmp_path / "flash" / "flash_angry.png").write_bytes(b"x")
    (tmp_path / "alt").mkdir()
    _env(monkeypatch, tmp_path, "alt")
    assert dp.asset("flash", "angry").endswith(os.path.join("flash", "flash_angry.png"))


def test_peek_states_cover_all_peek_calls():
    """结构护栏：desktop_pet.py 里所有 `asset(x, 'peek*')` 调用都必须在 _PEEK_STATES 里

    ⛔ 不用字符串 grep 数注释；用 ast 找真实调用。
    这样以后新加一个 peek 变体、忘了登记，会当场红。
    """
    src = io.open(os.path.join(ROOT, "desktop_pet.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    called = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = getattr(f, "id", None) or getattr(f, "attr", None)
        if name != "asset":
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                    and arg.value.startswith("peek"):
                called.add(arg.value)
    assert called, "没扫到任何 peek 调用，护栏失效"
    missing = sorted(called - set(dp._PEEK_STATES))
    assert not missing, "这些贴边状态没登记进 _PEEK_STATES（会跨角色回落）：%s" % missing


def test_peek_states_registry_is_exact():
    """登记表里的每一项都必须是 peek 开头（防手滑写进别的 state 改变旧行为）"""
    for s in dp._PEEK_STATES:
        assert s.startswith("peek"), "⛔ _PEEK_STATES 里有非贴边项：%r" % s


# ── 真资产抽查（缺素材池时跳过，只在开发机生效）──────────────────────

def test_real_pool_alpha_is_transparent():
    pool = os.path.join(ROOT, "assets_3.0")
    if not os.path.isdir(pool):
        pytest.skip("本机无 assets_3.0 素材池")
    from PIL import Image

    p = os.path.join(pool, "deepseek", "deepseek_idle_alpha.png")
    if not os.path.exists(p):
        pytest.skip("素材池里没有 deepseek_idle_alpha.png")
    im = Image.open(p)
    assert im.mode == "RGBA", "素材池的 _alpha 版应当是 RGBA，实测 %s" % im.mode
    a = im.convert("RGBA").split()[-1]
    zero = a.histogram()[0]          # 值为 0 的像素数（比 getdata() 快且不触发弃用告警）
    ratio = zero * 100.0 / (a.width * a.height)
    assert ratio > 40, "透明像素只有 %.1f%%，像是没抠干净" % ratio


def test_real_repo_idle_and_peek_same_character():
    """真仓真档案：待机与贴边必须落在**同一个角色目录**"""
    pool = os.path.join(ROOT, "assets_3.0")
    if not os.path.isdir(pool):
        pytest.skip("本机无 assets_3.0 素材池")
    idle = dp.asset("flash", "idle")
    assert os.path.exists(idle), "连待机图都找不到：%r" % idle
    idle_dir = os.path.dirname(idle)
    for s in ("peek", "peek_top", "peek_bottom"):
        got = dp.asset("flash", s)
        assert os.path.dirname(got) == idle_dir, \
            "贴边 %s 落到了别的目录：%r（待机在 %s）" % (s, got, idle_dir)
