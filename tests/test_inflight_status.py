# -*- coding: utf-8 -*-
"""在途状态（L1 秒表）+ 资源漏配审计（v6.79 · P0 的 L1）

背景（Owner 2026-09-23 15:43 实测）：上游 DeepSeek API 中断时，发消息卡了几十秒才回，
而使用者**只能靠外部邮件**才能判断「服务器崩了」✗ —— 因为在途状态只有一行 11px 灰字：
**没有秒数、没有"在等什么"、重试文案一闪即过** ✗。

另采纳微信侧 89 号的加固建议：`asset()` 对任何键都会**静默兜底**到 fallback / `{role}_idle.png` ✗
→ 「资源漏配」永远不被发现，而它正是今天缺陷 75 的共同土壤 ✓
→ 无专属素材时记一条审计 warning ✓（**每键只记一次**，防噪声 ✓）

运行：python -m pytest tests/test_inflight_status.py -q
"""
import os
import sys
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def _pet():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(sys.argv)
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    return p


def test_status_line_shows_elapsed_seconds():
    """在途状态必须带秒表（原先只有一行灰字，看不出等了多久）"""
    p = _pet()
    p._update_ai_status('正在思考…')
    assert p._status_widget is not None, '应生成状态行'
    assert '已等' in p._status_widget.text(), p._status_widget.text()
    p._ai_status_t0 = time.time() - 47          # 模拟已等 47 秒
    p._render_ai_status()
    txt = p._status_widget.text()
    assert '已等 47s' in txt and '正在思考' in txt, txt


def test_status_text_updates_in_place_not_recreate():
    """重试文案到来时应**原地刷新**（原先删旧建新 → 一闪即过 ✗）"""
    p = _pet()
    p._update_ai_status('正在思考…')
    w = p._status_widget
    p._update_ai_status('正在思考…（服务繁忙，5 秒后第 2 次重试…）')
    assert p._status_widget is w, '状态行应原地刷新，而不是删旧建新'
    assert '第 2 次重试' in p._status_widget.text(), p._status_widget.text()


def test_status_tick_timer_lifecycle():
    """秒表生命周期：状态行在 → 在跑；状态行移除 → 必须停（否则空转）"""
    p = _pet()
    p._update_ai_status('正在思考…')
    assert p._ai_status_timer.isActive(), '状态行在时秒表应在跑'
    p._remove_status_line()
    assert not p._ai_status_timer.isActive(), '状态行移除后秒表必须停'
    assert p._status_widget is None


def test_asset_fallback_writes_audit_warning_once(monkeypatch):
    """资源漏配不再静默：无专属素材时写审计 warning，且**每键只记一次**"""
    import governance as gov
    p = _pet()
    captured = []
    monkeypatch.setattr(gov, 'log_event', lambda *a, **k: captured.append((a, k)))
    key = '绝不存在的场景键'
    p.scene_imgs.pop(key, None)
    p._get_scene_img(key)
    p._get_scene_img(key)          # 第二次不应再记
    hits = [c for c in captured if key in str(c)]
    assert len(hits) == 1, '同一键只应记一次，实际 %d 条：%r' % (len(hits), captured)
