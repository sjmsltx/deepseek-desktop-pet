# -*- coding: utf-8 -*-
"""立绘绑定护栏（Owner 2026-10-03「立绘要想自定义」→ config 可自定义的电脑侧半 ✓）。

口径：
  · 档案 `appearance.portrait` ＝ 该角色的**资产目录前缀** ✓（**零 schema 变更** ✓ 该字段本来就存在 ✓）
  · 留空 / 目录不存在 / 查档案失败 → ⭐ **回落角色 key** ✓（**行为与从前完全一致** ✓）
  · ⛔ UI 只记绑定：**不复制、不覆盖**任何图片 ✗
"""
import io
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import desktop_pet as dp  # noqa: E402


class _P:
    def __init__(self, portrait=''):
        self.portrait = portrait


class _Reg:
    def __init__(self, mapping):
        self._m = mapping

    def get(self, k):
        return self._m.get(k)


def _set_env(monkeypatch, tmp_path, portrait):
    """把 ASSETS 指到临时目录 ✓ 并注入替身档案 ✓（不碰真资产 ✗）。"""
    monkeypatch.setattr(dp, 'ASSETS', str(tmp_path), raising=False)
    monkeypatch.setattr(dp, 'MODEL_REGISTRY', _Reg({'flash': _P(portrait)}), raising=False)


# ── 1. ⭐ 留空 = 与从前完全一致（最要紧的一条 ✓）──────────────────────
def test_empty_portrait_keeps_legacy_behaviour(monkeypatch, tmp_path):
    (tmp_path / 'flash').mkdir()
    (tmp_path / 'flash' / 'flash_happy.png').write_bytes(b'x')
    _set_env(monkeypatch, tmp_path, '')
    assert dp._asset_prefix('flash') == 'flash'
    assert dp.asset('flash', 'happy') == os.path.join(str(tmp_path), 'flash', 'flash_happy.png')


# ── 2. 目录不存在 → 回落 key ✓（不因配置错误而崩 ✗）──────────────────
def test_missing_dir_falls_back_to_key(monkeypatch, tmp_path):
    (tmp_path / 'flash').mkdir()
    _set_env(monkeypatch, tmp_path, 'no_such_dir')
    assert dp._asset_prefix('flash') == 'flash'


# ── 3. 指定存在目录 → 绑定生效 ✓ ──────────────────────────────────────
def test_existing_dir_binds(monkeypatch, tmp_path):
    (tmp_path / 'flash').mkdir()
    (tmp_path / 'alt').mkdir()
    (tmp_path / 'alt' / 'alt_happy.png').write_bytes(b'x')
    _set_env(monkeypatch, tmp_path, 'alt')
    assert dp._asset_prefix('flash') == 'alt'
    assert dp.asset('flash', 'happy') == os.path.join(str(tmp_path), 'alt', 'alt_happy.png')


# ── 4. 前缀目录缺这张 → 回落到角色 key 目录 ✓；兜底链不变 ✓ ────────────
def test_prefix_miss_then_key_then_fallback(monkeypatch, tmp_path):
    (tmp_path / 'flash').mkdir()
    (tmp_path / 'alt').mkdir()
    (tmp_path / 'flash' / 'flash_angry.png').write_bytes(b'x')      # key 目录有 angry
    (tmp_path / 'alt' / 'alt_idle.png').write_bytes(b'x')           # 前缀目录只有 idle
    _set_env(monkeypatch, tmp_path, 'alt')
    # ① 前缀目录没有 angry → 回落 key 目录 ✓
    assert dp.asset('flash', 'angry').endswith(os.path.join('flash', 'flash_angry.png'))
    # ② 两边都没有的 state → 最终落到前缀目录的 idle ✓
    assert dp.asset('flash', 'whatever_state').endswith(os.path.join('alt', 'alt_idle.png'))


# ── 5. 查档案失败不许崩（风险 1 口径 ✓）──────────────────────────────
def test_registry_failure_is_safe(monkeypatch, tmp_path):
    (tmp_path / 'flash').mkdir()
    monkeypatch.setattr(dp, 'ASSETS', str(tmp_path), raising=False)

    class _Boom:
        def get(self, k):
            raise RuntimeError('boom')

    monkeypatch.setattr(dp, 'MODEL_REGISTRY', _Boom(), raising=False)
    assert dp._asset_prefix('flash') == 'flash', '查档案失败必须回落 key ✓ 不崩 ✗'


# ── 6. UI：有入口 ✓ 保存写 portrait ✓ 且**不复制文件** ✗ ──────────────
def test_ui_entry_binds_without_copying_files():
    with io.open(os.path.join(ROOT, 'model_manager_ui.py'), encoding='utf-8') as fh:
        src = fh.read()
    assert 'ed_portrait' in src and '立绘目录' in src and '_on_pick_portrait' in src
    assert "set_field(self._cur, 'portrait'" in src, '保存必须写档案 portrait ✓'
    seg = src[src.index('def _on_pick_portrait'):]
    seg = seg[:seg.index('def ', 10)]
    for bad in ('shutil.copy', 'copy2', 'shutil.move', 'os.remove', 'os.replace'):
        assert bad not in seg, '⛔ 选立绘不得搬动/覆盖文件 ✗：%s' % bad
