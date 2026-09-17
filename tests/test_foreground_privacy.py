# -*- coding: utf-8 -*-
"""前台程序感知的隐私护栏 + 判定逻辑测试（v6.59）

本文件是「隐私边界」的机器保证：pet_foreground 只允许读进程名，
一旦有人（包括 AI 自己）往里加了读窗口标题 / 截屏 / 联网的代码，这里会红灯。

运行：python -m pytest tests/test_foreground_privacy.py -q
"""
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import pet_foreground as fg  # noqa: E402

SRC_PATH = os.path.join(BASE, 'pet_foreground.py')
SRC = open(SRC_PATH, encoding='utf-8').read()
SRC_NO_DOC = re.sub(r'"""[\s\S]*?"""', '', SRC)      # 去掉文档字符串后再查（文档里提到这些词是允许的）


def test_no_window_title_api():
    """护栏 1：不得出现任何「取窗口标题」的 API（窗口标题可能含网址/文件名/正文）"""
    forbidden = ['GetWindowText', 'GetWindowTextW', 'GetWindowTextA',
                 'GetWindowTextLength', 'WindowText', 'GetWindowInfo']
    hits = [w for w in forbidden if w in SRC_NO_DOC]
    assert not hits, f'pet_foreground 出现了取窗口标题的 API：{hits}'


def test_no_screenshot_or_input_api():
    """护栏 2：不截屏、不读输入内容、不读剪贴板"""
    forbidden = ['ImageGrab', 'pyautogui', 'screenshot', 'mss.', 'GetClipboard',
                 'GetKeyboardState', 'GetAsyncKeyState', 'GetLastInputInfo']
    hits = [w for w in forbidden if w in SRC_NO_DOC]
    assert not hits, f'pet_foreground 出现了截屏/输入类 API：{hits}'


def test_no_network():
    """护栏 3：不联网（数据只在进程内传给提示词）"""
    forbidden = ['import urllib', 'import requests', 'http.client', 'socket', 'urlopen']
    hits = [w for w in forbidden if w in SRC_NO_DOC]
    assert not hits, f'pet_foreground 出现了网络调用：{hits}'


def test_only_file_basename_no_path():
    """护栏 4：返回值只含文件名，绝不带路径（不泄露目录结构）"""
    assert fg._basename(r'C:\Users\someone\AppData\Local\Programs\X\Code.exe') == 'code.exe'
    assert fg._basename('/usr/bin/gedit') == 'gedit'
    assert fg._basename('') == ''
    # 实际取到的前台进程名也不带路径分隔符
    name = fg.foreground_process_name()
    assert isinstance(name, str)
    assert '\\' not in name and '/' not in name


def test_default_off_and_wired_to_config():
    """护栏 5：默认关闭 —— 配置读取处必须是 False 兜底"""
    pet = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    assert re.search(r"cfg\.get\('foreground_aware',\s*False\)", pet), \
        'desktop_pet 里 foreground_aware 的默认值必须是 False'


def test_categorize_and_level():
    assert fg.categorize('Code.exe') == 'code'
    assert fg.categorize('pycharm64.exe') == 'code'
    assert fg.categorize('Zoom.exe') == 'meeting'
    assert fg.categorize('genshinimpact.exe') == 'game'
    assert fg.categorize('PotPlayer.exe') == 'video'
    assert fg.categorize('WINWORD.EXE') == 'office'
    assert fg.categorize('chrome.exe') == 'browser'
    assert fg.categorize('windowsterminal.exe') == 'terminal'
    assert fg.categorize('whatever.exe') == 'other'
    assert fg.categorize('') == ''

    assert fg.busy_level('zoom.exe') == fg.LEVEL_HIGH
    assert fg.busy_level('genshinimpact.exe') == fg.LEVEL_HIGH
    assert fg.busy_level('potplayer.exe') == fg.LEVEL_HIGH
    assert fg.busy_level('code.exe') == fg.LEVEL_MID
    assert fg.busy_level('winword.exe') == fg.LEVEL_MID
    # 浏览器/终端/未知一律不表态 —— 不改变原有判断逻辑
    assert fg.busy_level('chrome.exe') == fg.LEVEL_NONE
    assert fg.busy_level('cmd.exe') == fg.LEVEL_NONE
    assert fg.busy_level('unknownapp.exe') == fg.LEVEL_NONE
    assert fg.busy_level('') == fg.LEVEL_NONE


def test_busy_hint_shape():
    assert fg.busy_hint('') == ''                      # 无信号必须为空，不污染提示词
    h = fg.busy_hint('code.exe')
    assert 'code.exe' in h and '写代码' in h
    h2 = fg.busy_hint(r'C:\Program Files\Zoom\bin\Zoom.exe')
    assert 'zoom.exe' in h2 and '会议' in h2
    for text in (h, h2, fg.busy_hint('whatever.exe')):
        assert '\\' not in text, '提示词里不得出现路径反斜杠'
        assert re.search(r'[A-Za-z]:[\\/]', text) is None, '提示词里不得出现盘符路径'
        assert re.search(r'(Users|AppData|Program Files)', text) is None, '提示词里不得出现目录名'


def test_privacy_note_wording():
    """界面上的隐私说明必须覆盖 4 个承诺，且不夸大"""
    note = fg.privacy_note()
    for word in ('进程名', '不读取窗口标题', '不截屏', '不上传'):
        assert word in note, f'隐私说明缺少承诺：{word}'


def test_judge_wakeup_accepts_hint():
    """care_engine.judge_wakeup 必须接受 busy_hint 且默认 None（向后兼容）"""
    import inspect
    import care_engine
    sig = inspect.signature(care_engine.judge_wakeup)
    assert 'busy_hint' in sig.parameters, 'judge_wakeup 未接入 busy_hint'
    assert sig.parameters['busy_hint'].default is None, 'busy_hint 默认值必须为 None'
