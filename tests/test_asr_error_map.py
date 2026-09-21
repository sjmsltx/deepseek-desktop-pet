# -*- coding: utf-8 -*-
"""语音输入错误分类（v6.75 修 bug）

背景：本机 WinRT 报 `RecognizeAsync ... "The text associated with this error code
could not be found."`（HRESULT 本地化文案取不到）→ 旧代码只匹配 'privacy policy' 字样
→ 匹配不上 → 使用者看到的是一句无意义的“识别失败”，真因（隐私策略没落盘）被丢掉。

本测试锁定：这几类错误都要被分类成可操作提示；未知错误仍原样返回。
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import asr                                                       # noqa: E402


@pytest.fixture(scope='module')
def eng():
    return asr.AsrEngine(BASE)


@pytest.mark.parametrize('err,kind', [
    ('Exception calling "RecognizeAsync" with "0" argument(s): '
     '"The text associated with this error code could not be found."', 'policy'),
    ('The speech privacy policy was not accepted', 'policy'),
    ('0x80045509 privacy', 'policy'),
    ('Access is denied', 'mic'),
    ('Microphone access denied', 'mic'),
    ('language pack not installed', 'lang'),
    ('未安装语言', 'lang'),
    ('完全未知的错误 xyz', 'other'),
])
def test_classify_error(eng, err, kind):
    got, hint = eng._classify_error(err)
    assert got == kind, (err, got)
    if kind != 'other':
        assert hint and len(hint) > 10, '应给出可操作提示'


def test_hint_has_no_markdown(eng):
    """提示是弹窗/输入框文字，不该带 markdown 星号"""
    for err in ('privacy policy', 'Access is denied', 'language'):
        _k, hint = eng._classify_error(err)
        if hint:
            assert '**' not in hint, hint


def test_policy_hint_mentions_windows_setting(eng):
    _k, hint = eng._classify_error('The speech privacy policy was not accepted')
    assert '隐私' in hint and 'Win+H' in hint
