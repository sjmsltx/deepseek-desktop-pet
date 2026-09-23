# -*- coding: utf-8 -*-
"""临时状态回收护栏（v6.79 · 缺陷 74）

使用者可见现象（2026-09-23 报）：
  · 喂食后立绘停在「亲亲」、小游戏「输」了停在沮丧图 —— 都**回不到待机**。

根因（已独立复核）：
  `pet_anim.show_state_image()` 只渲染一帧，**既不设 state、也不排收尾**；
  而收尾函数 `end_state(w, st)` 有 `w.state == st` 的前置门槛 →
  调用点只渲染不设 state 时，收尾**永远进不去** → 图挂在屏幕上不动。
  对照组：`_special_reaction` / `do_thinking` 是「设 state → 渲染 → 排收尾」三件套，所以正常。

本文件 5 条护栏：
  ① 喂食后回待机（真跑 QTimer 收尾）
  ② 小游戏「输」后回待机（专抓被「赢→play_scene」掩盖的那一支）
  ③ 饥饿是持续态：不被时间收尾清除 + 不抢更高优先级 + 饱食回升后回待机
  ④ 喂食时仍低饱食 → 收尾落回饥饿态（Owner 79 号裁定「饿了常显」）
  ⑤ 通用防线：`_show_state_image` 的每个调用点，所在方法必须同时有 `state =` 与收尾线索

运行：python -m pytest tests/test_temp_state_recovery.py -q
"""
import os
import re
import sys

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


def _wait(ms):
    """真跑事件循环 ms 毫秒 —— 让 QTimer.singleShot 的收尾**真的**触发。
    （不 mock 定时器：缺陷本身就是「收尾没被排上 / 排上了也进不去」，
     mock 掉就测不到真实行为。）"""
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


# ---------- ① 喂食回待机 ----------
def test_feed_returns_to_idle():
    p = _pet()
    p.affection.feed = lambda role: {'satiety': 80.0, 'affection': 10}
    p.affection.satiety = lambda role: 80.0
    p.state = 'idle'
    p._feed_pet()
    assert p.state == 'kiss', '喂食应立即进入 kiss 态（证明设了 state），实际 %r' % p.state
    _wait(3000)
    assert p.state == 'idle', '喂食收尾后应回待机（原先停在 kiss 不回），实际 %r' % p.state


# ---------- ② 小游戏「输」回待机 ----------
def test_game_lose_returns_to_idle():
    p = _pet()
    p.affection.trigger = lambda role, event: {}
    p.state = 'idle'
    p._on_game_result(win=False)
    assert p.state == 'defeat', '输时应进入 defeat 态，实际 %r' % p.state
    _wait(2600)
    assert p.state == 'idle', '「输」的收尾应回待机（原先永久卡在 defeat），实际 %r' % p.state


def test_game_win_celebration_ends_at_idle():
    """⚠️ **v6.79 缺陷 75 修订版**（原版是**假绿** ✗）：
    原断言写成 `state in ('scene','idle')` —— 而缺陷 75 恰好把 state 留在 'scene'，于是「通过」了 ✗。
    按微信侧 88 号补的原则改严：**必须断言最终状态 == idle**，禁用或式断言。
    """
    p = _pet()
    p.affection.trigger = lambda role, event: {}
    p.affection.satiety = lambda role: 80.0
    p.state = 'idle'
    p._on_game_result(win=True)
    assert p.state == 'scene', '赢时应进入庆祝场景态，实际 %r' % p.state
    p._end_scene()          # 推进 6 秒收尾（等价于 timer 到点），不真等 6 秒
    assert p.state == 'idle', \
        '庆祝收尾后必须回待机（缺陷 75：原先永久卡在 scene），实际 %r' % p.state


def test_scene_key_with_asset_but_unregistered_recovers(monkeypatch):
    """缺陷 75 本体：`happy` 有素材（flash_happy.png 存在）但未登记在 SCENE_ACTIONS →
    原先 KeyError → 收尾永远排不上 → 卡住。现必须：不抛异常 + 能收尾回待机 + 写审计 warning。"""
    import governance as gov
    p = _pet()
    captured = []
    monkeypatch.setattr(gov, 'log_event', lambda *a, **k: captured.append((a, k)))
    p.state = 'idle'
    p.play_scene('happy')          # ① 不得抛异常
    assert p.state == 'scene', '未登记键也应进入场景态后正常收尾，实际 %r' % p.state
    p._end_scene()                 # ② 收尾必须能回待机
    assert p.state == 'idle', '未登记键也必须能收尾回待机，实际 %r' % p.state
    # ③ 审计 warning 必须落（未知键 = 代码与数据不同步的信号，不能静默）
    assert any('happy' in str(x) for x in captured), '未登记键应写审计 warning，实际 %r' % captured


def test_arbitrary_unknown_scene_key_recovers(monkeypatch):
    """⭐ 缺陷 75 比“只有 happy”更广：`asset()` 对**任何**键都会兜底到 `{role}_idle.png` ✓
    → `_get_scene_img` 几乎不会返回 None ✗ → **任何未登记键**原先都会走到 KeyError → 卡住 ✗。
    本测试用一个人为的键名字验证：不抛异常 + 能收尾回待机 + 写审计 warning。"""
    import governance as gov
    p = _pet()
    captured = []
    monkeypatch.setattr(gov, 'log_event', lambda *a, **k: captured.append((a, k)))
    p.state = 'idle'
    p.play_scene('这个键不存在')          # ① 不得抛异常
    assert p.state == 'scene', '应进入场景态，实际 %r' % p.state
    p._end_scene()                       # ② 收尾必须能回待机
    assert p.state == 'idle', '未登记键必须能收尾回待机，实际 %r' % p.state
    # ③ 审计 warning
    assert any('这个键不存在' in str(x) for x in captured), \
        '未登记键应写审计 warning，实际 %r' % captured


# ---------- ③ 饥饿是持续态 ----------
def test_hungry_is_persistent_and_respects_priority():
    p = _pet()
    p.affection.satiety = lambda role: 10.0
    p.state = 'idle'
    p._check_satiety()
    assert p.state == 'hungry', '低饱食应从待机进入饥饿态，实际 %r' % p.state

    _wait(2600)   # 超过 kiss/victory 那类一次性收尾的时长
    assert p.state == 'hungry', '饥饿是持续状态，不得被时间收尾清除，实际 %r' % p.state

    p.state = 'scared'   # 更高优先级（睡眠 > scared > 情绪 > 小游戏 > hungry > 待机）
    p._check_satiety()
    assert p.state == 'scared', 'hungry 不得抢 scared，实际 %r' % p.state

    p.state = 'victory'  # 小游戏优先级也高于 hungry
    p._check_satiety()
    assert p.state == 'victory', 'hungry 不得抢 victory，实际 %r' % p.state

    p.state = 'hungry'
    p.affection.satiety = lambda role: 80.0   # 饱食回升 → 退出饥饿态
    p._check_satiety()
    assert p.state == 'idle', '饱食回升后应回待机，实际 %r' % p.state


# ---------- ④ 喂食收尾重判饱食度 ----------
def test_feed_reaction_falls_back_to_hungry_when_still_low():
    p = _pet()
    p.state = 'kiss'
    p._end_feed_reaction(10.0)
    assert p.state == 'hungry', '喂食后仍低饱食 → 应回到饥饿态，实际 %r' % p.state


def test_feed_reaction_goes_idle_when_full():
    p = _pet()
    p.state = 'kiss'
    p._end_feed_reaction(80.0)
    assert p.state == 'idle', '喂食后饱食达标 → 应回待机，实际 %r' % p.state


# ---------- ④b 收尾落点统一：仍饿则回饥饿（Owner 14:53 追加裁定） ----------
def test_emotion_restore_falls_back_to_hungry():
    """饥饿期间被情绪接管，情绪收尾后仍回饥饿状态（而不是回待机）"""
    p = _pet()
    p.affection.satiety = lambda role: 10.0
    p.state = 'happy'
    p._restore_state_after_emotion()
    assert p.state == 'hungry', '情绪收尾后仍饿 → 应回饥饿态，实际 %r' % p.state

    p.affection.satiety = lambda role: 80.0
    p.state = 'happy'
    p._restore_state_after_emotion()
    assert p.state == 'idle', '情绪收尾后不饿 → 应回待机，实际 %r' % p.state


def test_scene_end_falls_back_to_hungry():
    p = _pet()
    p.affection.satiety = lambda role: 10.0
    p.state = 'scene'
    p._end_scene()
    assert p.state == 'hungry', '场景收尾后仍饿 → 应回饥饿态，实际 %r' % p.state


def test_special_reaction_end_falls_back_to_hungry():
    """惊吓/开心（_special_reaction）收尾走 _end_state，同样按优先级落回饥饿"""
    p = _pet()
    p.affection.satiety = lambda role: 10.0
    p.state = 'scared'
    p._end_state('scared')
    assert p.state == 'hungry', '惊吓收尾后仍饿 → 应回饥饿态，实际 %r' % p.state

    # 对照：状态不匹配时 _end_state 必须空转（不得抢后来接管的状态）
    p.state = 'scene'
    p._end_state('scared')
    assert p.state == 'scene', '_end_state 不应抢走已接管的状态，实际 %r' % p.state


# ---------- ⑤ 通用防线（源码级） ----------
# 白名单：这些方法**故意**不排时间收尾，理由写在下面（不是漏配）
_WHITELIST = {
    # 饥饿 = 持续状态，退出条件是「饱食度回升 ≥30」而非时间；
    # 收尾落在 _check_satiety() 的 `elif self.state == 'hungry': self._end_state('hungry')`
    '_enter_hungry': "_end_state('hungry')",
}


def _methods(src):
    """枚举类方法区间 (name, start, end)（4 空格缩进的 def）"""
    lines = src.split('\n')
    out, cur = [], None
    for i, ln in enumerate(lines):
        if re.match(r'    def \w+', ln):
            if cur:
                out.append((cur[0], cur[1], i))
            cur = (ln.strip()[4:].split('(')[0], i)
    if cur:
        out.append((cur[0], cur[1], len(lines)))
    return out, lines


def _enclosing(mets, i):
    for name, a, b in mets:
        if a <= i < b:
            return name, a, b
    return None, i, i


def test_every_state_image_call_is_paired():
    """护栏⑤：`_show_state_image(` 的每个调用点，所在方法必须同时出现
    ① `self.state =`（否则 end_state 的 state==st 门槛进不去）
    ② 收尾线索（`_end_state(` / `singleShot(` / `QTimer(` / `_emotion_restore_timer`）
    谁不配收尾就红 —— 以后新增调用点会当场失败。"""
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    mets, lines = _methods(src)
    end_clues = ('_end_state(', 'singleShot(', 'QTimer(', '_emotion_restore_timer')
    offenders = []
    checked = 0
    for i, ln in enumerate(lines):
        if '_show_state_image(' not in ln or 'def _show_state_image' in ln:
            continue
        name, a, b = _enclosing(mets, i)
        if name is None:
            continue
        checked += 1
        body = '\n'.join(lines[a:b])
        has_state = bool(re.search(r'self\.state\s*=', body))
        has_end = any(c in body for c in end_clues)
        if name in _WHITELIST:
            # 白名单方法：必须能全仓找到它约定的那处收尾（防止白名单变成"免死金牌"）
            assert _WHITELIST[name] in src, \
                '白名单方法 %s 约定的收尾 %r 在源码中找不到' % (name, _WHITELIST[name])
            continue
        if not (has_state and has_end):
            offenders.append('%s(L%d) state=%s end=%s' % (name, i + 1, has_state, has_end))
    assert checked >= 5, '扫描到的调用点太少（%d），护栏可能失效' % checked
    assert not offenders, '这些 _show_state_image 调用点缺 state 或缺收尾：\n  ' + '\n  '.join(offenders)


# ---------- ⑥ pet_anim 收尾原语不得再变孤儿（微信侧 09 号建议） ----------
def test_pet_anim_end_primitives_still_wired():
    """pet_anim 的三个收尾原语必须仍被 desktop_pet 的 wrapper 调用 ——
    防止「收尾逻辑搬家」后它们再次变成 0 调用点的死代码（v6.79 C 方案）。"""
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    for name in ('anim.end_state(', 'anim.end_scene(', 'anim.restore_after_emotion('):
        assert name in src, 'pet_anim 收尾原语已变孤儿（无调用点）：%s' % name
    for wrapper in ('def _end_state(', 'def _end_scene(', 'def _restore_state_after_emotion(',
                    'def _rest_idle_or_hungry('):
        assert wrapper in src, '缺少收尾 wrapper / 落点方法：%s' % wrapper


# ---------- ⑦ 回待机类断言禁用或式（微信侧 88 号补的原则） ----------
def test_no_or_style_state_assertions():
    """护栏：'回待机 / 收尾'类断言**禁止或式**（`state in (a, b)`）——
    或式断言天然能假绿：缺陷 75 就是这么漏过去的（KeyError 恰好把 state 留在 'scene' → 断言"通过"）。
    正确写法：「推进 timer 后，最终状态 == idle」。"""
    bad = []
    tests_dir = os.path.join(BASE, 'tests')
    for fn in sorted(os.listdir(tests_dir)):
        if not (fn.startswith('test_') and fn.endswith('.py')):
            continue
        src = open(os.path.join(tests_dir, fn), encoding='utf-8').read()
        # ⚠️ 先剔掉文档字符串与注释行 —— 否则护栏会扫到“举例说明”里的例句本身（自己报自己 ✗）
        src = re.sub(r'"""[\s\S]*?"""', '', src)
        src = re.sub(r"'''[\s\S]*?'''", '', src)
        src = '\n'.join(ln for ln in src.split('\n') if not ln.strip().startswith('#'))
        for m in re.finditer(r"state\s+in\s*\(([^)]*)\)", src):
            if "'idle'" in m.group(1) or '"idle"' in m.group(1):
                bad.append('%s → %s' % (fn, m.group(0).strip()))
    assert not bad, '回待机类断言不得用或式（天然假绿）：\n  ' + '\n  '.join(bad)
