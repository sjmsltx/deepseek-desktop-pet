# -*- coding: utf-8 -*-
"""扒边探头：开关 / 顺序修正 / 看门狗兜底（v6.61）

锁住用户反馈的缺陷「扒边缩回后过一会儿自己弹出来、而且不再缩回」：
- 节流不通过的轮次不得探头（v6.61 把探头挪到「确认要说话」之后）
- 开关关闭（默认）：到点也不弹人，只冒关心气泡
- 开关开启：探头 + 挂看门狗；说完话由 _hide_bubble 收回
- 看门狗兜底：探头后一直没说出话（AI 判定不说 / 线程异常）→ 强制收回

运行：python -m pytest tests/test_dock_rehide.py -q
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
    p.memories = type('M', (), {'items': [], 'add': lambda s, *a, **k: s.items.append((a, k)) or {},
                                'all': lambda s, r: []})()
    return p


def _dock(p, dock_probe):
    """把桌宠置于「扒边中、未弹出」状态，并设定探头开关"""
    p._edge_side = 'left'
    p._edge_mode = 'peek'
    p._edge_popped = False
    p._dock_rehide = False
    p.active_chat_enabled = True
    p.sleeping = False
    p.foreground_aware = False
    p.ai_enabled = False          # 走兜底措辞分支，避免真起线程
    p.dock_probe = bool(dock_probe)


def test_throttled_does_not_probe():
    """节流未到点：不得弹出，也不得留下无法清零的收回标记（v6.61 顺序修正）"""
    p = _pet()
    _dock(p, dock_probe=True)
    p._active_chat_next = time.time() + 600
    popped = []
    p._popup_from_dock = lambda: popped.append(1)
    p._check_active_chat()
    assert popped == [], '节流不通过时不得探头'
    assert p._dock_rehide is False, '不得留下收回标记'
    assert p._edge_popped is False


def test_cooldown_does_not_probe():
    """冷却中：同样不得探头"""
    p = _pet()
    _dock(p, dock_probe=True)
    p._active_chat_next = 0
    p._care_last_at = time.time()   # 刚关心过 → 20 分钟冷却
    popped = []
    p._popup_from_dock = lambda: popped.append(1)
    p._check_active_chat()
    assert popped == [], '冷却期内不得探头'


def test_option_off_bubbles_without_probe():
    """开关关闭：到点也不弹人，但关心气泡照旧（用户要的「只冒气泡」）"""
    p = _pet()
    _dock(p, dock_probe=False)
    p._active_chat_next = 0
    p._care_allowed = lambda: (True, '')
    popped = []
    p._popup_from_dock = lambda: popped.append(1)
    p._check_active_chat()
    assert popped == [], '关闭开关时不得弹出整个人'
    assert p._edge_popped is False
    assert p._dock_rehide is False, '没探头就不该有收回标记'
    assert p._bubble_mode == 'care', '关闭开关时仍应冒关心气泡'


def test_option_on_probes_and_arms_watchdog():
    """开关开启：探头 + 挂看门狗"""
    p = _pet()
    _dock(p, dock_probe=True)
    p._active_chat_next = 0
    p._care_allowed = lambda: (True, '')

    def _pop():
        p._edge_popped = True
    p._popup_from_dock = _pop
    p._check_active_chat()
    assert p._edge_popped is True, '开启开关时应弹出'
    assert p._dock_rehide is True, '应挂上收回标记'
    assert p._probe_timer.isActive(), '应挂上看门狗'
    p._rehide_after_probe()      # 收尾：避免污染后续用例


def test_hide_bubble_rehides_after_probe():
    """说话结束（气泡隐藏）→ 自动缩回扒边，标记清零"""
    p = _pet()
    _dock(p, dock_probe=True)
    p._edge_popped = True
    p._dock_rehide = True
    entered = []
    p._enter_dock = lambda side, y: entered.append(side)
    p._hide_bubble()
    assert entered == ['left'], '气泡说完应自动缩回扒边'
    assert p._dock_rehide is False, '收回标记应清零'


def test_watchdog_forces_rehide_without_message():
    """看门狗：探头后一直没说出话 → 强制收回；未探头时不得乱动"""
    p = _pet()
    _dock(p, dock_probe=True)
    p._edge_popped = True
    p._dock_rehide = True
    entered = []
    p._enter_dock = lambda side, y: entered.append(side)
    p._probe_watchdog()
    assert entered == ['left'], '超时未说话应强制收回'
    assert p._dock_rehide is False
    entered.clear()
    p._probe_watchdog()
    assert entered == [], '没有探头标记时看门狗不应做任何事'


def test_toggle_persists_via_save_cfg():
    """开关落盘：走既有 _save_cfg_value 通道，不直接写 config"""
    p = _pet()
    saved = {}
    p._save_cfg_value = lambda k, v: (saved.__setitem__(k, v), True)[1]
    p.dock_probe = False
    p.toggle_dock_probe()
    assert p.dock_probe is True and saved.get('dock_probe') is True
    p.toggle_dock_probe()
    assert p.dock_probe is False and saved.get('dock_probe') is False


def test_bubble_fits_dock_window():
    """扒边窄窗里气泡宽度必须夹在窗口内（否则关心语被硬裁成残句）"""
    p = _pet()
    _dock(p, dock_probe=False)
    p.setFixedSize(p.pet_size, 340)
    p.bubble.setText('这是一句用来测试扒边窄窗里气泡宽度的关心话')
    p.bubble.show()
    p._place_bubble()
    assert p.bubble.width() <= p.width() - 8
    assert p.bubble.x() >= 0 and p.bubble.x() + p.bubble.width() <= p.width()


def test_source_guard_order_and_wiring():
    """源码护栏：探头必须排在节流判定之后，且开关/看门狗均已接线"""
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    for token in ('PROBE_WATCHDOG_MS', 'self._probe_from_dock()', '_rehide_after_probe',
                  '_probe_watchdog', "cfg.get('dock_probe'", "'dock_probe'"):
        assert token in src, '扒边探头未接线：%s' % token
    body = src.split('def _check_active_chat(self):', 1)[1].split('\n    def ', 1)[0]
    body = body.split('"""', 2)[2]   # 去掉 docstring（里面提到了 _probe_from_dock）
    assert body.index('_care_allowed') < body.index('_probe_from_dock'), \
        '探头必须排在节流判定之后（v6.61 顺序修正）'
    assert 'self._popup_from_dock()' not in body.split('_care_allowed')[0], \
        '节流判定之前不得出现探头动作'
