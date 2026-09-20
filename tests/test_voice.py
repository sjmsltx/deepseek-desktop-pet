# -*- coding: utf-8 -*-
"""语音朗读（P0）护栏（v6.63）

只看三件事：① 默认关＝零子进程零音频；② 夜间静音；③ 文本清洗与顺序播放。
（合成/播放的真实链路已单独实测：WinRT 与 SAPI 都产出有效 wav，winsound 异步播放可打断。）

运行：python -m pytest tests/test_voice.py -q
"""
import os
import sys
import time
import wave

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import voice_io as vio      # noqa: E402


class _Recorder:
    """假的合成+播放器：只记录被念了什么"""
    def __init__(self, dur=0.01, boom=False):
        self.texts = []
        self.dur = dur
        self.boom = boom

    def __call__(self, wav_path, text):
        self.texts.append(text)
        if self.boom:
            raise RuntimeError('合成炸了')
        return self.dur


def _wait(cond, timeout=3.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.02)
    return False


# ---------------------------------------------------------------- 文本清洗

def test_clean_strips_tags_markdown_and_noise():
    raw = ('好呀！[emotion:happy] 我已经帮你查好了 🎉\n\n'
           '- 第一点 **很重要**，见 https://example.com/doc\n'
           '`code_span` 和 ```py\nprint(1)\n```\n')
    out = vio.clean_for_speech(raw)
    assert '[emotion' not in out and 'http' not in out and '**' not in out
    assert '🎉' not in out and '```' not in out
    assert '第一点' in out and '很重要' in out


def test_clean_caps_length_and_keeps_speech():
    out = vio.clean_for_speech('啊' * 500)
    assert len(out) <= vio.DEFAULT_MAX_CHARS + 1 and out.endswith('…')


def test_clean_returns_empty_for_noise():
    assert vio.clean_for_speech('') == ''
    assert vio.clean_for_speech('   \n\n  ') == ''
    assert vio.clean_for_speech('[emotion:happy] ✨✨✨ ---') == ''


# ---------------------------------------------------------------- 夜间静音

def test_is_night_boundaries():
    class _T:
        def __init__(self, h):
            self.hour = h
    assert vio.is_night(_T(23)) is True
    assert vio.is_night(_T(0)) is True
    assert vio.is_night(_T(7)) is True
    assert vio.is_night(_T(8)) is False
    assert vio.is_night(_T(12)) is False
    assert vio.is_night(_T(22)) is False


# ---------------------------------------------------------------- 开关与队列

def test_disabled_means_no_subprocess(tmp_path):
    rec = _Recorder()
    v = vio.VoiceIO(str(tmp_path), enabled=False, runner=rec)
    assert v.speak('你好') is False
    assert v.blocked_reason() == 'off'
    time.sleep(0.15)
    assert rec.texts == [], '关闭状态下不得有任何合成/播放'


def test_night_quiet_blocks(tmp_path):
    class _T:
        hour = 3

    rec = _Recorder()
    v = vio.VoiceIO(str(tmp_path), enabled=True, night_quiet=True, runner=rec)
    assert v.blocked_reason(now=_T()) == 'night'
    assert v.speak('夜里别出声', now=_T()) is False
    v.set_config(night_quiet=False)
    assert v.speak('现在可以了', now=_T()) is True
    assert _wait(lambda: rec.texts)


def _spec(**kw):
    """构造一个“随时可用”的 VoiceIO（关掉夜间静音，避免晚上跑测试时被静默拦掉）"""
    kw.setdefault('night_quiet', False)
    return kw


def test_speaks_cleaned_text_sequentially(tmp_path):
    rec = _Recorder(dur=0.05)
    v = vio.VoiceIO(str(tmp_path), enabled=True, **_spec(runner=rec))
    assert v.speak('第一句 [emotion:happy]') is True
    assert v.speak('第二句 **加粗**') is True
    assert _wait(lambda: len(rec.texts) == 2, timeout=5)
    assert rec.texts[0] == '第一句' and rec.texts[1] == '第二句 加粗', '应当念清洗后的文本'
    assert v.spoken_count >= 1


def test_stop_clears_queue(tmp_path):
    rec = _Recorder(dur=0.2)
    v = vio.VoiceIO(str(tmp_path), enabled=True, **_spec(runner=rec))
    for i in range(5):
        v.speak('第%d句' % i)
    time.sleep(0.05)
    v.stop()
    assert v.pending() == 0, 'stop() 应清空队列'


def test_runner_failure_does_not_kill_worker(tmp_path):
    boom = _Recorder(boom=True)
    v = vio.VoiceIO(str(tmp_path), enabled=True, **_spec(runner=boom))
    assert v.speak('会炸的一句') is True
    assert _wait(lambda: v.last_error != '', timeout=3), '失败要记下来'
    ok = _Recorder()
    v._runner = ok
    assert v.speak('后面这句还行') is True
    assert _wait(lambda: ok.texts, timeout=3), '一次失败不该让朗读永久哑掉'


# ---------------------------------------------------------------- 实现约束

def test_helper_script_exists_and_has_fallback():
    ps = os.path.join(BASE, 'tts_helper.ps1')
    assert os.path.exists(ps)
    src = open(ps, encoding='utf-8').read()
    assert 'Windows.Media.SpeechSynthesis' in src, '应走 WinRT 内置声线'
    assert 'System.Speech' in src, '应有 SAPI 兜底'
    assert 'System.Runtime.WindowsRuntime' in src, 'PS5.1 下需要它才能 await WinRT'


def test_voice_io_has_no_gui_or_extra_deps():
    src = open(os.path.join(BASE, 'voice_io.py'), encoding='utf-8').read()
    tops = [ln.strip() for ln in src.splitlines()
            if ln.startswith(('import ', 'from '))]
    assert not any('PySide6' in ln for ln in tops), '朗读模块不该依赖 GUI（便于 headless 单测）'
    for bad in ('pyttsx3', 'requests'):
        assert bad not in src, '不引入这类依赖：%s' % bad
    assert 'winsound' in src, '离线 WAV 用标准库 winsound'
    assert 'mciSendString' in src, '在线 MP3 用系统 MCI（零依赖，可打断）'
    # edge_tts 必须惰性导入（缺包/断网时仍能跑离线）
    assert not any('edge_tts' in ln for ln in tops), 'edge_tts 不能写在顶层 import'
    assert 'import edge_tts' in src, '在线引擎应当能惰性加载 edge_tts'


# ---------------------------------------------------------------- v6.64 在线声线

def test_parse_voice_spec_and_engine_plan(tmp_path):
    assert vio.parse_voice_spec('') == ('edge', 'zh-CN-XiaoxiaoNeural')
    assert vio.parse_voice_spec('edge:zh-CN-YunxiNeural') == ('edge', 'zh-CN-YunxiNeural')
    assert vio.parse_voice_spec('offline:Huihui') == ('offline', 'Huihui')
    assert vio.parse_voice_spec('Huihui') == ('offline', 'Huihui'), '兼容旧配置里的裸声线名'
    assert vio.parse_voice_spec('乱写') == ('edge', 'zh-CN-XiaoxiaoNeural')
    v = vio.VoiceIO(str(tmp_path), engine='auto', voice='edge:zh-CN-XiaoxiaoNeural')
    assert v.engine_plan() == ['edge', 'offline'], '默认：先在线，失败转离线'
    v.set_config(voice='offline:Huihui')
    assert v.engine_plan() == ['offline'], '选了离线声线就别去联网'
    v.set_config(engine='edge')
    assert v.engine_plan() == ['edge', 'offline']
    v.set_config(engine='offline')
    assert v.engine_plan() == ['offline']


def test_voice_choices_include_both_engines():
    specs = [c[0] for c in vio.VOICE_CHOICES]
    assert any(s.startswith('edge:') for s in specs), '要有在线神经声线'
    assert any(s.startswith('offline:') for s in specs), '要有离线兜底声线'
    assert vio.DEFAULT_VOICE.startswith('edge:'), '默认应当是在线声线（音质优先）'


def test_online_success_uses_mp3(tmp_path, monkeypatch):
    v = vio.VoiceIO(str(tmp_path), engine='auto', voice='edge:zh-CN-XiaoxiaoNeural')
    monkeypatch.setattr(v, '_synth_edge', lambda t, p: (open(p, 'wb').write(b'x' * 999) and (True, '')))
    played = {}
    monkeypatch.setattr(v, '_play_mp3', lambda p: (played.setdefault('path', p), 2.0)[1])
    monkeypatch.setattr(v, '_synth_offline', lambda *a, **k: (_ for _ in ()).throw(
        AssertionError('在线成功时不该走离线')))
    dur = v._default_runner(str(tmp_path / 'base'), '你好')
    assert dur == 2.0 and v.last_engine == 'edge' and v.fell_back is False
    assert played['path'].endswith('.mp3'), '在线走 MP3'
    assert v.last_error == ''


def test_online_failure_falls_back_to_offline(tmp_path, monkeypatch):
    v = vio.VoiceIO(str(tmp_path), engine='auto', voice='edge:zh-CN-XiaoxiaoNeural')
    monkeypatch.setattr(v, '_synth_edge', lambda t, p: (False, '断网了'))
    monkeypatch.setattr(v, '_synth_offline',
                        lambda t, p: (open(p, 'wb').write(b'R' * 999) and (True, '')))
    monkeypatch.setattr(v, '_play_wav', lambda p: 1.5)
    dur = v._default_runner(str(tmp_path / 'base'), '你好')
    assert dur == 1.5 and v.last_engine == 'offline'
    assert v.fell_back is True and '断网' in v.last_error, '降级要如实记下来，不假装没问题'


def test_offline_only_never_touches_network(tmp_path, monkeypatch):
    v = vio.VoiceIO(str(tmp_path), engine='offline', voice='offline:Huihui')
    monkeypatch.setattr(v, '_synth_edge', lambda *a, **k: (_ for _ in ()).throw(
        AssertionError('离线引擎不得联网'))) 
    monkeypatch.setattr(v, '_synth_offline',
                        lambda t, p: (open(p, 'wb').write(b'R' * 999) and (True, '')))
    monkeypatch.setattr(v, '_play_wav', lambda p: 1.0)
    assert v._default_runner(str(tmp_path / 'base'), '你好') == 1.0
    assert v.last_engine == 'offline' and v.fell_back is False


def test_mci_helper_never_raises():
    ok, info = vio._mci('this is not an mci command')
    assert ok is False and isinstance(info, str)


def test_stop_purges_both_players(tmp_path):
    """stop() 要同时清 winsound 与 MCI（在线/离线都能被立刻打断）"""
    src = open(os.path.join(BASE, 'voice_io.py'), encoding='utf-8').read()
    seg = src.split('def _purge(')[1][:400]
    assert 'SND_PURGE' in seg and 'MCI_ALIAS' in seg
    v = vio.VoiceIO(str(tmp_path), enabled=True)
    assert v.stop() is True


# ---------------------------------------------------------------- v6.64 降延时 / 去闪窗 / 自定义声线

def test_split_sentences():
    got = vio.split_sentences('第一句。第二句！第三句？')
    assert got == ['第一句。', '第二句！', '第三句？']
    long_one = '这是一句很长的句子，' * 6
    pieces = vio.split_sentences(long_one, max_len=30)
    assert len(pieces) > 1 and all(len(p) <= 31 for p in pieces), '过长要切短，保证首句够快'
    assert vio.split_sentences('') == []
    assert vio.split_sentences('没有标点的一句话') == ['没有标点的一句话']


def test_pipeline_overlaps_synthesis_with_playback(tmp_path):
    """降延时的关键：**下一句的合成必须在上一句播放期间就开始**

    真实播放器（MCI / winsound）是异步的：`_play_*` 立刻返回、音频在后台放。
    所以这里把 `_play_kind` 也模拟成“立即返回 + 返回时长”，再断言第二句的合成
    发生在第一句的播放窗口内（若代码是“整段合成完再放”，或“等播完再合成下一句”，都会失败）。
    """
    v = vio.VoiceIO(str(tmp_path), engine='auto', voice='edge:zh-CN-XiaoxiaoNeural')
    log = []

    def fake_synth_any(text, base):
        time.sleep(0.05)                       # 模拟合成耗时
        path = base + '.mp3'
        open(path, 'wb').write(b'x' * 512)
        log.append(('synth', text, time.time()))
        return path, 'mp3', 'edge'

    def fake_play(path, kind):
        log.append(('play', path, time.time()))
        return 0.5                             # 播放时长 0.5s，但立即返回（异步播放）

    v._synth_any = fake_synth_any
    v._play_kind = fake_play
    total = v._default_runner(str(tmp_path / 'b'), '第一句。第二句。第三句。')
    assert total == 1.5 and len([x for x in log if x[0] == 'synth']) == 3
    play1 = [x for x in log if x[0] == 'play'][0][2]
    synth2 = [x for x in log if x[0] == 'synth' and x[1] == '第二句。'][0][2]
    assert synth2 - play1 < 0.5, '第二句应在第一句还没播完时就合成好（这就是降延时的关键）'
    assert synth2 > play1, '顺序应先是“开声”，再并行合成下一句'


def test_fallback_reason_is_recorded(tmp_path, monkeypatch):
    """降级要如实留痕（否则用户不知道音质为何变差）"""
    v = vio.VoiceIO(str(tmp_path), engine='auto', voice='edge:zh-CN-XiaoxiaoNeural')
    monkeypatch.setattr(v, '_synth_edge', lambda t, p: (False, '断网了'))
    monkeypatch.setattr(v, '_synth_offline',
                        lambda t, p: (open(p, 'wb').write(b'R' * 999) and (True, '')))
    monkeypatch.setattr(v, '_play_wav', lambda p: 1.2)
    assert v._default_runner(str(tmp_path / 'b'), '一句。') == 1.2
    assert v.last_engine == 'offline' and v.fell_back is True
    assert '断网' in v.last_error, '降级原因必须留在 last_error 里'


def test_offline_subprocess_has_no_console_window(tmp_path):
    """离线合成不再闪控制台：子进程必须带 CREATE_NO_WINDOW"""
    src = open(os.path.join(BASE, 'voice_io.py'), encoding='utf-8').read()
    seg = src.split('def _synth_offline(')[1][:1200]
    assert 'creationflags=_win_flags()' in seg
    assert 'CREATE_NO_WINDOW' in src
    # 列举声线同样不能闪窗
    seg2 = src.split('def list_system_voices(')[1][:800]
    assert 'creationflags=_win_flags()' in seg2


def test_list_system_voices_parses_helper(monkeypatch):
    class _P:
        stdout = ('winrt:Microsoft Huihui|zh-CN|Female\n'
                  'winrt:Microsoft Kangkang|zh-CN|Male\n'
                  'sapi:Microsoft Huihui Desktop|zh-CN|Female\n').encode('utf-8')
        stderr = b''
    monkeypatch.setattr(vio.subprocess, 'run', lambda *a, **k: _P())
    items = vio.list_system_voices('x.ps1')
    specs = [s for s, _ in items]
    assert specs == ['offline:Huihui', 'offline:Kangkang'], '重名要去重（Huihui 的 winrt/sapi 各一份）'
    assert all(lab.startswith('离线 · ') for _s, lab in items)


def test_list_system_voices_survives_failure(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError('powershell 挂了')
    monkeypatch.setattr(vio.subprocess, 'run', boom)
    assert vio.list_system_voices('x.ps1') == []


def test_list_edge_voices_filters_locale(monkeypatch):
    import sys
    import types

    fake = types.ModuleType('edge_tts')

    async def list_voices():
        return [{'ShortName': 'zh-CN-XiaoxiaoNeural', 'Gender': 'Female'},
                {'ShortName': 'zh-CN-YunxiNeural', 'Gender': 'Male'},
                {'ShortName': 'en-US-AriaNeural', 'Gender': 'Female'}]
    fake.list_voices = list_voices
    monkeypatch.setitem(sys.modules, 'edge_tts', fake)
    items = vio.list_edge_voices(locale_prefix='zh-')
    assert [s for s, _ in items] == ['edge:zh-CN-XiaoxiaoNeural', 'edge:zh-CN-YunxiNeural']
    assert '女声' in items[0][1]
    items_all = vio.list_edge_voices(locale_prefix='')
    assert len(items_all) == 3, '前缀为空时应该把其他语言声线也列出来（供用户自定义）'


def test_custom_voice_accepts_other_locale_and_offline_pack():
    assert vio.parse_voice_spec('edge:en-US-AriaNeural') == ('edge', 'en-US-AriaNeural')
    assert vio.parse_voice_spec('offline:Microsoft Yaoyao') == ('offline', 'Microsoft Yaoyao')
    assert vio.parse_voice_spec('edge:ja-JP-NanamiNeural') == ('edge', 'ja-JP-NanamiNeural')


def test_settings_and_host_wiring_for_custom_voice():
    sui = open(os.path.join(BASE, 'settings_ui.py'), encoding='utf-8').read()
    assert 'ed_voice_custom' in sui and '列出系统声线' in sui and '列出在线声线' in sui
    assert '_voice_edit_apply' in sui
    pet = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    assert 'def _voice_edit_apply' in pet and 'def _list_voices_dialog' in pet


# ---------------------------------------------------------------- v6.64 本地自建 TTS 服务

def _tiny_wav():
    import io as _io
    buf = _io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b'\x00\x00' * 1600)
    return buf.getvalue()


def _wait_ready(port, timeout=5.0):
    """等本地服务真的可连（避免“起了线程就立刻连”的竞态）"""
    import socket
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = socket.socket()
        s.settimeout(0.3)
        try:
            s.connect(('127.0.0.1', port))
            return True
        except Exception:
            time.sleep(0.05)
        finally:
            try:
                s.close()
            except Exception:
                pass
    return False


def _fake_tts_server(got):
    """起一个真实 HTTP 服务：POST /tts → 返回一段 WAV（模拟 GPT-SoVITS 类接口）"""
    import http.server
    import socketserver
    import threading
    payload = _tiny_wav()

    class _Srv(socketserver.ThreadingTCPServer):
        allow_reuse_address = True

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get('Content-Length') or 0)
            got['path'] = self.path
            got['body'] = self.rfile.read(n)
            self.send_response(200)
            self.send_header('Content-Type', 'audio/wav')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            self.send_response(404)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = _Srv(('127.0.0.1', 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    assert _wait_ready(port), '本地假服务没能在超时内就绪'
    return srv, port


def test_parse_local_spec():
    assert vio.parse_voice_spec('local:http://127.0.0.1:9880') == ('local', 'http://127.0.0.1:9880')
    assert vio.parse_voice_spec('http://127.0.0.1:9880') == ('local', 'http://127.0.0.1:9880')
    v = vio.VoiceIO('.', voice='local:http://127.0.0.1:9880')
    assert v.engine_plan() == ['local', 'edge', 'offline'], '本地服务失败要能逐级降级'
    v.set_config(engine='local')
    assert v.engine_plan() == ['local', 'offline']


def test_local_tts_real_service_roundtrip(tmp_path):
    import json
    got = {}
    srv, port = _fake_tts_server(got)
    try:
        v = vio.VoiceIO(str(tmp_path), voice='local:http://127.0.0.1:%d' % port,
                        local_ref='D:/voice/my.wav', local_prompt='这是参考音频里的话')
        played = {}
        v._play_wav = lambda p: (played.setdefault('path', p), 1.0)[1]
        dur = v._default_runner(str(tmp_path / 'b'), '本地服务测试。')
        assert dur == 1.0 and v.last_engine == 'local', \
            '实际走了 %s，错误=%r' % (v.last_engine, v.last_error)
        assert played['path'].endswith('.wav'), '本地服务返回 WAV → 走 winsound 播放'
        sent = json.loads(got['body'].decode('utf-8'))
        assert got['path'] == '/tts', '约定路径是 POST {地址}/tts'
        assert sent['text'] == '本地服务测试。'
        assert sent['ref_audio_path'] == 'D:/voice/my.wav' and sent['prompt_text'] == '这是参考音频里的话'
    finally:
        srv.shutdown()


def test_local_tts_mp3_response_detected(tmp_path):
    import http.server
    import socketserver
    import threading
    payload = b'\xff\xf3\x00\x00' + b'\x00' * 2000        # 伪 MP3（帧同步头）

    class _Srv(socketserver.ThreadingTCPServer):
        allow_reuse_address = True

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length') or 0))
            self.send_response(200)
            self.send_header('Content-Type', 'audio/mpeg')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *a):
            pass

    srv = _Srv(('127.0.0.1', 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    assert _wait_ready(port), '本地假服务没能在超时内就绪'
    try:
        v = vio.VoiceIO(str(tmp_path), voice='local:http://127.0.0.1:%d' % port)
        v._play_mp3 = lambda p: 2.0
        assert v._default_runner(str(tmp_path / 'b'), '测试') == 2.0
        assert v.last_engine == 'local', '实际走了 %s，错误=%r' % (v.last_engine, v.last_error)
    finally:
        srv.shutdown()


def test_local_unavailable_degrades(tmp_path):
    v = vio.VoiceIO(str(tmp_path), voice='local:http://127.0.0.1:9',
                    local_timeout=2)
    v._synth_edge = lambda t, p: (open(p, 'wb').write(b'x' * 999) and (True, ''))
    v._play_mp3 = lambda p: 1.0
    assert v._default_runner(str(tmp_path / 'b'), '本地没开时要降级') == 1.0
    assert v.last_engine == 'edge' and v.fell_back is True
    assert v.last_error, '要留下降级原因'


def test_probe_local_service_real():
    got = {}
    srv, port = _fake_tts_server(got)
    try:
        ok, info = vio.probe_local_service('http://127.0.0.1:%d' % port, timeout=3)
        assert ok is True, '服务在跑（即使根路径 404 也算活着），实测 %r' % (info,)
    finally:
        srv.shutdown()
    ok2, info2 = vio.probe_local_service('http://127.0.0.1:9', timeout=2)
    assert ok2 is False and info2


def test_local_fields_wired_in_settings_and_host():
    sui = open(os.path.join(BASE, 'settings_ui.py'), encoding='utf-8').read()
    for token in ('ed_voice_local', 'ed_voice_ref', 'ed_voice_prompt', '测试本地服务'):
        assert token in sui, '设置页要能配本地服务：%s' % token
    pet = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    assert 'def _set_voice_local' in pet and 'def _test_local_tts' in pet
    assert 'voice_local_url' in pet and 'voice_local_ref' in pet


if __name__ == '__main__':
    import pytest
    raise SystemExit(pytest.main([__file__, '-q']))
