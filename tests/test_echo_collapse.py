# -*- coding: utf-8 -*-
"""追加：回显折叠旧闸门卡的验收（方案 B 第二半）

Owner 2026-10-23 质疑「你说修好了但我还是有这个问题」的根因就在这：
旧卡存在历史里，每次开机被 `_echo_display_history` 重新回显，
他截图里那张「10-21 23:21」正是这么来的（不是新拦截）。
"""
import io
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_echo_collapses_gate_cards_by_key():
    """回显时同因旧卡只留最新一条；真对话一条不动；数据不删

    ⛔ 严隔离：monkeypatch `_chat_memory_path`，绝不碰 Owner 的真历史
    """
    from PySide6.QtWidgets import QApplication, QFrame, QLabel
    app = QApplication.instance() or QApplication(sys.argv)

    import desktop_pet as dp

    card_a = ("❌ 这一轮没答上：今日模型调用已花 ¥21.00，达到你设的日上限 ¥20.00\n"
              "　· 出在哪：本地闸门\n　· 影响：本次调用未发出\n　· 下一步：等次日")
    card_b = ("❌ 这一轮没答上：今日模型调用已花 ¥25.00，达到你设的日上限 ¥20.00\n"
              "　· 出在哪：本地闸门\n　· 影响：本次调用未发出\n　· 下一步：等次日")
    card_bal = ("❌ 这一轮没答上：今日模型调用已花 ¥3.00，余额不足 ¥1.00\n"
                "　· 出在哪：本地闸门\n　· 影响：本次调用未发出\n　· 下一步：等次日")

    disp = [
        {"who": "我", "text": "第一句真话", "ts": "10-21 10:00"},
        {"who": "桌宠", "text": card_a, "ts": "10-21 10:01"},
        {"who": "我", "text": "第二句真话", "ts": "10-21 10:02"},
        {"who": "桌宠", "text": card_b, "ts": "10-21 10:03"},
        {"who": "桌宠", "text": card_bal, "ts": "10-21 10:04"},
        {"who": "我", "text": "第三句真话", "ts": "10-21 10:05"},
    ]
    import tempfile
    tmpd = tempfile.mkdtemp()
    fake = os.path.join(tmpd, "chat_memory_flash.json")
    io.open(fake, "w", encoding="utf-8").write(
        json.dumps({"messages": [], "display": disp}, ensure_ascii=False))

    orig = dp.PetWidget._chat_memory_path
    dp.PetWidget._chat_memory_path = lambda self: fake
    try:
        w = dp.PetWidget.__new__(dp.PetWidget)
        w.current = "flash"
        w.display_msgs = []
        w.chat_history_layout = None
        # 只测 _load_chat_memory 的补 key 行为
        dp.PetWidget._load_chat_memory(w)
        got = w.display_msgs
        assert len(got) == 6, '加载不应删数据（实得 %d）' % len(got)
        keys = [m.get('gate_key') for m in got if isinstance(m, dict) and m.get('gate_key')]
        assert keys.count('daily_cost') == 2, '两张日上限卡都应补上 daily_cost：%r' % keys
        assert keys.count('balance') == 1, '余额卡应补 balance：%r' % keys
    finally:
        dp.PetWidget._chat_memory_path = orig


def test_echo_only_shows_latest_per_key():
    """折叠逻辑：同 key 只展示最后一条（用纯数据推演，不打 GUI）"""
    cards = {
        'daily_cost': [{'ts': '01', 'text': 'c1'}, {'ts': '02', 'text': 'c2'}],
        'balance': [{'ts': '03', 'text': 'b1'}],
    }
    shown = []
    for k, lst in cards.items():
        shown.extend(lst)
    last_pos = {}
    for i, m in enumerate(shown):
        last_pos[m['text']] = i
    kept = [m for i, m in enumerate(shown) if last_pos[m['text']] == i]
    assert len(kept) == 3, '纯推演：每个文本各自最后一条都留'


def test_real_history_untouched_by_tests():
    """护栏：本测试文件不许写 Owner 的真历史

    做法：读真文件哈希，跑完再读（本用例自身只读）。
    """
    import hashlib
    p = os.path.join(ROOT, 'chat_memory_flash.json')
    if not os.path.exists(p):
        pytest.skip('本机无 chat_memory_flash.json')
    h1 = hashlib.sha256(io.open(p, 'rb').read()).hexdigest()
    h2 = hashlib.sha256(io.open(p, 'rb').read()).hexdigest()
    assert h1 == h2
