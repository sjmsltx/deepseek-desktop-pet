# -*- coding: utf-8 -*-
"""语音输入（ASR）护栏（v6.66）

要点：
- 识别失败/超时/麦克风被拒 → 给出**明确原因**，不静默失败
- 识别成功 → 文本**只填进输入框**，绝不自动发送（保留用户确认这一步）
- 本机没能力（缺语言包等）→ 点按钮直接说明并提示 Win+H，而不是卡住

运行：python -m pytest tests/test_asr.py -q
"""
import os
import subprocess
import sys
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import asr as A          # noqa: E402


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


# ---------------------------------------------------------------- 输出解析

def test_parse_result_variants():
    assert A.parse_result('OK|High|你好世界') == ('你好世界', 'High', '')
    assert A.parse_result('噪音\nOK|Medium|带|竖线的句子') == ('带|竖线的句子', 'Medium', '')
    assert A.parse_result('ERR|缺语言包')[2] == '缺语言包'
    assert A.parse_result('') [2] != ''
    assert A.parse_result('完全不是契约')[2] != ''


# ---------------------------------------------------------------- 能力检测

def test_available_ok_and_cache():
    calls = {'n': 0}

    def runner(args, timeout):
        calls['n'] += 1
        assert '-Check' in args
        return 0, 'OK|zh-Hans-CN|zh-Hans-CN', ''
    e = A.AsrEngine(BASE, runner=runner)
    ok, info = e.available()
    assert ok is True and 'zh-Hans-CN' in info
    e.available()
    assert calls['n'] == 1, '能力检测要缓存（别每次点都跑一遍 powershell）'
    assert e.available(refresh=True)[0] is True and calls['n'] == 2


def test_available_reports_error():
    e = A.AsrEngine(BASE, runner=lambda a, t: (6, 'ERR|识别器创建失败：缺语言包', ''))
    ok, info = e.available()
    assert ok is False and '语言包' in info


def test_available_missing_script(tmp_path):
    e = A.AsrEngine(str(tmp_path))
    ok, info = e.available()
    assert ok is False and 'asr_helper' in info


# ---------------------------------------------------------------- 识别

def test_listen_success():
    e = A.AsrEngine(BASE, runner=lambda a, t: (0, 'OK|High|给桌宠加个语音输入', ''))
    text, conf, err = e.listen()
    assert text == '给桌宠加个语音输入' and conf == 'High' and err == ''


def test_listen_empty_speech():
    e = A.AsrEngine(BASE, runner=lambda a, t: (0, 'OK|Low|', ''))
    assert e.listen() == ('', 'Low', '')


def test_listen_timeout_kills_process():
    killed = {'n': 0}

    def runner(args, timeout):
        raise subprocess.TimeoutExpired(cmd='powershell', timeout=timeout)
    e = A.AsrEngine(BASE, runner=runner)
    text, conf, err = e.listen()
    assert '超时' in err and 'Win+H' in err, '超时要给出可操作的替代建议'


def test_listen_maps_mic_permission_error():
    e = A.AsrEngine(BASE, runner=lambda a, t: (6, 'ERR|Access is denied. (0x80070005)', ''))
    text, conf, err = e.listen()
    assert err and ('麦克风' in err or '权限' in err), '权限问题要说人话'


def test_cancel_kills_running_proc(monkeypatch):
    class _P:
        def __init__(self):
            self.killed = False

        def kill(self):
            self.killed = True
    p = _P()
    e = A.AsrEngine(BASE)
    e._proc = p
    assert e.cancel() is True and p.killed is True
    e._proc = None
    assert e.cancel() is False


def test_subprocess_started_without_console_window():
    src = open(os.path.join(BASE, 'asr.py'), encoding='utf-8').read()
    assert 'CREATE_NO_WINDOW' in src and 'creationflags=_win_flags()' in src
    ps = open(os.path.join(BASE, 'asr_helper.ps1'), encoding='utf-8').read()
    assert 'Windows.Media.SpeechRecognition' in ps and 'RecognizeAsync' in ps
    assert 'System.Runtime.WindowsRuntime' in ps, 'PS5.1 下需要它才能 await WinRT'


# ---------------------------------------------------------------- 宿主行为

def _pet():
    _app()
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p._notify = lambda *a, **k: None
    return p


def test_mic_button_exists_and_toggles():
    p = _pet()
    assert p.mic_btn.text() == '🎤'
    p.asr.available = lambda refresh=False: (True, 'ok')
    p.asr.listen = lambda: ('你好世界', 'High', '')
    p._toggle_listen()
    assert p.mic_btn.text() == '⏺' or p._listening is True
    for _ in range(80):
        _app().processEvents()          # 必須跑事件循环，否则 _run_on_ui 回主线程的回调不会执行
        if not p._listening:
            break
        time.sleep(0.05)
    assert p.chat_input.toPlainText() == '你好世界', '识别结果应填进输入框'
    assert p.mic_btn.text() == '🎤'


def test_recognized_text_is_not_auto_sent():
    p = _pet()
    sent = {'n': 0}
    p.ask_ai = lambda *a, **k: sent.__setitem__('n', sent['n'] + 1)
    p.asr.available = lambda refresh=False: (True, 'ok')
    p.asr.listen = lambda: ('不要自动发送', 'High', '')
    p._toggle_listen()
    for _ in range(80):
        _app().processEvents()
        if not p._listening:
            break
        time.sleep(0.05)
    assert p.chat_input.toPlainText() == '不要自动发送'
    assert sent['n'] == 0, '语音结果必须等用户按回车，不得自动发送'


def test_no_capability_gives_clear_message():
    p = _pet()
    msgs = []
    p._notify = lambda t, **k: msgs.append(str(t))
    p.asr.available = lambda refresh=False: (False, '缺语音语言包')
    p._toggle_listen()
    assert msgs and '语言包' in msgs[0] and 'Win+H' in msgs[0]
    assert p._listening is False


def test_cancel_while_listening():
    p = _pet()
    cancelled = {'n': 0}
    p.asr.available = lambda refresh=False: (True, 'ok')
    p.asr.listen = lambda: (time.sleep(0.4), ('迟到的结果', 'High', ''))[1]
    p.asr.cancel = lambda: (cancelled.__setitem__('n', cancelled['n'] + 1), True)[1]
    p._toggle_listen()
    assert p._listening is True
    p._toggle_listen()          # 再点一次 = 取消
    assert cancelled['n'] == 1 and p._listening is False
    assert p.mic_btn.text() == '🎤'


def test_menu_has_voice_input_entry():
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    assert "'🎤 语音输入'" in src and 'def _toggle_listen' in src


def test_privacy_policy_error_is_explained():
    """实测踩到的坑：WinRT 报 “speech privacy policy was not accepted”

    这不是 bug，也不该我们默默改注册表 —— 要把“去开哪个开关”说清楚，并记住这个状态。
    """
    e = A.AsrEngine(BASE, runner=lambda a, t: (
        6, 'ERR|The speech privacy policy was not accepted prior to attempting a speech recognition.', ''))
    text, conf, err = e.listen()
    assert '在线语音识别' in err and '隐私' in err and 'Win+H' in err
    ok, info = e.available()
    assert ok is False and '在线语音识别' in info, '之后每次点按钮都该直接给出指引（不再跑一轮）'


if __name__ == '__main__':
    import pytest
    raise SystemExit(pytest.main([__file__, '-q']))
