# -*- coding: utf-8 -*-
"""读屏截图 → 气泡反馈（2026-11-01，Owner 需求二）

Owner 原话：
    「原来不是有个读取程序功能吗？现在进一步给他完善一下，可以加一个选项定时截图
      或者加快捷键截图，这样的话就可以与这个用户实时进行互动还可以反馈」
    「对了我说的那个截图然后反馈是指的反馈到那个气泡上面」

本文件锁住：
  A. 结果是**气泡**，不是聊天区（Owner 明确要求）
  B. 定时截图默认关（截图是敏感能力）
  C. 画面没变就不问模型（省 token）—— 而且判据不能用「文件大小」那种笨办法
  D. 打字/拖拽中不打扰
  E. 热键可配；解析不了要**明确失败**，不能静默注册个错的
  F. 定时器幂等（重复调用不叠加）
"""
import os
import sys

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

import desktop_pet as dp  # noqa: E402
import affection_engine as ae  # noqa: E402


def _pet(tmp_path, **attrs):
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p.affection = ae.AffectionEngine(str(tmp_path / 'aff.json'))
    p._bubbles = []
    p._notices = []
    p._chats = []
    p.say_plain = lambda t, *a, **k: p._bubbles.append(t)
    p._notify = lambda t, *a, **k: p._notices.append(t)
    p._append_chat = lambda who, t: p._chats.append((who, t))
    for k, v in attrs.items():
        setattr(p, k, v)
    return p


# ---------- A. 默认值与开关 ----------
def test_defaults_off_and_bubble(tmp_path):
    p = _pet(tmp_path)
    assert p.screenshot_timer is False, '定时截图必须默认关（截图是敏感能力）'
    assert p.screenshot_feedback == 'bubble', 'Owner 要求反馈到气泡，不是聊天区'
    assert p.screenshot_interval >= 30
    assert p.screenshot_region in ('full', 'pet')
    assert p.screenshot_hotkey == 'ctrl+alt+d'


def test_structurally_initialized(tmp_path):
    """没有 config.json 时属性也必须存在（同 follow_up_mode 的坑）"""
    for name in ('screenshot_timer', 'screenshot_interval', 'screenshot_region',
                 'screenshot_hotkey', 'screenshot_feedback'):
        assert hasattr(_pet(tmp_path), name), '%s 没初始化' % name


# ---------- B. 反馈落在气泡 ----------
def test_feedback_goes_to_bubble_not_chat(tmp_path):
    p = _pet(tmp_path)
    p._on_shot_feedback('屏幕上是一个代码编辑器', trigger='hotkey')
    assert p._bubbles, '截图结果没有进气泡'
    assert '屏幕上是一个代码编辑器' in p._bubbles[-1]
    assert not p._chats, 'Owner 要气泡，不该往聊天区塞'


def test_feedback_long_text_also_leaves_trace(tmp_path):
    """气泡塞不下的长内容才补一条聊天记录（否则信息丢了）"""
    p = _pet(tmp_path)
    long_text = '很长的识别结果' * 20
    p._on_shot_feedback(long_text, trigger='timer')
    assert p._bubbles
    assert p._chats, '长内容应补一条聊天记录留痕'


def test_feedback_can_be_switched_to_chat(tmp_path):
    """老行为可切回（不破坏已有习惯）"""
    p = _pet(tmp_path, screenshot_feedback='chat')
    p._on_shot_feedback('旧行为', trigger='hotkey')
    assert p._chats and not p._bubbles


def test_feedback_marker_differs_by_trigger(tmp_path):
    p = _pet(tmp_path)
    p._on_shot_feedback('手动截的', trigger='hotkey')
    p._on_shot_feedback('定时截的', trigger='timer')
    assert p._bubbles[0].startswith('📷')
    assert p._bubbles[1].startswith('👀'), '定时和手动的气泡要能区分'


# ---------- C. 热键解析 ----------
@pytest.mark.parametrize('spec,ok', [
    ('ctrl+alt+d', True), ('ctrl+shift+s', True), ('alt+f9', True), ('win+alt+1', True),
    ('d', False), ('ctrl+alt', False), ('ctrl+alt+ab', False), ('乱写', False), ('', False),
])
def test_parse_hotkey(spec, ok):
    mods, vk = dp.PetWidget._parse_hotkey(spec)
    assert (mods is not None) is ok, '解析结果不符合预期：%r → %r' % (spec, (mods, vk))
    if ok:
        assert isinstance(vk, int) and vk > 0


def test_hotkey_requires_modifier(tmp_path):
    """单个键不接（否则会全局抢走那个键，用户按不出来）"""
    mods, vk = dp.PetWidget._parse_hotkey('f9')
    assert mods is None


def test_set_bad_hotkey_rolls_back(tmp_path):
    """写错快捷键 → 回滚到旧值，并提示失败（不静默留个错的）"""
    p = _pet(tmp_path, screenshot_hotkey='ctrl+alt+d')
    got = p._set_screenshot_hotkey('这不是快捷键')
    assert got == 'ctrl+alt+d', '非法快捷键没有回滚'
    assert any('不认识' in n or '失败' in n for n in p._notices)


# ---------- D. 定时器幂等 ----------
def test_timer_start_is_idempotent(tmp_path):
    p = _pet(tmp_path, screenshot_interval=30)
    assert p._start_screenshot_timer() is True
    first = p._shot_timer_obj
    assert p._start_screenshot_timer() is True
    assert p._shot_timer_obj is first, '重复启动创建了第二个定时器（会叠加触发）'
    p._stop_screenshot_timer()
    assert not p._shot_timer_obj.isActive()


def test_set_timer_true_starts_false_stops(tmp_path):
    p = _pet(tmp_path)
    p._set_screenshot_timer(True)
    assert p.screenshot_timer is True
    assert p._shot_timer_obj is not None and p._shot_timer_obj.isActive()
    p._set_screenshot_timer(False)
    assert p.screenshot_timer is False
    assert not p._shot_timer_obj.isActive()


def test_interval_clamped(tmp_path):
    p = _pet(tmp_path)
    assert p._set_screenshot_interval(1) == 30, '间隔下限是 30 秒'
    assert p._set_screenshot_interval(99999) == 3600


# ---------- E. 画面没变就不问模型 ----------
def test_tick_skips_when_picture_unchanged(tmp_path, monkeypatch):
    """定时触发时画面没变 ⇒ 不截、不问（省 token，也不烦人）"""
    p = _pet(tmp_path, screenshot_timer=True)
    sig = tuple([7] * 256)
    p._shot_last_sig = sig

    class _FakeImg:
        def convert(self, *a):
            return self

        def resize(self, *a):
            return self

        def getdata(self):
            return list(sig)

    class _FakeGrab:
        @staticmethod
        def grab(*a, **k):
            return _FakeImg()

    import PIL.ImageGrab as IG
    monkeypatch.setattr(IG, 'grab', _FakeGrab.grab)
    called = []
    monkeypatch.setattr(p, '_capture_screenshot', lambda *a, **k: called.append(1) or '/tmp/x.png')
    assert p._screenshot_tick() is False
    assert not called, '画面没变还是去截图问了模型'


def test_tick_captures_when_picture_changed(tmp_path, monkeypatch):
    p = _pet(tmp_path, screenshot_timer=True)
    p._shot_last_sig = tuple([1] * 256)

    class _FakeImg:
        """假图：只需支持 convert/resize/getdata/save

        2026-11-01：加了 save —— 定时截图改成「只抓一次屏」后，
        同一张图要既能算指纹又能落盘，缺 save 会走异常分支。
        """
        def convert(self, *a):
            return self

        def resize(self, *a):
            return self

        def getdata(self):
            return [2] * 256

        def save(self, path, fmt=None):
            return None

    monkeypatch.setattr('PIL.ImageGrab.grab', lambda *a, **k: _FakeImg())
    asked = []
    monkeypatch.setattr(p, '_capture_screenshot', lambda *a, **k: '/tmp/y.png')
    monkeypatch.setattr(p, '_ask_screenshot', lambda path, trigger='hotkey':
                        asked.append((path, trigger)) or True)
    assert p._screenshot_tick() is True
    assert asked and asked[0][1] == 'timer'


def test_tick_does_nothing_when_disabled(tmp_path):
    p = _pet(tmp_path, screenshot_timer=False)
    assert p._screenshot_tick() is False


def test_signature_is_content_based():
    """指纹必须来自像素，而不是「文件大小」——后者对轻微变化不敏感"""
    class _I:
        def __init__(self, v):
            self.v = v

        def convert(self, *a):
            return self

        def resize(self, *a):
            return self

        def getdata(self):
            return self.v

    a = dp.PetWidget._screenshot_signature(_I([1] * 256))
    b = dp.PetWidget._screenshot_signature(_I([2] * 256))
    assert a is not None and b is not None
    assert a != b


# ---------- F. 别打扰 ----------
def test_tick_skips_while_dragging(tmp_path):
    p = _pet(tmp_path, screenshot_timer=True, dragging=True)
    assert p._screenshot_tick() is False


def test_tick_skips_while_typing(tmp_path):
    p = _pet(tmp_path, screenshot_timer=True)
    try:
        p.chat_input.setFocus()
        _app.processEvents()
    except Exception:
        pytest.skip('无 chat_input，跳过')
    if not p.chat_input.hasFocus():
        pytest.skip('焦点拿不到（离屏环境），跳过')
    assert p._screenshot_tick() is False, '用户正在打字时不该被截图打扰'


# ---------- G. 截图路径 ----------
def test_capture_returns_none_on_failure(tmp_path, monkeypatch):
    """截图失败要返回 None（调用方据此提示），不能抛崩"""
    def boom(*a, **k):
        raise OSError('no screen')
    monkeypatch.setattr('PIL.ImageGrab.grab', boom)
    p = _pet(tmp_path)
    assert p._capture_screenshot() is None


def test_hotkey_path_uses_feedback_pipeline(tmp_path, monkeypatch):
    """热键 → 截一张 → 走一次性问答（不开整轮 agent）"""
    p = _pet(tmp_path)
    monkeypatch.setattr(p, '_capture_screenshot', lambda *a, **k: '/tmp/z.png')
    asked = []
    monkeypatch.setattr(p, '_ask_screenshot', lambda path, trigger='hotkey':
                        asked.append((path, trigger)) or True)
    assert p._on_screenshot_hotkey() is True
    assert asked == [('/tmp/z.png', 'hotkey')]


def test_hotkey_path_when_capture_fails(tmp_path, monkeypatch):
    p = _pet(tmp_path)
    monkeypatch.setattr(p, '_capture_screenshot', lambda *a, **k: None)
    assert p._on_screenshot_hotkey() is False
    assert any('截图失败' in n for n in p._notices)


# ---------- H. 设置界面 ----------
def test_settings_has_screenshot_controls():
    src = open(os.path.join(BASE, 'settings_ui.py'), encoding='utf-8').read()
    for name in ('ck_shot_timer', 'sp_shot_interval', 'cb_shot_region',
                 'cb_shot_fb', 'ed_shot_key'):
        assert name in src, '设置界面缺少控件 %s' % name
    for fn in ('_toggle_shot_timer', '_apply_shot_interval', '_apply_shot_hotkey'):
        assert fn in src, '设置界面缺少回调 %s' % fn


def test_setters_persist(tmp_path):
    p = _pet(tmp_path)
    saved = {}
    p._save_cfg_value = lambda k, v: saved.__setitem__(k, v) or True
    p._set_screenshot_region('pet')
    p._set_screenshot_feedback('chat')
    p._set_screenshot_timer(False)
    assert saved.get('screenshot_region') == 'pet'
    assert saved.get('screenshot_feedback') == 'chat'
    assert saved.get('screenshot_timer') is False
