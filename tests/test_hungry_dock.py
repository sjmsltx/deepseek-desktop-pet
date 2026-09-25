# -*- coding: utf-8 -*-
"""缺陷 1 护栏：饥饿态在**贴边**下的表现（Owner 2026-09-25 22:58 裁定四条 ✓）

四条裁定 → 四条要盯死：
  ① 新增「饥饿贴边立绘」`*_peek*_hungry` ✓（缺则**回落普通贴边图**但**不静默失败** ✗ → 审计 warning）
  ② 气泡后追加**食物类 emoji**（池内随机 ✓ 不写死单个 ✗）
  ③ ⛔ **不自动退出贴边**（Owner：会打扰用户 ✗ → 等用户自己拖出 ✓）
  ④ 拖出后 → 显示**饥饿立绘** `*_hungry.png` ✓
"""
from __future__ import annotations

import io
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DP = ROOT / 'desktop_pet.py'
ANIM = ROOT / 'pet_anim.py'


def _src(p):
    return io.open(p, encoding='utf-8').read()


class _FakePet:
    """只带 _check_satiety / 取图选择器所需最小状态 ✓"""
    HUNGRY_BLOCKING_STATES = ('sleep', 'scared')

    def __init__(self, satiety=20, state='idle', docked=False, sleeping=False):
        self.state = state
        self.sleeping = sleeping
        self._edge_side = 'left' if docked else None
        self._edge_mode = 'peek'
        self.current = 'flash'
        self.bubbles = []
        self.entered = 0
        self.ended = []
        self._warned = []
        self._last_satiety_warn = 0
        self._care_suspended_date = ''
        self.active_chat_enabled = False

        class _Aff:
            def satiety(_s, role):
                return satiety
        self.affection = _Aff()

        from desktop_pet import PetWidget
        self._hungry_entry_allowed = lambda: PetWidget._hungry_entry_allowed(self)
        self._peek_hungry_variant = lambda side: PetWidget._peek_hungry_variant(self, side)

    def _enter_hungry(self):
        self.entered += 1
        self.state = 'hungry'

    def _end_state(self, st):
        self.ended.append(st)
        self.state = 'idle'

    def _show_pet_bubble(self, text, *a, **k):
        self.bubbles.append(text)

    def _resume_active_care_if_new_day(self):
        return False

    def _warn_asset_fallback(self, key):
        self._warned.append(key)


# ── ① 进入条件：优先级允许即进入；**贴边不算抢占** ✓ ──────────────────
def test_hungry_entry_allowed_matrix():
    from desktop_pet import PetWidget
    cases = [
        (dict(state='idle', docked=False), True, '原口径：待机可进 ✓'),
        (dict(state='idle', docked=True), True, '贴边+待机 ✓'),
        (dict(state='thinking', docked=True), True, '⭐ 贴边不算抢占（临时表现也放行）✓'),
        (dict(state='thinking', docked=False), False, '未贴边+思考态 → 不进（优先级 ✓）'),
        (dict(state='scared', docked=True), False, '惊吓是硬阻挡 ✓'),
        (dict(state='idle', sleeping=True), False, '睡觉是硬阻挡 ✓'),
    ]
    for kw, want, why in cases:
        got = PetWidget._hungry_entry_allowed(_FakePet(satiety=20, **kw))
        assert got is want, f'{why}：期望 {want} 实得 {got} ✗'


def test_check_satiety_enters_hungry_while_docked():
    """⭐ 贴边 + 低饱食 → **进入饥饿态** ✓（原实现只在 idle 才进 ✗）"""
    from desktop_pet import PetWidget
    p = _FakePet(satiety=20, state='thinking', docked=True)
    PetWidget._check_satiety(p)
    assert p.entered == 1 and p.state == 'hungry', p.__dict__.get('state')


def test_check_satiety_does_not_undock():
    """③ ⛔ **不自动退出贴边**（Owner：会打扰用户 ✗）"""
    from desktop_pet import PetWidget
    p = _FakePet(satiety=20, state='thinking', docked=True)
    PetWidget._check_satiety(p)
    assert p._edge_side == 'left', '饥饿巡检不得自动退出贴边 ✗'
    src = _src(DP)
    i = src.index('def _check_satiety')
    body = src[i:i + 1800]
    for bad in ('_exit_dock_to_free', '_enter_dock', 'undock'):
        assert bad not in body, f'_check_satiety 里不该出现 {bad} ✗（会自动退出贴边）'


def test_exit_hungry_when_satiety_recovers():
    """③ 附：饱食度回升 ≥30 → 退出饥饿态 ✓（退回普通贴边图由渲染层决定 ✓）"""
    from desktop_pet import PetWidget
    p = _FakePet(satiety=80, state='hungry', docked=True)
    PetWidget._check_satiety(p)
    assert p.ended == ['hungry'], p.ended


# ── ① 饥饿贴边图：有则用 ✓ 缺则回落 + 审计 warning ✓（不静默 ✗）────────
class _PM:
    """最小 QPixmap 替身（代码会调 isNull() ✓）"""
    def __init__(self, tag=''):
        self.tag = tag

    def isNull(self):
        return False

    def __eq__(self, other):
        return isinstance(other, _PM) and other.tag == self.tag

    def __repr__(self):
        return 'PM(%s)' % self.tag


def test_peek_hungry_variant_prefers_hungry_pixmap():
    from desktop_pet import PetWidget
    p = _FakePet()
    p.peek_hungry_pixmap = _PM('HUNGRY_PM')
    assert PetWidget._peek_hungry_variant(p, 'left') == _PM('HUNGRY_PM')
    p.peek_top_hungry_pixmap = _PM('TOP_HUNGRY')
    assert PetWidget._peek_hungry_variant(p, 'top') == _PM('TOP_HUNGRY')
    p.peek_bottom_hungry_pixmap = _PM('BOT_HUNGRY')
    assert PetWidget._peek_hungry_variant(p, 'bottom') == _PM('BOT_HUNGRY')


def test_peek_hungry_variant_warns_on_missing():
    """缺图 → 回落（返回 None ✓）**且记审计 warning** ✓（只记一次 ✓ 不刷屏 ✓）"""
    from desktop_pet import PetWidget
    p = _FakePet()
    assert PetWidget._peek_hungry_variant(p, 'left') is None
    assert p._warned, '缺图必须记审计 warning（不静默失败）✗'
    assert 'hungry' in p._warned[0]
    n = len(p._warned)
    PetWidget._peek_hungry_variant(p, 'left')
    assert len(p._warned) == n, '同一角色不得重复刷审计 ✗'


def test_peek_rendering_prefers_hungry_when_state_hungry():
    """源码护栏：贴边渲染在 `state == 'hungry'` 时**优先**取饥饿贴边图 ✓"""
    src = _src(DP)
    i = src.index('def _show_peek')
    body = src[i:i + 4200]
    assert body.count('_peek_hungry_variant') >= 2, '四方向里左右/上下两处都要接饥饿图 ✓'
    assert "getattr(self, 'state', '') == 'hungry'" in body


# ── ④ 拖出/恢复：**先判饥饿** ✓（不再硬回待机 ✗）────────────────────────
def test_restore_display_state_checks_hungry_first():
    import pet_anim

    class _W:
        sleeping = False

        def __init__(self):
            self.calls = []

        def _still_hungry(self):
            return True

        def _enter_hungry(self):
            self.calls.append('hungry')

        def _show_idle(self):
            self.calls.append('idle')

        def _show_state_image(self, st):
            self.calls.append(st)

    w = _W()
    pet_anim.restore_display_state(w)
    assert w.calls == ['hungry'], f'拖出后应先判饥饿 ✗ 实得 {w.calls}'

    class _W2(_W):
        def _still_hungry(self):
            return False
    w2 = _W2()
    pet_anim.restore_display_state(w2)
    assert w2.calls == ['idle'], w2.calls


def test_restore_display_state_sleep_wins():
    import pet_anim

    class _W:
        sleeping = True

        def __init__(self):
            self.calls = []

        def _still_hungry(self):
            return True

        def _show_state_image(self, st):
            self.calls.append(st)

        def _show_idle(self):
            self.calls.append('idle')

        def _enter_hungry(self):
            self.calls.append('hungry')
    w = _W()
    pet_anim.restore_display_state(w)
    assert w.calls == ['sleep'], '睡眠优先级最高 ✓'


# ── ② 气泡 emoji 池 ─────────────────────────────────────────────────
def test_hungry_peek_asset_present_and_spec():
    """批 D：饥饿贴边资产**在库** ✓（尺寸/模式对齐参考图 ✓）—— 防以后被误删 ✗

    ⚠️ 已知差异（微信侧 2026-09-25 提示 + 我方实测 ✓ **未动图** ✗ 等决策）：
      本图 alpha 主体盒 = (0,143,682,1024) → **占满全宽 100%** ✗
      参考 `flash_peek.png` = (12,233,452,1024) → **只占左侧 65%** ✗
      → 渲染画布放置逻辑相同（同尺寸 682×1024 ✓）→ 差异在**主体占比** ✓ 贴边时会显更宽更高 ✗
      → 若要对齐属**资产侧**调整（缩到 65% + 左对齐 + 顶边对齐 233）→ 待微信侧问 Owner ✓ 我不擅自改图 ✗
    """
    from PIL import Image
    p = ROOT / 'assets' / 'flash' / 'flash_peek_hungry.png'
    assert p.is_file(), 'flash_peek_hungry.png 缺失 ✗（贴边饥饿会回落到普通贴边图）'
    with Image.open(p) as im:
        assert im.size == (682, 1024), f'尺寸应与 flash_peek.png 一致 ✓ 实得 {im.size}'
        assert im.mode == 'RGBA', im.mode
        bb = im.split()[-1].getbbox()
        assert bb is not None, '透明通道为空 ✗'
        assert bb[3] == im.height, '主体应触底（贴边对齐用）✗'


def test_pro_peek_assets_waiting_for_hungry():
    """批 D：pro **有整套贴边图** ✓ → 所以 `pro_peek*_hungry` 也需要 ✓（登记现状，防以后忘 ✓）"""
    base = ROOT / 'assets' / 'pro'
    for name in ('pro_peek.png', 'pro_peek_top.png', 'pro_peek_bottom.png'):
        assert (base / name).is_file(), f'{name} 缺失（pro 应有贴边态）✗'


def test_hungry_bubble_uses_random_food_emoji():
    src = _src(DP)
    m = re.search(r'HUNGRY_EMOJI_POOL\s*=\s*\(([^)]*)\)', src)
    assert m, '找不到食物表情池 ✗'
    pool = re.findall(r"'([^']+)'", m.group(1))
    assert len(pool) >= 5, f'表情池至少 5 个（不许写死单个 ✗）实得 {len(pool)}'
    assert any(ch in ''.join(pool) for ch in ('🍚', '🍜', '🍗', '🥢', '🍴', '😋')), \
        '池里应有食物/餐具类表情 ✓'
    assert 'random.choice(HUNGRY_EMOJI_POOL)' in src, '取用必须是随机 ✓'
