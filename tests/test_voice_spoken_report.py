# -*- coding: utf-8 -*-
"""朗读实况回灌 + 朗读字数上限（2026-10-26，WX-125）

起因（Owner 实测）：让它念《过秦论》，它写了 1419 字、说「念下来两千字出头，
我这边读完确实费了点劲」，而**实际只念了开头寒暄和结尾问句共 70 字，正文五段一个字没出声**。

两个缺陷：
  ① `voice_max_chars` 是死配置：代码读、config 无、界面无入口，
     而截断日志还写着「可在 config.json 改 voice_max_chars」⇒ 用户被指去改不存在的东西。
  ② 语音层念了多少**从不回传**给模型 ⇒ 它不知道，于是把「只念了一部分」说成「念完了」。

本文件锁两件事的行为：
  · `_record_spoken_report` 只在明显少念时才留话，且只回灌一次
  · `_set_voice_max_chars` 越界夹紧、写配置、立刻对 VoiceIO 生效
"""
import io
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)


def _app():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope='module')
def pet():
    _app()
    import desktop_pet as dp
    p = dp.PetWidget()
    # 绝不写真实 config（本文件只测内存行为）
    p._save_cfg_value = lambda *a, **k: True
    p._notify = lambda *a, **k: None
    return p


# ---------------- ① 回灌：什么情况下该留话 ----------------

def test_reports_when_only_a_fraction_was_spoken(pet):
    """Owner 那次的比例（1419 字只念 70 字）必须留话"""
    pet.voice_content_mode = 'summary'
    pet.voice_max_chars = 1200
    pet._spoken_report = ''
    pet._record_spoken_report('x' * 1419, 'y' * 1419, 'z' * 70)
    note = pet._spoken_report
    assert note, '只念了 5% 却不留话 ⇒ 模型会继续以为念完了'
    assert '1419' in note and '70' in note, '回灌必须带具体字数，否则模型无从判断'
    assert '不是用户说的话' in note, '必须标明这是系统记录，防止被当成用户发言'
    # 光道歉不够，必须给出下一步
    assert '念全文' in note and 'set_voice_summary' in note


def test_no_report_when_fully_spoken(pet):
    """念全了就不能留话 —— 否则每轮都塞一句，把真正的提醒稀释成噪声"""
    pet.voice_content_mode = 'full'
    pet.voice_max_chars = 3000
    pet._spoken_report = ''
    pet._record_spoken_report('x' * 2337, 'y' * 2337, 'z' * 2299)
    assert pet._spoken_report == ''


@pytest.mark.parametrize('n_all,n_spoken,expect', [
    (1000, 800, False),     # 刚好 80% 边界 → 不算「明显少念」
    (1000, 799, True),      # 略低于 → 要留
    (0, 0, False),          # 空文本 → 不留
])
def test_threshold(pet, n_all, n_spoken, expect):
    pet._spoken_report = ''
    pet._record_spoken_report('x' * n_all, 'y' * n_all, 'z' * n_spoken)
    assert bool(pet._spoken_report) is expect


def test_report_consumed_only_once(pet):
    """只回灌一次：取过就清空，不能每轮重复塞同一句"""
    pet.voice_content_mode = 'summary'
    pet._spoken_report = ''
    pet._record_spoken_report('x' * 1419, 'y' * 1419, 'z' * 70)
    first = pet._take_spoken_report()
    assert first, '第一次取不到 ⇒ 回灌不生效'
    assert pet._take_spoken_report() == '', '第二次还取得到 ⇒ 会每轮重复'


# ---------------- ② voice_max_chars：能改、夹紧、立刻生效 ----------------

@pytest.mark.parametrize('given,expect', [
    (3000, 3000),
    (100, 200),       # 下限夹住
    (99999, 6000),    # 上限夹住
    ('5000', 5000),   # 字符串也能吃
])
def test_set_voice_max_chars_clamps(pet, given, expect):
    assert pet._set_voice_max_chars(given) == expect
    assert pet.voice_max_chars == expect


def test_set_voice_max_chars_applies_to_voiceio(pet):
    """改完必须立刻对 VoiceIO 生效（不能等重启）"""
    pet._set_voice_max_chars(3000)
    assert pet.voice.max_chars == 3000


def test_bad_value_does_not_crash(pet):
    pet._set_voice_max_chars(2500)
    assert pet._set_voice_max_chars('abc') == 2500, '坏值应保持原值，不许抛/不许归零'


# ---------------- ③ 结构：回灌位置不能在请求之后 ----------------

def test_spoken_report_injected_before_request_loop():
    """源码级锁定：take 必须在 messages 组装之后、请求循环之前

    这条防的是「把回灌写在发请求之后」——那样第一次请求永远拿不到，
    等于白做，而单测只测方法本身是发现不了的。
    """
    import ast
    path = os.path.join(BASE, 'desktop_pet.py')
    src = io.open(path, encoding='utf-8').read()
    tree = ast.parse(src)
    worker = None
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == '_ai_worker':
            worker = n
            break
    assert worker is not None

    msg_assign = take_line = insert_line = loop_line = None
    for n in ast.walk(worker):
        if isinstance(n, ast.Assign) and msg_assign is None:
            if any(isinstance(t, ast.Name) and t.id == 'messages' for t in n.targets):
                msg_assign = n.lineno
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            if n.func.attr == '_take_spoken_report' and take_line is None:
                take_line = n.lineno
            if (n.func.attr == 'insert' and insert_line is None
                    and isinstance(n.func.value, ast.Name) and n.func.value.id == 'messages'):
                insert_line = n.lineno
        if isinstance(n, ast.For) and loop_line is None:
            if isinstance(n.target, ast.Name) and n.target.id == '_':
                loop_line = n.lineno

    assert msg_assign and take_line and insert_line and loop_line
    assert take_line > msg_assign, 'take 必须在 messages 组装之后'
    assert insert_line < loop_line, 'insert 必须在请求循环之前，否则第一轮拿不到'
