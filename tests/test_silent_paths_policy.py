# -*- coding: utf-8 -*-
"""风险 1 护栏：关键路径的异常**不许静默** ✗（2026-10-03 夜检报告 / 第一批）。

口径（避免误伤 ✗）：
  · 本护栏只钉**关键路径**上的少数几处 —— 不是"全仓不许有静默 except"（那会有合理兜底 ✓）
  · 关键路径 = 配置热加载 / 网络请求 / 记账 这三类：
    一旦失败却无声，界面会给出**与事实相反**的结论（如"✅ 已修改"），比崩掉更难查
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, 'desktop_pet.py')


def _src():
    with io.open(APP, encoding='utf-8') as fh:
        return fh.read()


def _except_block(src, anchor, span=120):
    """取 anchor 之后 span 字符内的第一个 except 块（含其后 4 行）"""
    i = src.index(anchor)
    seg = src[i:i + span * 40]
    m = re.search(r'\n(\s*)except\b[^\n]*:\n((?:.*\n){1,4})', seg)
    assert m, '未能在 %s 之后找到 except 块' % anchor
    return m.group(2)


# ── 1. 配置热加载失败不许静默（否则"✅ 已修改"是假的 ✗）───────────────
def test_config_hot_reload_failure_is_logged():
    blk = _except_block(_src(), "elif key == 'sedentary_minutes':")
    assert '_silent_log' in blk, '配置热加载的 except 必须留日志（不许 pass 静默 ✗）'
    assert "hot_reload" in blk or 'hot_reload' in _src()


# ── 2. 自动查余额失败不许静默（网络路径 ✓ 但仍不打扰用户 ✓）──────────
def test_auto_balance_refresh_failure_is_logged():
    # ⚠️ 锚点必须**唯一**（`balance_auto_minutes` 在文件前部也出现过 ✗ 会抓错区块 ✓）
    blk = _except_block(_src(), 'if self.api_stats.balance_stale(')
    assert '_silent_log' in blk, '自动刷新余额的 except 必须留日志 ✗'
    assert 'balance_auto' in blk


# ── 3. ⭐ 反向护栏：本护栏**只管关键路径**，不是全仓一刀切 ✗ ────────
def test_policy_scope_is_bounded_not_blanket():
    src = _src()
    # 读配置回落默认值这类**允许**静默（属合理兜底 ✓，本护栏故意不碰 ✓）
    assert re.search(r"with open\(CONFIG_PATH, 'r', encoding='utf-8'\) as _f:\n\s*self\.active_chat_enabled = bool\(", src)
    # 且全仓仍存在静默 except（证明护栏口径是“关键路径”而非“全仓禁绝” ✓）
    assert len(re.findall(r'except Exception:\s*\n\s*pass', src)) > 0
