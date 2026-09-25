# -*- coding: utf-8 -*-
"""v1-B 护栏：失败卡片**唯一出口** + 同代次去重 + 弃权不计判错 + user_facing 上限

微信侧 v1-B 定案（2026-09-25 `WX-桌宠-20260925-04-定-v1B三件`）：
  ① 三档划分认（A 12 / B 19 / C 45）；C 档「已被 L2/L5 覆盖」者**显式登记为有意不标** ✓
  ② B 档「改设置的失败」**不弹卡片**（走状态行/就地提示）✓
  ③ 去重口径：**同一任务代次只出一张卡**；同代次内**闸门卡优先**；**弃权不计入判错统计**；
     **单点出口不得绕过** ✓
  ④ 机制：**显式标记**（`user_facing=True`），不用白名单查表 ✓（未来新增调用点默认不进卡片）
"""
from __future__ import annotations

import ast
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / 'desktop_pet.py'
MAX_USER_FACING = 25

# A 档 12 处涉及的标签前缀（护栏：这些必须标 ✓）
A_TAGS = ('_smart_open', '_vision_content:files_api', '_load_chat_memory', '_save_chat_memory',
          '_load_ai_config', '_record_api_usage', '_save_position')

# ⭐ C 档（有意不标）里「已被 L2/L5 覆盖」的项 —— 显式登记，防以后当遗漏补上 ✗
COVERED_BY_L2_L5 = ('_post_stream:diag', '_audit_failure:diag', '_audit_failure:audit',
                    '_notify_failure_card', '_on_user_facing_failure')
# ⭐ B 档「改设置的失败」＝不弹卡片（走状态行）✓ —— 同样显式登记
SETTINGS_NO_CARD = ('_set_voice_rate', '_set_asr_backend', '_set_asr_extra',
                    '_set_voice_content_mode', '_voice_test')


def _tree():
    return ast.parse(io.open(SRC, encoding='utf-8').read())


def _silent_log_calls():
    """所有 `_silent_log(...)` 调用 → [(tag, user_facing, lineno)]（AST 取值，不走行匹配 ✓）"""
    out = []
    for node in ast.walk(_tree()):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, 'id', None) != '_silent_log' or not node.args:
            continue
        a0 = node.args[0]
        tag = a0.value if isinstance(a0, ast.Constant) and isinstance(a0.value, str) else None
        uf = False
        for kw in node.keywords:
            if kw.arg == 'user_facing' and isinstance(kw.value, ast.Constant):
                uf = bool(kw.value.value)
        out.append((tag, uf, getattr(node, 'lineno', 0)))
    return out


# ── 护栏④：显式标记的数量与覆盖面 ──────────────────────────────────
def test_user_facing_count_within_budget():
    """v1-B 首批恰好 12 处；总数不得超过上限（防以后随手加标记刷屏 ✗）"""
    marked = [t for t, uf, _ in _silent_log_calls() if uf]
    assert len(marked) == 12, f'v1-B 首批应为 12 处，实际 {len(marked)}：{marked}'
    assert len(marked) <= MAX_USER_FACING, f'user_facing 数量超过上限 {MAX_USER_FACING} ✗'


def test_user_facing_covers_expected_tags():
    """A 档 7 组标签（共 12 处）必须都被标注 ✓"""
    marked = [t for t, uf, _ in _silent_log_calls() if uf]
    for pre in A_TAGS:
        assert any(t and t.startswith(pre) for t in marked), f'{pre} 未标记 user_facing ✗'


# ── 护栏：单点出口（不得绕过）───────────────────────────────────────
def test_card_single_exit():
    """源码里只有 `_notify_failure_card` 内能渲染 `to_card` ✓"""
    hits, span = [], None
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Call) and getattr(node.func, 'attr', None) == 'to_card':
            hits.append(node.lineno)
        if isinstance(node, ast.FunctionDef) and node.name == '_notify_failure_card':
            span = (node.lineno, node.end_lineno or node.lineno)
    assert hits, '未找到 to_card 调用 → 护栏本身失效 ✗'
    assert span, '找不到 _notify_failure_card（单点出口被删？）✗'
    outside = [ln for ln in hits if not (span[0] <= ln <= span[1])]
    assert not outside, f'to_card 在单点出口之外被调用 ✗ 行号：{outside}'


def test_intentional_not_marked_registered():
    """C 档“已被 L2/L5 覆盖”与 B 档“改设置不弹卡”→ 显式登记，且确实**没标** ✗"""
    calls = _silent_log_calls()
    marked = [t for t, uf, _ in calls if uf]
    for tag in COVERED_BY_L2_L5 + SETTINGS_NO_CARD:
        assert any(t and t.startswith(tag) for t, _, _ in calls), f'登记项 {tag} 在源码里找不到 ✗'
        assert not any(t and t.startswith(tag) for t in marked), \
            f'{tag} 已登记为“有意不标”，却又被标注了 ✗'


# ── 行为护栏③：同代次一张卡 / 闸门优先 / 弃权不计判错 ────────────────
class _Sig:
    def __init__(self):
        self.msgs = []

    def emit(self, t):
        self.msgs.append(t)


class _FakeWin:
    """只带出卡所需最小状态（不实例化整个 GUI ✓）"""
    FAIL_CARD_TAG_KINDS = ()
    UPSTREAM_LAYERS = ('上游超时', '上游故障', '上游限流')

    def _upstream_notice(self):
        return ''          # L3-1：测试里不探测上游公告 ✓

    def __init__(self, gen=7):
        self._fail_card_gen = None
        self._fail_card_kind = ''
        self._cur_gen = gen
        self.ai_reply_signal = _Sig()


def _diag(layer):
    import pet_diagnosis as d
    return d.Diag(layer, '原因', '影响', '下一步', 'raw')


def test_one_card_per_generation():
    from desktop_pet import PetWidget
    w = _FakeWin()
    assert PetWidget._notify_failure_card(w, _diag('上游故障'), gen=w._cur_gen) == 'emitted'
    assert PetWidget._notify_failure_card(w, _diag('上游超时'), gen=w._cur_gen) == 'deduped'
    assert len(w.ai_reply_signal.msgs) == 1, '同一代次只允许出现一张卡 ✗'


def test_gate_card_has_priority_within_generation():
    from desktop_pet import PetWidget
    w = _FakeWin()
    PetWidget._notify_failure_card(w, _diag('上游故障'), gen=w._cur_gen)
    assert PetWidget._notify_failure_card(w, _diag('本地闸门'), gen=w._cur_gen) == 'emitted', \
        '同代次内闸门卡应优先 ✓'
    assert PetWidget._notify_failure_card(w, _diag('上游超时'), gen=w._cur_gen) == 'deduped'
    assert len(w.ai_reply_signal.msgs) == 2


def test_new_generation_gets_new_card():
    from desktop_pet import PetWidget
    w = _FakeWin(gen=8)
    PetWidget._notify_failure_card(w, _diag('上游故障'), gen=8)
    w._cur_gen = 9
    assert PetWidget._notify_failure_card(w, _diag('上游故障'), gen=9) == 'emitted'
    assert len(w.ai_reply_signal.msgs) == 2


def test_yielded_not_counted(monkeypatch):
    """弃权（count=False）→ 不写判错审计 ✓（定案 ③②）"""
    import desktop_pet as dp
    import governance as gov
    captured = []
    monkeypatch.setattr(gov, 'log_event',
                        lambda kind, actor, action, detail='', allowed=True, extra=None, ms=None:
                        captured.append(kind), raising=True)
    d = dp._audit_failure(RuntimeError('stopped by user'), context='对话', count=False)
    assert d is not None, '弃权也应返回归因结构（供其它路径复用）'
    assert captured == [], f'弃权不得计入判错统计 ✗ 实际写入 {captured}'
