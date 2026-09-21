# -*- coding: utf-8 -*-
"""语音输入双路径：WinRT 失败 → 自动降级 SAPI（v6.77）

背景：使用者开了 Windows 的语音隐私开关，但 OneCore 那条路实测被策略挡住
（注册表 Speech_OneCore\\Settings\\SpeechRecognizer 键不存在 → WinRT 必败）。
System.Speech（SAPI）走另一套识别栈、**不依赖那个策略** → 做自动降级，
让语音输入在“策略没落盘”的机器上也能用。
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import asr                                                       # noqa: E402

POLICY_ERR = 'The speech privacy policy was not accepted'


def _engine(seq):
    calls = []

    def runner(args, timeout=30):
        calls.append(list(args))
        idx = 0 if '-Engine' not in args else 1
        return seq[idx]()

    e = asr.AsrEngine(BASE, runner=runner)
    return e, calls


def test_falls_back_to_sapi_when_winrt_policy_blocked():
    e, calls = _engine([lambda: (0, 'ERR|' + POLICY_ERR, ''),
                        lambda: (0, 'OK|0.87|这是 SAPI 识别结果', '')])
    text, conf, err = e.listen()
    assert text == '这是 SAPI 识别结果' and err == ''
    assert e.last_engine == 'sapi'
    assert any('-Engine' in c for c in calls), '没有真的去试 SAPI'
    assert e._policy_blocked is False, 'SAPI 走通后不该再宣称被策略阻断'


def test_winrt_success_does_not_call_sapi():
    e, calls = _engine([lambda: (0, 'OK|0.9|WinRT 结果', ''), lambda: (0, 'OK|0.9|x', '')])
    text, _conf, _err = e.listen()
    assert text == 'WinRT 结果' and e.last_engine == 'winrt'
    assert not any('-Engine' in c for c in calls), 'WinRT 成了就不该再多跑一趟'


def test_both_fail_reports_actionable_hint():
    e, _calls = _engine([lambda: (0, 'ERR|' + POLICY_ERR, ''),
                         lambda: (0, 'ERR|SAPI 识别失败：no recognizer', '')])
    text, _conf, err = e.listen()
    assert text == ''
    assert '隐私' in err or 'Win+H' in err
    assert '备用识别' in err, '要说明已试过备用路径，否则使用者会以为是没做'
    assert e._policy_blocked is True


def test_sapi_only_error_still_returned():
    e, _calls = _engine([lambda: (0, 'ERR|something weird but not policy', ''),
                         lambda: (0, 'ERR|SAPI 识别失败：Timeout', '')])
    _t, _c, err = e.listen()
    assert err and ('备用识别' in err)
