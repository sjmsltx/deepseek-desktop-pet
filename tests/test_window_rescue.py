# -*- coding: utf-8 -*-
"""窗口拖出屏幕就失联（Owner 2026-11-01 报，已存在数月）

## Owner 原话
    「有的时候啊如果拖这个桌宠拖快了直接把它拖到上面的屏幕之外，这个时候直接就卡住了
      关都没有办法关……你想想办法怎么解决吧，我觉得可以就是它自动检测到被整到屏幕上面去
      之后给它自动拉下来，或者说是你给他整一个按钮可以强制推出的那种」

## 根因链（实测，四条叠加才致命）
1. `mouseMoveEvent` 裸 `self.move(...)`，**无屏幕钳制** → 拖快一次采样跳变就扔出屏幕（实测 y=-600）
2. 窗口标志 `Qt.Tool` → **不在任务栏、不在 Alt+Tab**
3. `_ensure_tray()` 唯一调用点是 `hide_to_tray()` → **平时没有托盘图标**
4. 窗口在屏幕外 → 右键菜单点不到
⇒ 用户「看不到、点不到、切不到、也没有托盘」，只能进任务管理器。

本文件锁住六道防线，任何一道失守都会让 bug 复发。
"""
import os
import sys

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QPA_FONTDIR', r'C:\Windows\Fonts')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtCore import QPoint  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

import desktop_pet as dp  # noqa: E402
import affection_engine as ae  # noqa: E402


def _pet(tmp_path):
    """建实例并把**所有会挪窗口的定时器停掉**

    ⚠ 2026-11-01：本轮两次「单跑绿、全量红」都是同一个原因 ——
      周期自检（5 秒）和动画定时器会在测试中途把窗口挪走，
      断言拿到的是「它挪完之后」的位置。统一在 helper 里停掉，
      个别测试要测定时器行为时自己再启动。
    """
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p.affection = ae.AffectionEngine(str(tmp_path / 'aff.json'))
    p.show()
    _app.processEvents()
    for _name in ('_lost_timer', '_random_action_timer', 'anim_timer',
                  'blink_timer', '_satiety_timer'):
        _t = getattr(p, _name, None)
        if _t is not None:
            try:
                _t.stop()
            except Exception:
                pass
    return p


class _GP:
    def __init__(self, pt):
        self._pt = pt

    def toPoint(self):
        return self._pt


class _MoveEvt:
    """模拟拖拽中的 mouseMoveEvent 事件"""
    def __init__(self, x, y):
        self._pt = QPoint(x, y)

    def globalPosition(self):
        return _GP(self._pt)

    def buttons(self):
        return dp.Qt.LeftButton

    def accept(self):
        return None


# ---------- ① 拖拽钳制（防患于未然）----------
@pytest.mark.parametrize('mouse', [(300, -600), (300, -900), (-900, -900), (300, -2000)])
def test_drag_upward_is_clamped(tmp_path, mouse):
    """往上拖：钳制必须挡住（顶部贴边已移除，跑到上方之外没有合法用途）"""
    p = _pet(tmp_path)
    p.move(200, 200)
    _app.processEvents()
    p.dragging = True
    p.drag_offset = QPoint(0, 0)
    p.mouseMoveEvent(_MoveEvt(*mouse))
    _app.processEvents()
    p.dragging = False
    g = _app.primaryScreen().availableGeometry()
    assert p.y() >= g.top(), (
        '拖到 %r 之后 y=%d 跑到了屏幕上方之外（top=%d）' % (mouse, p.y(), g.top()))


@pytest.mark.parametrize('mouse', [(99999, 300), (300, 99999), (-9000, 300)])
def test_drag_sideways_not_clamped_but_release_rescues(tmp_path, mouse):
    """左右/底部**不钳**（Owner 要求，那是贴边吸附的地盘）⇒ 靠松手救援兜底

    这条测的正是「不许把钳制加回左右下」：拖动过程中允许越界，
    但松手时必须被 `_rescue_if_lost` 拉回可见区。
    """
    p = _pet(tmp_path)
    p.move(200, 200)
    _app.processEvents()
    p.dragging = True
    p.drag_offset = QPoint(0, 0)
    p.mouseMoveEvent(_MoveEvt(*mouse))
    _app.processEvents()
    # 拖动中允许越界（钳制只管顶部）
    p.mouseReleaseEvent(_MoveEvt(*mouse))
    _app.processEvents()
    assert p._visible_area() >= 0.5, (
        '拖到 %r 松手后只剩 %.0f%% 可见 —— 松手救援没接住'
        % (mouse, p._visible_area() * 100))


def test_drag_above_screen_stops_at_top_edge(tmp_path):
    """顶边直接抵住：顶部贴边已移除，跑到上方之外没有任何合法用途"""
    p = _pet(tmp_path)
    p.dragging = True
    p.drag_offset = QPoint(0, 0)
    p.mouseMoveEvent(_MoveEvt(300, -2000))
    _app.processEvents()
    p.dragging = False
    g = _app.primaryScreen().availableGeometry()
    assert p.y() >= g.top(), '窗口仍跑到屏幕上方之外（y=%d < top=%d）' % (p.y(), g.top())


# ---------- ② 钳制函数本身 ----------
def test_clamp_only_touches_top(tmp_path):
    """钳制**只动 y**，且只把 y 顶到屏幕顶边；x 和底部一律原样返回

    ⛔ 这条是 Owner 2026-11-01 指示的守门测试：
       「左右和下边不用搞这个，只要上面就行」
       谁把左右/底部的钳制加回来，这里就红。
    """
    p = _pet(tmp_path)
    g = _app.primaryScreen().availableGeometry()
    cases = [(-5000, -5000), (5000, 5000), (300, -600), (-300, 99999), (99999, 300)]
    for x, y in cases:
        nx, ny = p._clamp_visible(x, y)
        assert nx == x, 'x 被钳了（%r → %r）—— 左右不该钳，那是贴边吸附的地盘' % (x, nx)
        want_y = max(g.top(), y)
        assert ny == want_y, 'y 钳制结果不对：%r → %r（应为 %r）' % (y, ny, want_y)


def test_clamp_does_not_move_normal_position(tmp_path):
    p = _pet(tmp_path)
    g = _app.primaryScreen().availableGeometry()
    x = g.left() + 100
    y = g.top() + 100
    assert p._clamp_visible(x, y) == (x, y)


def test_nearest_screen_survives_offscreen_point(tmp_path):
    """屏幕外坐标也要能取到一块屏 —— 用「最近屏」而不是 screenAt 单点

    ⚠ 实测 `QApplication.screenAt(300, -600)` 返回 None。若用它判界，
      钳制逻辑会直接失效（这正是原 bug 能发生的原因之一）。
    """
    p = _pet(tmp_path)
    g = p._nearest_screen(300, -600, p.width(), p.height())
    assert g is not None, '屏幕外坐标取不到任何屏，钳制会失效'


# ---------- ③ 松开救援 ----------
def test_release_rescues_when_lost(tmp_path):
    p = _pet(tmp_path)
    p.move(300, -900)
    _app.processEvents()
    assert p._visible_area() < 0.2, '前提不成立：窗口居然还可见'
    p.dragging = True
    p.mouseReleaseEvent(_MoveEvt(300, -900))
    _app.processEvents()
    assert p._visible_area() >= 0.5, '松手后窗口仍在屏幕外'


def test_rescue_returns_false_when_visible(tmp_path):
    p = _pet(tmp_path)
    g = _app.primaryScreen().availableGeometry()
    p.move(g.left() + 100, g.top() + 100)
    _app.processEvents()
    assert p._rescue_if_lost('test') is False, '窗口好好的却被拉了'


# ---------- ③b 贴边吸附范围不得与钳制重叠（Owner 这次报的问题）----------
@pytest.mark.parametrize('side', ['left', 'right', 'bottom'])
def test_dock_trigger_position_is_reachable_after_clamp(tmp_path, side):
    """贴边吸附所需的位置，必须能通过钳制（否则吸附永远触发不了）

    实测过的原始症状：底吸附需要 y ≥ 521，而「留一半窗口」的钳制上界是 519
    ⇒ 差 2px，底部吸附被封死。
    """
    p = _pet(tmp_path)
    g = _app.primaryScreen().geometry()
    w, ps = p.width(), p.pet_size
    if side == 'left':
        need = 18 - (w - ps) // 2               # x ≤ need 才吸附左边
        nx, _ny = p._clamp_visible(need, 300)
        assert nx == need, '左吸附位置被钳制改动（%d → %d）' % (need, nx)
    elif side == 'right':
        need = (g.right() - 18) - (w + ps) // 2  # x ≥ need 才吸附右边
        nx, _ny = p._clamp_visible(need, 300)
        assert nx == need, '右吸附位置被钳制改动（%d → %d）' % (need, nx)
    else:
        need = (g.bottom() - 18) - ps            # y ≥ need 才吸附底部
        _nx, ny = p._clamp_visible(300, need)
        assert ny == need, (
            '底吸附位置被钳制改动（%d → %d）—— 底部吸附会永远触发不了' % (need, ny))


@pytest.mark.parametrize('side', ['left', 'right', 'bottom'])
def test_dock_still_engages_at_edge(tmp_path, side):
    """真跑一遍 _edge_dock_check：拖到对应边缘能吸附上"""
    p = _pet(tmp_path)
    p._lost_timer.stop()
    g = _app.primaryScreen().geometry()
    w, h, ps = p.width(), p.height(), p.pet_size
    if side == 'left':
        p.move(18 - (w - ps) // 2, 300)
    elif side == 'right':
        p.move((g.right() - 18) - (w + ps) // 2, 300)
    else:
        p.move(300, (g.bottom() - 18) - ps)
    _app.processEvents()
    p.dragging = False
    p._edge_dock_check()
    _app.processEvents()
    assert p._edge_side == side, (
        '%s 边吸附没触发（_edge_side=%r）—— 钳制把吸附范围压住了' % (side, p._edge_side))


# ---------- ④ 贴边不误伤 ----------
def test_rescue_skips_docked(tmp_path):
    """贴边时窗口本来就在边缘外一点 —— 那是设计行为，不能当「丢失」拉回来

    ⚠ 2026-11-01：原先这里是**手设** p._edge_side = 'left' 再 move(-200)。
      那是假状态（真实贴边由 _enter_dock 算位置），而且动画/自检定时器会
      把窗口挪回去，测试就随机红。改成走真实 _enter_dock，并先停掉周期自检。
      —— 手设假状态这个病，我这轮已犯第四次（前三次：_edge_docked / _leave_edge / 空白帧）。
    """
    p = _pet(tmp_path)
    p._lost_timer.stop()
    p._enter_dock('left', p.y())
    _app.processEvents()
    assert p._edge_side == 'left', '前提不成立：没进入贴边'
    pos_before = (p.x(), p.y())
    assert p._rescue_if_lost('test') is False, '贴边状态被当成了「丢失」'
    assert (p.x(), p.y()) == pos_before, '贴边状态被误拉回'


# ---------- ⑤ 保存位置前钳制 ----------
def test_save_position_never_writes_offscreen(tmp_path, monkeypatch):
    p = _pet(tmp_path)
    written = {}
    monkeypatch.setattr(dp.PetWidget, '_atomic_write_json',
                        staticmethod(lambda path, data, pretty=True: written.update(data)))
    p.move(300, -900)
    _app.processEvents()
    p._save_position()
    g = _app.primaryScreen().availableGeometry()
    assert written, '什么都没写'
    assert g.top() <= written['y'] <= g.bottom(), (
        '把离屏坐标写进了配置（y=%r）—— 下次启动也会失踪' % written.get('y'))


# ---------- ⑥ 常驻托盘 + 拉回菜单 + 热键 ----------
def test_tray_exists_without_hiding_first(tmp_path, monkeypatch):
    """托盘必须常驻 —— 原来只在 hide_to_tray 里建，平时没有入口

    ⚠ 2026-11-01：离屏环境默认不建托盘（`_tray_allowed()`，见 WX-164 §五.3：
      85 处构造点 × 每实例一个 QSystemTrayIcon，全量实跑出现 No Icon set 警告）。
      这条测的是「产品在真实桌面会建」，所以用**真开关** PET_TRAY=1 打开，
      ⛔ 不手设 p.tray（那是假状态，这轮已犯四次）。
    """
    monkeypatch.setenv('PET_TRAY', '1')
    p = _pet(tmp_path)
    assert hasattr(p, 'tray') and p.tray is not None, (
        'PET_TRAY=1 时仍没建托盘 —— 窗口跑到屏幕外就彻底没有入口了（原 bug 的致命前提）')


def test_tray_off_in_offscreen(tmp_path):
    """离屏（pytest）环境默认**不建**托盘 —— 那是 85 处构造点的无谓开销"""
    p = _pet(tmp_path)
    assert p._tray_allowed() is False, '离屏环境判据错了'
    assert getattr(p, 'tray', None) is None, '离屏环境竟然建了托盘'


def test_tray_env_switch_off(tmp_path, monkeypatch):
    """PET_TRAY=0 也该关掉（调试用）"""
    monkeypatch.setenv('PET_TRAY', '0')
    p = _pet(tmp_path)
    assert p._tray_allowed() is False


def test_tray_has_rescue_action(tmp_path, monkeypatch):
    monkeypatch.setenv('PET_TRAY', '1')
    p = _pet(tmp_path)
    texts = [a.text() for a in p.tray.contextMenu().actions()]
    assert any('拉回' in t for t in texts), '托盘菜单里没有「拉回屏幕」：%r' % texts
    assert any('退出' in t for t in texts), '托盘菜单里没有退出：%r' % texts


def test_tray_icon_falls_back_when_idle_missing(tmp_path, monkeypatch):
    """构造早期 full_idle 可能还没好 —— 那时也要把托盘建起来（空图标也行）"""
    monkeypatch.setenv('PET_TRAY', '1')
    p = _pet(tmp_path)
    p.full_idle = None
    p.tray = None
    t = p._ensure_tray()
    assert t is not None, 'full_idle 缺失时托盘建不起来'


# ---------- ⑨ _restore_position 必须用同一套「落在哪块屏」判据 ----------
def test_restore_position_uses_same_screen_lookup():
    """结构钉（WX-164 §3.3）：屏外坐标的「最近屏」判据只能有一处实现

    ⚠ 312 §一 我写过 `screenAt` 在屏外返回 None，却只改了 `_clamp_visible`。
      这正是我给敏感名单加 ast 护栏要防的「写两份必然只修一份」。
      用 ast 判（不 grep 文本 —— 注释里提到 screenAt 会误判）。
    """
    import ast
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    tree = ast.parse(src)

    def _func_node(name):
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        return None

    bad = []
    for fname in ('_restore_position', '_clamp_visible'):
        fn = _func_node(fname)
        assert fn is not None, '找不到 %s' % fname
        calls_screenat = False
        for sub in ast.walk(fn):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) \
                    and sub.func.attr == 'screenAt':
                calls_screenat = True
        if calls_screenat:
            bad.append(fname)
    assert not bad, (
        '%r 仍在用 QApplication.screenAt —— 屏外坐标会取不到屏（返回 None）。'
        '应统一走 _nearest_screen（一处实现）' % bad)


def test_rescue_hotkey_registered_or_reportable(tmp_path):
    """召回热键：注册成功要能看见；失败也必须能看见（不能静默）"""
    p = _pet(tmp_path)
    assert hasattr(p, '_rescue_hotkey_ok'), '没有记录召回热键是否注册成功'


# ---------- ⑦ rescue_pet 无条件归位 ----------
def test_rescue_pet_always_recenters(tmp_path):
    p = _pet(tmp_path)
    p.move(300, -900)
    _app.processEvents()
    assert p.rescue_pet() is True
    _app.processEvents()
    assert p._visible_area() >= 0.9


def test_rescue_pet_clears_dock_first(tmp_path):
    """贴边时点「拉回屏幕」必须先解除贴边，否则 _edge_dock_check 又吸回去"""
    p = _pet(tmp_path)
    p._edge_side = 'left'
    p.rescue_pet()
    assert p._edge_side is None, '拉回后仍是贴边状态，会被再吸回去'


# ---------- ⑧ 周期自检 ----------
def test_lost_timer_exists(tmp_path):
    """自检定时器必须存在，且间隔正确

    ⚠ 2026-11-01 改：不再断言「启动时就在跑」。
      实测：25 个实例的 5 秒定时器会在全量长跑里把别的测试挪动的窗口救回来，
      导致「单跑绿、全量红」。现在离屏（测试）环境**故意**不启动，
      只在真实桌面前台启动。见 `_lost_timer_allowed()`。
    """
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p.affection = ae.AffectionEngine(str(tmp_path / 'aff.json'))
    try:
        assert hasattr(p, '_lost_timer'), '没有周期自检定时器'
        assert p._lost_timer.interval() == p.LOST_RESCUE_MS
    finally:
        p._lost_timer.stop()


def test_lost_timer_off_in_offscreen(tmp_path):
    """离屏环境（pytest）下，周期自检**不许**自动跑

    实测过的后果：它会每 5 秒把「被故意挪到屏幕外」的窗口救回来，
    干扰别的测试对窗口位置的断言。
    """
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p.affection = ae.AffectionEngine(str(tmp_path / 'aff.json'))
    try:
        assert p._lost_timer_allowed() is False, '离屏环境判据错了'
        assert not p._lost_timer.isActive(), '离屏环境竟然自动启动了自检'
    finally:
        p._lost_timer.stop()


def test_lost_timer_env_switch(tmp_path, monkeypatch):
    """环境变量 PET_LOST_TIMER=0 也应当关掉（调试/特殊场景用）"""
    monkeypatch.setenv('PET_LOST_TIMER', '0')
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p.affection = ae.AffectionEngine(str(tmp_path / 'aff.json'))
    try:
        assert p._lost_timer_allowed() is False
    finally:
        p._lost_timer.stop()


def test_manual_check_lost_still_works_in_offscreen(tmp_path):
    """定时器不自动跑，但**手动调用**必须照常工作（这是产品能力，不许为测试砍掉）"""
    p = _pet(tmp_path)
    p.move(300, -900)
    _app.processEvents()
    assert p._check_lost() is True
    _app.processEvents()
    assert p._visible_area() >= 0.5


def test_check_lost_skips_invisible(tmp_path):
    """用户主动最小化到托盘时，自检不许把他叫回来"""
    p = _pet(tmp_path)
    p.hide()
    _app.processEvents()
    assert p._check_lost() is False


def test_check_lost_skips_while_dragging(tmp_path):
    p = _pet(tmp_path)
    p.dragging = True
    p.move(300, -900)
    _app.processEvents()
    assert p._check_lost() is False, '拖拽中跟用户抢窗口会抖'
    p.dragging = False


def test_check_lost_rescues_offscreen(tmp_path):
    p = _pet(tmp_path)
    # ⚠ 必须先停掉周期定时器：它每 5 秒自己跑一次，会跟这条测试抢
    #   （实测：全量跑时定时器先把窗口救回来了，_check_lost 于是返回 False）
    #   这本身说明自检在工作 —— 但测试要测的是「单次调用」的行为。
    p._lost_timer.stop()
    p.move(300, -900)
    _app.processEvents()
    assert p._visible_area() < 0.2, '前提不成立：窗口居然还可见'
    ok = p._check_lost()
    _app.processEvents()
    assert ok is True
    assert p._visible_area() >= 0.5
