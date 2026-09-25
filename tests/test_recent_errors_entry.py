# -*- coding: utf-8 -*-
"""L4-2 护栏：最近错误**入口**（右键菜单 + 设置系统页）+ 空态文案 + 一键复制 + 不新造第二套

微信侧 L4-2 核验清单：
  ① 入口可点 ② 空态有文案（不是空白 ✗）③ 只走单点出卡 ✓ ④ 一键复制摘要 ✓
"""
from __future__ import annotations

import io
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DP = ROOT / 'desktop_pet.py'
SU = ROOT / 'settings_ui.py'


def _src(p):
    return io.open(p, encoding='utf-8').read()


# ── ① 入口可点：右键菜单 + 设置「系统」页 ───────────────────────────────
def test_entry_in_context_menu():
    s = _src(DP)
    assert "stmenu.addAction('🧯 最近错误')" in s, '右键菜单「状态」里缺最近错误入口 ✗'
    assert 'self.show_recent_errors' in s, '菜单未接到 show_recent_errors ✗'


def test_entry_in_settings_system_page():
    s = _src(SU)
    assert "('🧯 最近错误', self.host.show_recent_errors)" in s, '设置「系统」页缺最近错误入口 ✗'


# ── ② 空态有文案（不是空白 ✗）──────────────────────────────────────────
def test_empty_state_text_present():
    s = _src(DP)
    assert '最近没有失败记录' in s, '空态必须有文案（不得空白）✗'
    import desktop_pet as dp
    import governance as gov
    import pet_diagnosis as d

    class _Fake:
        RECENT_ERRORS_LIMIT = 20
    # 审计读不到 → 走空态 ✓（不打真审计）
    txt = dp.PetWidget.recent_errors_text(_Fake(), limit=5) if hasattr(dp.PetWidget, 'recent_errors_text') else ''
    assert txt, '空态文本不应为空 ✗'
    assert '最近没有失败记录' in txt or '最近失败' in txt


# ── ④ 一键复制摘要 ✓ ───────────────────────────────────────────────────
def test_copy_button_present():
    s = _src(DP)
    assert '📋 复制摘要' in s, '缺一键复制摘要 ✗'
    assert 'clipboard().setText' in s, '复制按钮没真的写剪贴板 ✗'


# ── ③ 不新造第二套：卡片唯一出口不被绕过 ✓ ─────────────────────────────
def test_single_card_exit_not_bypassed():
    import ast
    tree = ast.parse(_src(DP))
    hits, span = [], None
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, 'attr', None) == 'to_card':
            hits.append(node.lineno)
        if isinstance(node, ast.FunctionDef) and node.name == '_notify_failure_card':
            span = (node.lineno, node.end_lineno or node.lineno)
    assert span, '找不到 _notify_failure_card ✗'
    outside = [ln for ln in hits if not (span[0] <= ln <= span[1])]
    assert not outside, f'L4-2 不得新增第二套出卡路径 ✗（to_card 出现在 {outside}）'


def test_reuses_l4_1_data_layer():
    """入口必须复用 L4-1 的整理层（不得自己解析审计 JSON ✗）"""
    s = _src(DP)
    assert '_gov.recent_failure_records(' in s, '未复用 governance.recent_failure_records ✗'
    assert '_diag.recent_errors(' in s, '未复用 pet_diagnosis.recent_errors ✗'
