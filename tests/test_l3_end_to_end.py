# -*- coding: utf-8 -*-
"""端到端实测：L3 是否真的进了发给模型的请求

不测 memory_index 单函数（已 18 条绿），测**接线生效**：
走 _ai_worker 真实组装路径，截获 stream_chat_completions 收到的 data
（那是真正发出去的请求体 —— 由 _post_stream 闭包转发给它）。

判据：
  1. 先证明截获点有效（请求体里有 messages），否则后面全是假绿
  2. 问「我今天花了多少钱」→ 请求体里能搜到 L3 段 + 真实花费数字
  3. 问无关问题 → 请求体里搜不到 L3 段
"""
import json
import os
import re
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

import desktop_pet as dp  # noqa: E402


def _capture(text):
    """跑一次 _ai_worker，截获真正要发出去的请求体"""
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    box = {}

    def fake_stream(key, data, *a, **k):
        # 记录请求体后立刻异常退出 —— 一层层冒泡到 _ai_worker 自己的 try 里
        try:
            box['body'] = json.loads(data.decode('utf-8'))
        except Exception as _exc:
            box['err'] = repr(_exc)
        raise RuntimeError('__captured__')
        yield  # 让它仍是个 generator（语法上需要）

    orig = dp.stream_chat_completions
    dp.stream_chat_completions = fake_stream
    try:
        try:
            p._ai_worker(text)
        except Exception:
            pass
    finally:
        dp.stream_chat_completions = orig
    return p, box.get('body')


def _system_text(body):
    if not body:
        return ''
    return '\n'.join(m.get('content') or '' for m in body.get('messages', [])
                     if m.get('role') == 'system')


def test_capture_point_is_valid():
    """先证明截获点对：请求体里必须有 messages —— 否则后面三条是假绿"""
    _p, body = _capture('你好')
    assert body, '没截到请求体 —— 截获点错了，后面的断言都会是假绿'
    assert body.get('messages'), '请求体没有 messages'
    assert body.get('model'), '请求体没有 model'


def test_l3_reaches_system_prompt():
    _p, body = _capture('我今天花了多少钱')
    txt = _system_text(body)
    assert 'L3 索引' in txt, 'L3 段没进 system prompt。system 前 500 字：\n%s' % txt[:500]


def test_l3_carries_real_number():
    p, body = _capture('我今天花了多少钱')
    txt = _system_text(body)
    cost = float(p.api_stats.today['cost'])
    assert ('%.4f' % cost) in txt, (
        'prompt 数字与 api_stats.today 不一致：期望 %.4f，实际 ¥ 值 %r\nL3 相关行：%r'
        % (cost, re.findall(r'¥[\d.]+', txt)[:6],
           [l for l in txt.splitlines() if 'L3' in l or 'api_stats' in l]))


def test_l3_absent_for_unrelated_question():
    _p, body = _capture('今天天气怎么样')
    txt = _system_text(body)
    assert 'L3 索引' not in txt, '无关问题不该注入 L3，尾部：\n%s' % txt[-600:]
