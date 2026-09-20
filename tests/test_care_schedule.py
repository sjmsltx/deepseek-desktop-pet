# -*- coding: utf-8 -*-
"""关心节流 / 场景触发 / 措辞护栏（v6.60 批 4）

锁住「效果不明显」与「别从打扰变成骚扰」之间的平衡：
- 深夜静默、冷却 20 分钟、每日上限 8 次（三重节流）
- 场景触发：只有开启前台感知、且「专注 → 不表态」切换后 30–300 秒窗口内才提前关心
- 兜底措辞库：≥15 句、不重复使用上一条

运行：python -m pytest tests/test_care_schedule.py -q
"""
import datetime
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
    p.memories = type('M', (), {'items': [], 'add': lambda s, *a, **k: s.items.append((a, k)) or {},
                                'all': lambda s, r: []})()
    return p


def test_night_silence():
    p = _pet()
    for h in (23, 0, 3, 7):
        assert p._is_night(h), '%d 点应属深夜静默' % h
    for h in (8, 12, 17, 22):
        assert not p._is_night(h), '%d 点不该静默' % h


def test_cooldown_blocks_then_allows():
    p = _pet()
    p._is_night = lambda *a, **k: False        # 锁掉深夜静默，让用例与运行时刻无关
    p._care_last_at = time.time() - 60
    ok, why = p._care_allowed()
    assert not ok and '冷却' in why, '冷却期内应被拦下'
    p._care_last_at = time.time() - (p.CARE_COOLDOWN_MIN * 60 + 10)
    ok, why = p._care_allowed()
    assert ok, '冷却结束后应放行，实际被拦：%s' % why


def test_daily_cap_and_reset():
    p = _pet()
    p._is_night = lambda *a, **k: False        # 同上：不因跑在深夜而提前被静默拦掉
    p._care_last_at = 0
    day = datetime.datetime.now().strftime('%Y-%m-%d')
    p._care_today = {'date': day, 'n': p.CARE_DAILY_MAX}
    ok, why = p._care_allowed()
    assert not ok and '上限' in why, '达到当日上限应被拦下'
    p._care_today = {'date': day, 'n': p.CARE_DAILY_MAX - 1}
    assert p._care_allowed()[0], '未达上限应放行'
    p._care_today = {'date': '2000-01-01', 'n': 999}
    assert p._care_allowed()[0], '跨天后计数应重置'


def test_care_mark_counts():
    p = _pet()
    p._care_last_at, p._care_today = 0, None
    p._care_mark()
    p._care_mark()
    assert p._care_today['n'] == 2
    assert p._care_last_at > 0


def test_scene_requires_foreground_flag():
    p = _pet()
    p.foreground_aware = False
    p._note_foreground('code.exe')
    p._note_foreground('chrome.exe')
    assert not p._scene_ready(), '未开启前台感知时不得走场景触发'


def test_scene_window_and_single_use():
    p = _pet()
    p.foreground_aware = True
    p._note_foreground('code.exe')
    p._note_foreground('chrome.exe')
    assert not p._scene_ready(), '刚切换（<30 秒）不该立刻打扰'
    p._fg_break_at = time.time() - 90
    assert p._scene_ready(), '30–300 秒窗口内应可用'
    p._fg_break_at = time.time() - 1000
    assert not p._scene_ready(), '超过 300 秒不再是休息间隙'
    p._fg_break_at = time.time() - 90
    p._scene_used = True
    assert not p._scene_ready(), '同一间隙只用一次'


def test_scene_only_from_focus_category():
    """从浏览器切到浏览器/桌面不算休息间隙（本来就没在专注）"""
    p = _pet()
    p.foreground_aware = True
    p._scene_used = True
    p._note_foreground('chrome.exe')
    p._note_foreground('notepad.exe')
    assert p._scene_used is True, '非「专注 → 不表态」的切换不应开启场景窗口'


def test_fallback_library_variety():
    import care_engine as ce
    zh = ce.fallback_lines('zh', 'all')
    assert len(zh) >= 15, '兜底措辞库太少（%d 句）' % len(zh)
    assert len(set(zh)) == len(zh), '措辞库存在重复句'
    assert ce.fallback_lines('en', 'all'), '英文库为空'
    assert ce.fallback_lines('xx', 'all'), '未知语言应回退到中文库'
    last = zh[0]
    for _ in range(20):
        assert ce.pick_fallback('zh', 'care', last) != last, '会连续重复上一条措辞'


def test_source_guard_throttle_wired():
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    for token in ('CARE_COOLDOWN_MIN', 'CARE_DAILY_MAX', 'self._care_allowed()',
                  'self._care_mark()', 'self._scene_ready()'):
        assert token in src, '节流/场景触发未接线：%s' % token
