# -*- coding: utf-8 -*-
"""新增测试：声线不能被静默换掉

锁四件事（每件都有 2026-10-25 的实测依据）：
  1 降级时 actual_voice 必须能报出「实际用的是谁」
  2 describe_actual 必须判出「与设置不一致」
  3 指定声线不存在时，ps1 要 WARN（不静默）
  4 主程序对降级只提示一次，且不误报（设置与实况一致时不提示）

⛔ 全部用注入替身，不真起 powershell、不真合成音频 —— 否则测试慢且依赖本机声线。
"""
import io
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


def _voice(**kw):
    from voice_io import VoiceIO
    kw.setdefault('enabled', True)
    return VoiceIO(BASE, **kw)


class _FakeProc:
    def __init__(self, stdout=b''):
        self.stdout = stdout
        self.stderr = b''
        self.returncode = 0


def test_offline_records_actual_voice_with_spaces(monkeypatch, tmp_path):
    """实际声线名带空格时必须完整取到（"Microsoft Huihui"，不是 "Microsoft"）

    第一次实现用 seg.split(' ', 1)[0]，只拿到 "Microsoft" —— 等于没报。
    """
    import voice_io as V

    v = _voice(engine='offline', voice='edge:zh-CN-XiaoxiaoNeural')
    out = str(tmp_path / 'x.wav')

    def fake_run(cmd, **kw):
        # 造一个足够大的假 wav，让 _synth_offline 认为成功
        open(out, 'wb').write(b'RIFF' + b'\x00' * 400)
        return _FakeProc(b'OK engine=winrt voice=Microsoft Huihui bytes=404 out=' + out.encode())

    monkeypatch.setattr(V.subprocess, 'run', fake_run)
    ok, err = v._synth_offline('你好', out)
    assert ok and not err
    assert v.actual_voice == 'Microsoft Huihui', v.actual_voice


def test_offline_warn_is_kept_in_last_error(monkeypatch, tmp_path):
    """指定声线不存在时，WARN 必须留在 last_error（不能假装按设置念了）"""
    import voice_io as V

    v = _voice(engine='offline', voice='offline:不存在的声线')
    out = str(tmp_path / 'y.wav')

    def fake_run(cmd, **kw):
        open(out, 'wb').write(b'RIFF' + b'\x00' * 400)
        return _FakeProc('WARN|指定的 WinRT 声线不存在：不存在的声线（改用系统默认）\n'
                         'OK engine=winrt voice=Microsoft Kangkang bytes=404\n'.encode('utf-8'))

    monkeypatch.setattr(V.subprocess, 'run', fake_run)
    ok, _err = v._synth_offline('你好', out)
    assert ok
    assert '不存在' in v.last_error, v.last_error
    assert v.actual_voice == 'Microsoft Kangkang'


def test_fallback_voice_used_instead_of_system_default(monkeypatch, tmp_path):
    """配置了 fallback_voice 时，降级用它；未配置时才交给系统默认"""
    import voice_io as V

    seen = []

    def fake_run(cmd, **kw):
        seen.append(list(cmd))
        outp = cmd[cmd.index('-Out') + 1]
        open(outp, 'wb').write(b'RIFF' + b'\x00' * 400)
        return _FakeProc(b'OK engine=winrt voice=Microsoft Yaoyao bytes=404')

    monkeypatch.setattr(V.subprocess, 'run', fake_run)

    v = _voice(engine='offline', voice='edge:zh-CN-XiaoxiaoNeural', fallback_voice='Yaoyao')
    v._synth_offline('你好', str(tmp_path / 'a.wav'))
    assert '-Voice' in seen[0] and seen[0][seen[0].index('-Voice') + 1] == 'Yaoyao'

    seen.clear()
    v2 = _voice(engine='offline', voice='edge:zh-CN-XiaoxiaoNeural')
    v2._synth_offline('你好', str(tmp_path / 'b.wav'))
    assert '-Voice' not in seen[0], '没配 fallback 时不该硬塞声线名'


def test_describe_actual_flags_mismatch():
    """设置晓晓、实际离线 → 必须报「不一致」；设置就是离线同一个 → 不报"""
    v = _voice(engine='auto', voice='edge:zh-CN-XiaoxiaoNeural')
    v.actual_engine = 'offline'
    v.actual_voice = 'Microsoft Huihui'
    label, changed = v.describe_actual()
    assert changed is True
    assert 'Huihui' in label and '离线' in label

    v2 = _voice(engine='offline', voice='offline:Huihui')
    v2.actual_engine = 'offline'
    v2.actual_voice = 'Microsoft Huihui'
    _l, changed2 = v2.describe_actual()
    assert changed2 is False, '设置与实况一致时不该报不一致'

    v3 = _voice(engine='auto', voice='edge:zh-CN-XiaoxiaoNeural')
    v3.actual_engine = 'edge'
    v3.actual_voice = 'zh-CN-XiaoxiaoNeural'
    _l3, changed3 = v3.describe_actual()
    assert changed3 is False


def test_host_notifies_once_when_voice_swapped():
    """主程序：降级提示一次就够，重复调用不再刷；一致时不提示"""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    assert app is not None
    import desktop_pet as dp

    p = dp.PetWidget()
    notes = []
    p._notify = lambda m, *a, **k: notes.append(str(m))
    try:
        p.voice.actual_engine = 'offline'
        p.voice.actual_voice = 'Microsoft Kangkang'
        p.voice.last_error = '已降级（在线合成失败：403）'
        p._voice_note_key = ''
        for _ in range(4):
            p._voice_note_actual()
        assert len(notes) == 1, '同一情况重复刷屏了：%r' % notes
        assert 'Kangkang' in notes[0], notes[0]

        # 设置与实况一致 → 不该再提示
        p.voice.voice = 'offline:Kangkang'
        p._voice_note_key = ''
        n = len(notes)
        p._voice_note_actual()
        assert len(notes) == n
    finally:
        p.deleteLater()


def test_old_edge_token_gets_upgrade_hint(monkeypatch):
    """token 是旧格式时，提示里必须出现升级方法（否则只有一句 403，看不出原因）

    判据要能证伪：新格式时必须**不**提示 —— 否则等于一直提示，等于没提示。

    ⛔ 只 patch 被测的那一个静态方法。上一版我顺手把 sys.modules['edge_tts.drm']
       换成了假模块，导致 edge_tts 自己 `from .drm import DRM` 直接 ImportError。
    """
    import edge_tts.drm as real_drm

    import voice_io as V

    monkeypatch.setattr(real_drm.DRM, 'generate_sec_ms_gec',
                        staticmethod(lambda: 'A' * 64))          # 旧：单个 64 位 hex
    hint = V.edge_tts_version_hint()
    assert 'pip install -U edge-tts' in hint, hint

    monkeypatch.setattr(real_drm.DRM, 'generate_sec_ms_gec',
                        staticmethod(lambda: 'A' * 16 + '-' + 'B' * 64))   # 新：含 '-'
    assert V.edge_tts_version_hint() == '', '新格式不该提示（否则等于没提示）'
