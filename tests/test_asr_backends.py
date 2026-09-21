# -*- coding: utf-8 -*-
"""ASR 可插拔后端（v6.77）

使用者："先做 C 应急（Win+H）+ 顺带把 A(whisper) 和 D(联网接口) 的插口留好"。
本测试锁：后端分发、未配置时的可操作提示、配置能写到引擎上、录音器接口存在。
（trigger_win_h 有系统副作用 → 不在测试里真按；只验证分发到它。）
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


@pytest.fixture(scope='module')
def eng():
    import asr
    return asr.AsrEngine(BASE)


def test_default_backend_is_auto(eng):
    assert eng.backend() == 'auto'
    assert hasattr(eng, '_listen_local')


@pytest.mark.parametrize('backend,attr', [
    ('winh', 'trigger_win_h'), ('whisper', '_listen_whisper'), ('http', '_listen_http'),
])
def test_backends_exist(eng, backend, attr):
    assert hasattr(eng, attr)


def test_whisper_without_config_gives_actionable_hint(eng):
    eng.backend_name = 'whisper'
    t, _c, err = eng.listen()
    assert t == '' and 'whisper' in err and 'whisper.cpp' in err
    eng.backend_name = 'auto'


def test_http_without_config_gives_actionable_hint(eng):
    eng.backend_name = 'http'
    t, _c, err = eng.listen()
    assert t == '' and '接口' in err
    eng.backend_name = 'auto'


def test_whisper_missing_model_message(eng, tmp_path):
    exe = tmp_path / 'main.exe'
    exe.write_bytes(b'x')
    eng.backend_name = 'whisper'
    eng.whisper_exe = str(exe)
    eng.whisper_model = ''
    t, _c, err = eng.listen()
    assert '模型' in err
    eng.backend_name = 'auto'


def test_recorder_interface_present(eng):
    assert callable(getattr(eng, 'record_wav', None))


# ---------- 可配置热键（v6.77）----------

@pytest.mark.parametrize('spec,expect_mods,expect_key', [
    ('win+h', [0x5B], 0x48),
    ('Win+H', [0x5B], 0x48),                 # 大小写不敏感
    ('', [0x5B], 0x48),                       # 空 → 默认
    ('乱填的', [0x5B], 0x48),                    # 解析不了 → 回落默认
    ('ctrl+shift+space', [0x11, 0x10], 0x20),
    ('win+alt+h', [0x5B, 0x12], 0x48),
    ('ctrl+f5', [0x11], 0x74),
    ('ctrl+shift+f12', [0x11, 0x10], 0x7B),
    ('alt+enter', [0x12], 0x0D),
    ('ctrl+1', [0x11], 0x31),
])
def test_parse_hotkey(eng, spec, expect_mods, expect_key):
    mods, key = eng.parse_hotkey(spec)
    assert mods == expect_mods and key == expect_key, (spec, mods, key)


def test_trigger_uses_configured_hotkey(eng):
    """trigger_win_h 要按配置发键（测试注入替身，不真按 —— 避免扰动使用者桌面）"""
    sent = []
    eng._key_sender = lambda mods, key: sent.append((list(mods), key))
    eng.winh_hotkey = 'ctrl+shift+space'
    _t, _c, err = eng.trigger_win_h()
    assert sent == [([0x11, 0x10], 0x20)], sent
    assert 'ctrl+shift+space' in err, '提示里应该把实际用的热键写出来'
    eng.winh_hotkey = 'win+h'
    eng._key_sender = None


def test_host_set_backend_writes_config():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    assert app is not None
    import desktop_pet as dp
    p = dp.PetWidget()
    saved = {}
    p._save_cfg_value = lambda k, v: saved.__setitem__(k, v)
    p._notify = lambda *a, **k: None
    val = p._set_asr_backend('winh')
    assert val == 'winh' and saved.get('asr_backend') == 'winh'
    assert p.asr.backend_name == 'winh'
    assert p._set_asr_backend('乱填') == 'auto', '非法值要回落到 auto'


def test_host_set_extra_propagates():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    import desktop_pet as dp
    p = dp.PetWidget()
    saved = {}
    p._save_cfg_value = lambda k, v: saved.__setitem__(k, v)
    p._set_asr_extra(whisper_exe='H:\\w\\main.exe', asr_http_url='https://x/asr')
    assert saved.get('asr_whisper_exe') == 'H:\\w\\main.exe'
    assert p.asr.whisper_exe == 'H:\\w\\main.exe'
    assert p.asr.asr_http_url == 'https://x/asr'
