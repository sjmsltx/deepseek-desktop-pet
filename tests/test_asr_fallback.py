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


def test_policy_blocked_skips_winrt():
    """已知 WinRT 被策略挡住 → 下一轮别先白等一轮必然失败的识别（最长 25 秒）

    使用者体感就是"点了没反应"，所以这条要锁死。
    """
    e, calls = _engine([lambda: (0, 'OK|0.9|WinRT 结果', ''),
                        lambda: (0, 'OK|0.9|SAPI 结果', '')])
    e._policy_blocked = True
    text, _c, err = e.listen()
    assert text == 'SAPI 结果' and err == '' and e.last_engine == 'sapi'
    assert len(calls) == 1 and '-Engine' in calls[0], calls


def test_available_asks_sapi_when_policy_blocked():
    """被策略挡住不等于整机不能用：要问 SAPI，而不是直接否决"""
    e = asr.AsrEngine(BASE)
    e._policy_blocked = True
    e._sapi_cache = ['zh-CN']
    ok, info = e.available()
    assert ok is True and '备用' in info
    e._sapi_cache = []
    ok2, info2 = e.available()
    assert ok2 is False and '在线语音识别' in info2


def test_rejected_falls_back_to_sapi():
    """WinRT 说「听到了但不敢认」时，必须再试一次 SAPI

    ⚠ 判断变过一次，两次依据都记在这里：
      1) 2026-10-25 上半场：认为「WinRT 质量更好，它都不敢认，SAPI 只会更差」，
         于是让它直接返回、省掉一轮等待。
      2) 同日下午实测（本机 Realtek 麦克风阵列，静音峰值约 25%、语音信号偏弱）：
         WinRT 外放 2 次 + 静音 1 次 **全部 REJECTED（0% 出字）**；
         SAPI 3 次里 2 次出字。
         ⇒ 「WinRT 一定更好」这个前提在本机不成立。
           宁可给一个低可信的猜测，也不要"点了完全没反应"。
    所以现在钉：REJECTED 必须降级，并且把 SAPI 的结果交出去。
    """
    e, calls = _engine([lambda: (0, 'REJECTED|听到了声音但没听准', ''),
                        lambda: (0, 'OK|0.42|SAPI 兜底结果', '')])
    e._policy_blocked = False
    text, conf, err = e.listen()
    assert text == 'SAPI 兜底结果', '没降级到 SAPI：%r' % (text,)
    assert len(calls) == 2, '应该跑两轮（WinRT + SAPI）：%r' % calls
    assert e.last_engine == 'sapi'


def test_rejected_and_sapi_both_fail_gives_env_hint():
    """两条都没结果时，提示要指向「麦克风底噪」这个真实原因"""
    e, _c = _engine([lambda: (0, 'REJECTED|听到了声音但没听准', ''),
                     lambda: (0, 'ERR|没听清（SAPI 超时）', '')])
    e._policy_blocked = False
    text, _conf, err = e.listen()
    assert text == ''
    assert '没听准' in err and '底噪' in err, err


def test_rejected_parsed_as_error_not_empty_success():
    """REJECTED 必须当成「没听准」，不能被当成「识别成功但文本为空」"""
    from asr import parse_result
    text, conf, err = parse_result("REJECTED|听到了声音但没听准" + chr(10))
    assert text == "" and conf == "Rejected"
    assert err, "REJECTED 必须带原因，否则界面只能说「没听到内容」"


def test_sapi_only_error_still_returned():
    e, _calls = _engine([lambda: (0, 'ERR|something weird but not policy', ''),
                         lambda: (0, 'ERR|SAPI 识别失败：Timeout', '')])
    _t, _c, err = e.listen()
    assert err and ('备用识别' in err)
