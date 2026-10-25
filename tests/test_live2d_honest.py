# -*- coding: utf-8 -*-
"""Live2D 开关必须说实话（2026-10-25）

背景
----
`config.json` 里 `display_mode` 可以是 `live2d`，但便携版根本跑不了 Live2D：
`_internal/live2d/v3/` 只有 `_v3cpp.pyd`，缺 `__init__.py` / `lapp_model.py`，
也没有 pyopengl。Python 把无 `__init__.py` 的目录当 namespace package ⇒
`import live2d.v3` **成功**，`init()` 才炸。

原来的问题是**启动路径静默**：建不出来就只把 `display_mode` 改成 `static`，
不通知、不记录。用户上次明明选了 Live2D，之后每次启动都是静态图，无从知道为什么
—— 与「语音在线失败静默换声线」同一类无声降级。

这组测试锁的是三件事：
  1 失败原因要**分得清**（缺模型 / 没装依赖 / 包不完整 / init 失败）
  2 启动降级要**说出来**，不能悄悄改
  3 切换失败时**不许写配置**（否则配置文件与实际状态不符）

⛔ 用桩对象测 PetWidget 的方法，不建 QWidget —— 不依赖 GPU、不碰真实配置。
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import desktop_pet  # noqa: E402

PW = desktop_pet.PetWidget


class _Stack:
    def __init__(self):
        self.added = []
        self.current = None

    def addWidget(self, w):
        self.added.append(w)

    def setCurrentWidget(self, w):
        self.current = w


class _Bubble:
    def __init__(self):
        self.raised = 0

    def raise_(self):
        self.raised += 1


class _Base:
    language = 'zh'
    display_mode = 'static'
    _l2d_fail_msg = ''

    def __init__(self):
        self.pet_stack = _Stack()
        self.bubble = _Bubble()
        self.msgs = []
        self.saved = []

    def _notify(self, msg, *a, **k):
        self.msgs.append(msg)

    def _save_cfg_value(self, k, v):
        self.saved.append((k, v))
        return True


# ---------------- 1. 原因要分得清 ----------------

class _NoModel(_Base):
    _l2d_unavailable_reason = PW._l2d_unavailable_reason
    _create_l2d_embedded = PW._create_l2d_embedded

    def _live2d_model_path(self):
        return None


def test_reason_missing_model_is_specific():
    """模型文件缺失要单独说出来，不能混成'缺少 live2d-py'"""
    r = _NoModel()._l2d_unavailable_reason()
    assert '模型文件不存在' in r, '原因不具体：%r' % r


def test_create_embedded_records_reason():
    """_create_l2d_embedded 失败时必须把原因留下（原先三处 except 全吞）"""
    w = _NoModel()
    assert w._create_l2d_embedded() is None
    assert '模型文件不存在' in w._l2d_fail_msg, \
        '失败原因没记录：%r' % w._l2d_fail_msg


class _BrokenPkg(_Base):
    """模拟便携版：模型在、但 live2d 包不完整（有 _v3cpp 却无 __init__）"""
    _l2d_unavailable_reason = PW._l2d_unavailable_reason

    def _live2d_model_path(self):
        return os.path.join(ROOT, 'assets', 'live2d', 'mao', 'Mao.model3.json')


def test_reason_detects_incomplete_package(monkeypatch):
    """包不完整 ≠ 没装依赖 —— 两者给用户的动作完全不同

    这条直接伪造一个「只有 _v3cpp、没有 __init__」的包：
    namespace package 让 `import live2d.v3` 成功，但 `init` / `LAppModel` 不存在。
    这正是便携版里发生的事，不能靠 skip 绕过。
    """
    import types
    if not os.path.exists(_BrokenPkg()._live2d_model_path()):
        pytest.skip('模型文件不在，这条前提不成立')

    fake_v3 = types.ModuleType('live2d.v3')      # 故意不提供 init / LAppModel
    fake_pkg = types.ModuleType('live2d')
    fake_pkg.v3 = fake_v3
    monkeypatch.setitem(sys.modules, 'live2d', fake_pkg)
    monkeypatch.setitem(sys.modules, 'live2d.v3', fake_v3)

    r = _BrokenPkg()._l2d_unavailable_reason()
    assert '不完整' in r, '残缺包没被识别出来：%r' % r
    assert '未安装' not in r, '把"包残缺"误报成"没安装"：%r' % r


# ---------------- 2. 切换失败不许写配置 ----------------

class _SwitchFail(_Base):
    _set_display_mode = PW._set_display_mode

    def _create_l2d_embedded(self):
        return None


def test_switch_to_live2d_reports_specific_reason():
    w = _SwitchFail()
    w._l2d_fail_msg = '便携版不含 Live2D 运行时（需从源码运行并安装 live2d-py + pyopengl）'
    w._set_display_mode('live2d')
    assert w.display_mode == 'static', '切换失败却把模式写成 live2d'
    assert w.saved == [], '切换失败仍写了配置：%r' % (w.saved,)
    assert w.msgs, '切换失败没有提示'
    assert '便携版不含' in w.msgs[0], '提示没给出具体原因：%r' % w.msgs[0]


# ---------------- 3. 启动降级必须说出来 ----------------

class _Boot(_Base):
    _apply_display_mode = PW._apply_display_mode

    def __init__(self, ok, mode='live2d', why='live2d 包不完整（缺 __init__.py）'):
        super().__init__()
        self.display_mode = mode
        self._ok = ok
        self._why = why

    def _create_l2d_embedded(self):
        if self._ok:
            self._l2d_fail_msg = ''
            return object()
        self._l2d_fail_msg = self._why
        return None


def test_startup_live2d_fallback_is_not_silent():
    """config 是 live2d 但建不出来 —— 必须告知，不许悄悄退回静态"""
    w = _Boot(False)
    w._apply_display_mode()
    assert w.display_mode == 'static'
    assert w.msgs, '启动降级完全没提示（这就是本轮修的缺陷）'
    assert 'live2d 包不完整' in w.msgs[0], \
        '提示没带具体原因：%r' % w.msgs[0]


def test_startup_live2d_success_enters_mode():
    w = _Boot(True)
    w._apply_display_mode()
    assert w.display_mode == 'live2d'
    assert w.pet_stack.added, '建出来了却没加进 stack'
    assert w.pet_stack.current is w._l2d_widget
    assert w.msgs == [], '成功时不该弹提示'


def test_startup_static_mode_is_noop():
    w = _Boot(True, mode='static')
    w._apply_display_mode()
    assert w.pet_stack.added == []
    assert w.msgs == []
    assert w.display_mode == 'static'


# ---------------- 4. 换模型失败也不许报成功 ----------------

class _SwitchModel(_Base):
    """换模型时：模型列表里有它，但建不出来"""
    _set_live2d_model = PW._set_live2d_model

    def __init__(self):
        super().__init__()
        self.display_mode = 'live2d'
        self.language = 'zh'
        self.live2d_model = 'mao'
        self.pet_label = object()
        self._l2d_widget = None
        self._l2d_fail_msg = 'live2d 包不完整（缺 __init__.py / lapp_model.py）'

    def _scan_live2d_models(self):
        return ['mao', 'other']

    def _create_l2d_embedded(self):
        return None


def test_switch_model_failure_does_not_claim_success():
    """第三条路径：换模型建不出来时，不许说「已切换」

    原先行为：先销毁旧部件 → 建不出来 → 仍 `_notify('已切换 Live2D 模型：xxx')`
    ⇒ 画面悄悄回到静态、display_mode 还写着 live2d、用户被告知成功。
    """
    w = _SwitchModel()
    w._set_live2d_model('other')
    joined = ' | '.join(w.msgs)
    assert '已切换 Live2D 模型' not in joined, \
        '换模型失败却报了成功：%r' % w.msgs
    assert w.display_mode == 'static', '失败后 display_mode 仍是 %r' % w.display_mode
    assert ('display_mode', 'static') in w.saved, '没把配置改回 static：%r' % (w.saved,)
    assert 'live2d 包不完整' in joined, '没说明具体原因：%r' % joined


def test_switch_model_success_still_reports():
    """正常换模型仍要报「已切换」（别把正常路径改坏）"""
    class _Ok(_SwitchModel):
        def _create_l2d_embedded(self):
            return object()

    w = _Ok()
    w._set_live2d_model('other')
    assert '已切换 Live2D 模型' in ' | '.join(w.msgs)
    assert w.display_mode == 'live2d'

# ---------------- 5. 降级必须落配置，否则热加载会把它翻回去 ----------------

def test_startup_fallback_persists_to_config():
    """降级后必须把 display_mode 写回 config —— 否则第 4 条静默路径

    2026-10-25 第四条路径（微信侧 WX-119 §3.5 报；本条锁它）：

      _apply_display_mode 降级时只改内存 `self.display_mode = 'static'`，
      **不写 config**（函数体内 _save_cfg_value 出现 0 次）。
      而 _load_ai_config 每次都无条件
          self.display_mode = cfg.get('display_mode', 'static')
      并且它有 8 个调用点，含 `ask_ai` —— **每次聊天前都跑一次**。

    ⇒ 便携版（Live2D 包不完整）上的真实时间线：
        启动 → 老实降级 + 警告一次（第 1 条修的就是这个）
        用户说第一句话 → _load_ai_config 把 display_mode 从 config 读回 'live2d'
        从此 display_mode 恒为 'live2d'，而模型根本没有

    ⇒ 后果不是「状态不一致」而是**画面没了**：
        _show_idle   L5460  if display_mode == 'live2d': return   → 待机立绘不画
        _show_peek   L5505  if display_mode == 'live2d': return   → 扒边立绘不画
        pet_anim      L87   if display_mode == 'live2d': return   → 状态动画不播

    ⛔ 判据必须能证伪：
        只断言 `display_mode == 'static'` 是**测不出**这个 bug 的 ——
        内存里本来就是 static（降级那一刻改的）。必须断言**配置被改写**，
        再模拟下一次 _load_ai_config 的读取口径，看它会不会翻回去。
    """
    w = _Boot(False)
    w._apply_display_mode()
    assert w.display_mode == 'static', '降级后内存值应在 static'
    assert ('display_mode', 'static') in w.saved, (
        '降级没写回配置 —— 下一次 _load_ai_config 会把它翻回 live2d：saved=%r'
        % (w.saved,))

    # 跨路径：按下一次 _load_ai_config 的口径重算一遍（cfg.get('display_mode')）
    cfg_value = 'live2d'          # 用户原本选的
    for k, v in w.saved:
        if k == 'display_mode':
            cfg_value = v
    assert cfg_value == 'static', (
        '热加载会把 display_mode 翻回 %r —— 降级只活到用户说的第一句话' % cfg_value)
