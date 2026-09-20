# -*- coding: utf-8 -*-
"""平台抽象层（P1 批次 1）测试。

三件事：① 能力报告如实；② 已收编项**真的转发**到既有实现（不是另写一套）；
③ 非 Windows / 宿主未绑定时**降级不抛异常**，且导入期不碰平台专有模块。
"""
import os
import subprocess
import sys
import textwrap

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import platform_layer as pl  # noqa: E402

KEYS = {'open_path', 'open_url', 'clipboard', 'foreground', 'ocr', 'tts', 'asr',
        'hotkey', 'autostart', 'window_effects', 'beep', 'lock_screen', 'dpi_awareness'}



# ---------------------------------------------------------------- 能力报告

def test_capabilities_shape():
    caps = pl.capabilities()
    assert set(caps) == KEYS, f'能力清单变了：{set(caps) ^ KEYS}'
    for key, info in caps.items():
        assert set(info) == {'ok', 'via', 'note'}, key
        assert info['via'] in ('module', 'host', 'unavailable')
        if not info['ok']:
            assert info['via'] == 'unavailable', f'{key} 不 ok 时 via 必须是 unavailable'


def test_windows_capabilities_expected():
    if not pl.is_windows():
        pytest.skip('只在 Windows 上断言实现存在')
    caps = pl.capabilities()
    for key in ('open_path', 'open_url', 'clipboard', 'foreground', 'ocr', 'tts', 'asr',
                'hotkey', 'beep', 'lock_screen', 'dpi_awareness'):
        assert caps[key]['ok'], f'{key} 在本机应可用：{caps[key]}'
        assert caps[key]['via'] == 'module'
    # 尚未收编的两项：宿主没绑定前必须**如实报不可用**（不假装支持）
    assert caps['autostart']['ok'] is True and caps['autostart']['via'] == 'module'
    assert caps['window_effects']['ok'] is True and caps['window_effects']['via'] == 'module'


def test_report_lists_everything():
    r = pl.report()
    assert '平台抽象层' in r and pl.platform_name() in r
    for key in KEYS:
        assert key in r, f'报告里少了 {key}'


# ---------------------------------------------------------------- 宿主绑定

# ---------------------------------------------------------------- 真的转发了吗

def test_open_path_delegates(monkeypatch):
    seen = []
    import pet_sysutils
    monkeypatch.setattr(pet_sysutils, 'open_shell_target', lambda t: seen.append(t))
    assert pl.open_path(123) is True
    assert seen == ['123'], '必须把参数转成字符串后交给 pet_sysutils'


def test_open_url_and_search_delegate(monkeypatch):
    seen = []
    import pet_sysutils
    monkeypatch.setattr(pet_sysutils, 'open_url', lambda u: seen.append(('url', u)))
    monkeypatch.setattr(pet_sysutils, 'open_search_url', lambda q, e='x': seen.append(('q', q, e)))
    assert pl.open_url('http://a') is True
    assert pl.open_search('龙虾') is True
    assert pl.open_search('龙虾', 'https://example.com/?q=') is True
    assert seen[0] == ('url', 'http://a')
    assert seen[1][0] == 'q' and seen[2][2] == 'https://example.com/?q='


def test_clipboard_delegates(monkeypatch):
    import pet_sysutils
    monkeypatch.setattr(pet_sysutils, 'read_clipboard_text', lambda: '内容')
    got = []
    monkeypatch.setattr(pet_sysutils, 'write_clipboard_text', lambda t: got.append(t))
    assert pl.clipboard_get() == '内容'
    assert pl.clipboard_set('新') is True and got == ['新']


def test_foreground_delegates(monkeypatch):
    import pet_foreground
    monkeypatch.setattr(pet_foreground, 'foreground_process_name', lambda: 'code.exe')
    monkeypatch.setattr(pet_foreground, 'busy_hint', lambda p=None: '用户在开会' if p is None else 'p=%s' % p)
    assert pl.foreground_process() == 'code.exe'
    assert pl.busy_hint() == '用户在开会'
    assert pl.busy_hint('zoom.exe') == 'p=zoom.exe'


def test_ocr_delegates(monkeypatch):
    import pet_docs
    seen = []
    monkeypatch.setattr(pet_docs, 'ocr_image', lambda path, ps1: seen.append((path, ps1)) or '识别结果')
    assert pl.ocr_image('a.png', 'ocr_helper.ps1') == '识别结果'
    assert seen == [('a.png', 'ocr_helper.ps1')]


class _FakeVoice:
    def __init__(self):
        self.spoken = []

    def speak(self, text, now=None, force=False):
        self.spoken.append((text, force))
        return True, ''

    def stop(self):
        self.spoken.append('stop')


def test_speak_delegates_to_voice_io():
    v = _FakeVoice()
    ok, msg = pl.speak(v, '你好', force=True)
    assert ok is True and v.spoken == [('你好', True)]
    assert pl.stop_speech(v) is True and v.spoken[-1] == 'stop'
    ok2, msg2 = pl.speak(None, '你好')
    assert ok2 is False and '语音实例' in msg2


def test_hotkey_filter_delegates(monkeypatch):
    import pet_sysutils
    monkeypatch.setattr(pet_sysutils, 'hotkey_filter_factory', lambda cb: ('filter', cb))
    got = pl.hotkey_filter({1: 'cb'})
    assert got == ('filter', {1: 'cb'})


def test_register_hotkey_uses_user32(monkeypatch):
    calls = []

    class _User32:
        @staticmethod
        def RegisterHotKey(hwnd, hid, mods, vk):
            calls.append(('reg', hid, mods, vk))
            return 1

        @staticmethod
        def UnregisterHotKey(hwnd, hid):
            calls.append(('unreg', hid))
            return 1

    class _Windll:
        user32 = _User32()

    class _FakeCtypes:
        windll = _Windll()

    monkeypatch.setattr(pl, 'ctypes', _FakeCtypes)
    assert pl.register_hotkey(1, pl.MOD_CONTROL | pl.MOD_ALT, 0x50) is True
    assert pl.unregister_hotkey(1) is True
    assert calls == [('reg', 1, 3, 0x50), ('unreg', 1)]   # MOD_ALT=1 | MOD_CONTROL=2 = 3


def test_beep_returns_bool():
    assert pl.beep('ok') in (True, False)


# ---------------------------------------------------------------- 降级：非 Windows

@pytest.fixture
def _as_linux(monkeypatch):
    monkeypatch.setattr(pl, 'platform_name', lambda: 'linux')
    monkeypatch.setattr(pl, 'is_windows', lambda: False)


def test_non_windows_degrades_without_exception(_as_linux):
    assert pl.open_path('x') is False
    assert pl.open_url('http://a') is False
    assert pl.open_search('q') is False
    assert pl.clipboard_get() == ''
    assert pl.clipboard_set('x') is False
    assert pl.ocr_image('a.png') == ''
    assert pl.beep('ok') is False
    assert pl.hotkey_filter({}) is None
    assert pl.register_hotkey(1, 0, 0) is False
    assert pl.unregister_hotkey(1) is False
    caps = pl.capabilities()
    for key in ('open_path', 'open_url', 'clipboard', 'hotkey', 'beep', 'autostart', 'window_effects'):
        assert caps[key]['ok'] is False and caps[key]['via'] == 'unavailable'


# ---------------------------------------------------------------- 导入期契约

def test_import_does_not_pull_platform_specific_modules():
    """导入本模块、**并调用 capabilities()**，都不得**新增** winreg/winsound/PySide6

    注意：只看增量 —— 本机解释器在 site 阶段就导入了 winreg，用绝对值会误判。
    （capabilities() 用 find_spec 只查不执行 —— 否则 pet_sysutils 一被 import
     就会把它顶层的 winreg 拉进来，跨平台前提就没了）
    """
    code = textwrap.dedent('''
        import sys
        base = set(sys.modules)          # 环境自带可能已经导入 winreg（本机 site 阶段就会），
                                         # 所以只能看**增量**——模块自己拉进来了什么
        import platform_layer
        after_import = [m for m in ('winreg', 'winsound', 'PySide6')
                        if m in sys.modules and m not in base]
        caps = platform_layer.capabilities()
        after_probe = [m for m in ('winreg', 'winsound', 'PySide6')
                       if m in sys.modules and m not in base]
        print('BAD_IMPORT:' + ','.join(after_import))
        print('BAD_PROBE:' + ','.join(after_probe))
        print('KEYS:%d' % len(caps))
    ''')
    env = dict(os.environ)
    env['QT_QPA_PLATFORM'] = 'offscreen'
    out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                         cwd=BASE, timeout=120, env=env)
    assert out.returncode == 0, out.stderr[-800:]
    lines = dict(l.split(':', 1) for l in out.stdout.strip().splitlines() if ':' in l)
    assert lines.get('BAD_IMPORT', '?') == '', f'导入期不该拉进：{lines.get("BAD_IMPORT")}'
    assert lines.get('BAD_PROBE', '?') == '', f'capabilities() 不该拉进：{lines.get("BAD_PROBE")}'
    assert lines.get('KEYS') == '13', out.stdout


# ---------------------------------------------------------------- 开机自启（批次 2）

def test_autostart_enable_disable(tmp_path, monkeypatch):
    """开启→存在、关闭→消失；且**两向都能生效**（旧实现只会关，见 v6.72 修真）"""
    d = str(tmp_path)
    made = []

    def fake_create(path, target, workdir):
        made.append((path, target, workdir))
        open(path, 'w', encoding='utf-8').write('lnk')
        return True

    monkeypatch.setattr(pl, 'create_autostart_lnk', fake_create)
    monkeypatch.setattr(pl, '_cleanup_legacy', lambda sd=None: [])

    assert pl.autostart_enabled(d) is False
    ok, msg = pl.autostart_set(True, d)
    assert ok and pl.autostart_enabled(d) is True, msg
    assert made and made[0][0].endswith(pl.AUTOSTART_LNK_NAME)

    ok2, msg2 = pl.autostart_set(False, d)
    assert ok2 and pl.autostart_enabled(d) is False, msg2
    # 再开一次也能开（防止"只能关"回归）
    assert pl.autostart_set(True, d)[0] and pl.autostart_enabled(d) is True


def test_autostart_toggle_reports_new_state(tmp_path, monkeypatch):
    d = str(tmp_path)
    monkeypatch.setattr(pl, 'create_autostart_lnk',
                        lambda p, t, w: (open(p, 'w').write('x'), True)[1])
    monkeypatch.setattr(pl, '_cleanup_legacy', lambda sd=None: [])
    on1, ok1, _ = pl.autostart_toggle(d)
    on2, ok2, _ = pl.autostart_toggle(d)
    assert (on1, ok1, on2, ok2) == (True, True, False, True)


def test_autostart_disable_when_already_off(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, '_cleanup_legacy', lambda sd=None: [])
    ok, msg = pl.autostart_disable(str(tmp_path))
    assert ok and '本来' in msg


def test_autostart_cleans_legacy_items(tmp_path, monkeypatch):
    """开启/关闭都要清掉旧版 .bat/.cmd（防开机双启动）"""
    d = str(tmp_path)
    for old in pl.AUTOSTART_LEGACY:
        open(os.path.join(d, old), 'w', encoding='utf-8').write('old')
    monkeypatch.setattr(pl, 'create_autostart_lnk',
                        lambda p, t, w: (open(p, 'w').write('x'), True)[1])
    calls = []
    real = pl._cleanup_legacy

    def spy(sd=None):
        calls.append(sd)
        return real(sd if sd else d)

    monkeypatch.setattr(pl, '_cleanup_legacy', spy)
    pl.autostart_set(True, d)
    assert calls, '开启时必须清理旧版启动项'
    assert not any(os.path.exists(os.path.join(d, o)) for o in pl.AUTOSTART_LEGACY), '旧 .bat/.cmd 应被删除'


def test_autostart_target_dev_vs_frozen(tmp_path, monkeypatch):
    """开发版 → 启动桌宠.bat（存在时）；打包版 → exe 本身"""
    bat = tmp_path / '启动桌宠.bat'
    bat.write_text('@echo off', encoding='utf-8')
    monkeypatch.delattr(__import__('sys'), 'frozen', raising=False)
    t, w = pl.autostart_target(base_dir=str(tmp_path), script_path=str(tmp_path / 'desktop_pet.py'))
    assert t == str(bat) and w == str(tmp_path)

    monkeypatch.setattr(__import__('sys'), 'frozen', True, raising=False)
    t2, w2 = pl.autostart_target()
    assert t2 == __import__('sys').executable


def test_autostart_non_windows_degrades(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, 'is_windows', lambda: False)
    monkeypatch.setattr(pl, '_cleanup_legacy', lambda sd=None: [])
    ok, msg = pl.autostart_set(True, str(tmp_path))
    assert ok is False and 'Windows' in msg


# ---------------------------------------------------------------- 窗口特效（批次 2）

def test_apply_pet_window_flags():
    """真建一个 QWidget，验证标志/属性确实设上（offscreen 也能查）"""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QWidget
    app = QApplication.instance() or QApplication([])
    w = QWidget()
    assert pl.apply_pet_window(w) is True
    flags = w.windowFlags()
    assert flags & Qt.FramelessWindowHint
    assert flags & Qt.WindowStaysOnTopHint
    assert flags & Qt.Tool
    assert flags & Qt.NoDropShadowWindowHint
    assert w.testAttribute(Qt.WA_TranslucentBackground)
    w.deleteLater()
    assert app is not None


def test_set_topmost_toggle():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QWidget
    app = QApplication.instance() or QApplication([])
    w = QWidget()
    assert pl.set_topmost(w, True) is True
    assert w.windowFlags() & Qt.WindowStaysOnTopHint
    assert pl.set_topmost(w, False) is True
    assert not (w.windowFlags() & Qt.WindowStaysOnTopHint)
    w.deleteLater()
    assert app is not None


def test_clear_dwm_shadow_degrades_on_non_windows(monkeypatch):
    monkeypatch.setattr(pl, 'is_windows', lambda: False)
    assert pl.clear_dwm_shadow(1234) is False
    assert pl.clear_dwm_shadow(0) is False


# ---------------------------------------------------------------- 批次 3 新增能力

def test_foreground_helpers_delegate(monkeypatch):
    import pet_foreground
    monkeypatch.setattr(pet_foreground, 'categorize', lambda p=None: 'dev')
    monkeypatch.setattr(pet_foreground, 'busy_level', lambda p=None: 'mid')
    monkeypatch.setattr(pet_foreground, 'category_label', lambda c: '开发')
    monkeypatch.setattr(pet_foreground, 'privacy_note', lambda: '只读进程名')
    monkeypatch.setattr(pet_foreground, 'foreground_process_name', lambda: 'code.exe')
    assert pl.foreground_categorize() == 'dev'
    assert pl.foreground_categorize('zoom.exe') == 'dev'
    assert pl.foreground_busy_level() == 'mid'
    assert pl.foreground_label('dev') == '开发'
    assert pl.foreground_privacy_note() == '只读进程名'


def test_lock_screen_and_dpi_degrade_off_windows(monkeypatch):
    monkeypatch.setattr(pl, 'is_windows', lambda: False)
    assert pl.lock_screen() is False
    assert pl.enable_dpi_awareness() is False


def test_lock_screen_calls_user32(monkeypatch):
    calls = []

    class _U:
        @staticmethod
        def LockWorkStation():
            calls.append('lock')
            return 1

        @staticmethod
        def SetProcessDPIAware():
            calls.append('dpi')
            return 1

    class _Ctypes:
        windll = type('W', (), {'user32': _U()})()

    monkeypatch.setattr(pl, 'is_windows', lambda: True)
    monkeypatch.setitem(__import__('sys').modules, 'ctypes', _Ctypes())
    assert pl.lock_screen() is True
    assert pl.enable_dpi_awareness() is True
    assert calls == ['lock', 'dpi']


def test_beep_vocabulary_matches_host(monkeypatch):
    """铃声序列必须与原宿主一致：msg=880+1320、remind=660+990、其它=660"""
    played = []

    class _WS:
        SND_FILENAME = 1

        @staticmethod
        def Beep(f, d):
            played.append((f, d))

    monkeypatch.setattr(pl, 'is_windows', lambda: True)
    monkeypatch.setitem(__import__('sys').modules, 'winsound', _WS)
    pl.beep('msg')
    assert played == [(880, 80), (1320, 80)]
    played.clear()
    pl.beep('remind')
    assert played == [(660, 200), (990, 200)]
    played.clear()
    pl.beep('other')
    assert played == [(660, 100)]
