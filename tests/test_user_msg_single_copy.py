# -*- coding: utf-8 -*-
"""用户消息在上下文里只出现一次（2026-11-06）

## 为什么有这份测试

Owner 报：「她总说我把一句话发两次，但我并没有。」

实测根因：`ask_ai` 把当前消息**加了两次**
  · `chat_history_msgs.append(...)` 已入历史
  · `ctx = chat_history_msgs[-30:] + [{'role':'user','content':text}]` 又追加一遍
⇒ 模型看到连续两条一模一样的 user 消息，理解成「你连说两遍」。

点情感选项更糟：`_send_choice` 自己也 append 了一次 ⇒ 共 3 条。

## 口径

「用户消息入历史」只能有**一个**入口（`ask_ai` 开头），
且三条早退路径（未配置 / 引导并入 / 排队）都必须入历史 —— 否则用户说的话会丢。

本文件同时锁三件事：
  1. 历史里只有一条
  2. 真正发给模型的 messages 里也只有一条
  3. 源码里只有一处 `chat_history_msgs.append({'role': 'user'...})`（防回潮）
"""
import json
import os
import sys

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

import desktop_pet as dp          # noqa: E402
import affection_engine as ae     # noqa: E402


def _pet(tmp_path, **attrs):
    """产品真实入口造实例；只打桩外部副作用（存盘/摘要/气泡/通知）"""
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p._save_chat_memory = lambda *a, **k: True
    p._summarize_old = lambda *a, **k: None
    p._load_ai_config = lambda *a, **k: None
    p.affection = ae.AffectionEngine(str(tmp_path / 'aff.json'))
    p._bubbles = []
    p._notices = []
    p._chats = []
    p.say_plain = lambda t, *a, **k: p._bubbles.append(t)
    p._notify = lambda t, *a, **k: p._notices.append(t)
    p._append_chat = lambda who, t: p._chats.append((who, t))
    p.ai_enabled = True
    p.chat_history_msgs = []
    for k, v in attrs.items():
        setattr(p, k, v)
    return p


def _count_user(msgs, text):
    """数一数 msgs 里有几条 user 消息的内容含 text"""
    n = 0
    for m in msgs:
        if m.get('role') != 'user':
            continue
        c = m.get('content')
        if isinstance(c, list):     # 多模态 content 数组
            c = json.dumps(c, ensure_ascii=False)
        if text in str(c or ''):
            n += 1
    return n


class _FakeStream:
    """假流式：一轮就结束，只用来抓请求里发出去的 messages"""

    def __init__(self):
        self.payloads = []

    def __call__(self, api_key, data, **kw):
        self.payloads.append(json.loads(data))
        yield ('content', '收到')
        yield ('done', {'content': '收到', 'tool_calls': None, 'reasoning_content': ''})


def _wire(p, fake):
    p._current_api_key = lambda: 'sk-test'      # 产品里它是方法，不是字符串
    p._request_endpoint = lambda: 'http://127.0.0.1:1/chat'
    p._execute_tool = lambda name, args: '工具结果'
    p._maybe_extract_memory = lambda: None
    p._speak_reply = lambda *a, **k: None
    p._record_api_usage = lambda *a, **k: None
    p._handle_affection = lambda *a, **k: None
    for _sig in (p.ai_status_signal, p.reasoning_signal, p.stream_signal,
                 p.stream_done_signal, p.ai_reply_signal):
        try:
            _sig.disconnect()
        except Exception:
            pass
    return fake


# ---------- A. 历史里只有一条 ----------
def test_ask_ai_records_user_msg_exactly_once(tmp_path):
    """输入框路径：ask_ai 一次，历史里只有一条"""
    p = _pet(tmp_path)
    p._run_task = lambda text, images=None: None    # 只测入历史，不起线程

    p.ask_ai('这句话只说一遍')

    assert _count_user(p.chat_history_msgs, '这句话只说一遍') == 1, (
        '历史里出现了多条同样的 user 消息 —— 模型会以为你连说了两遍')


def test_send_choice_records_user_msg_exactly_once(tmp_path):
    """点情感选项路径：_send_choice 不得自己再 append 一次"""
    p = _pet(tmp_path)
    p._run_task = lambda text, images=None: None

    p._send_choice('好呀')

    assert _count_user(p.chat_history_msgs, '好呀') == 1


# ---------- B. 真正发出去的 messages 里也只有一条 ----------
def test_request_payload_has_single_copy(tmp_path, monkeypatch):
    """端到端：抓 _ai_worker 真正发出去的请求体，断言当前消息只出现一次"""
    p = _pet(tmp_path)
    p.chat_history_msgs = [
        {'role': 'user', 'content': '上一句'},
        {'role': 'assistant', 'content': '上一答'},
    ]
    fake = _wire(p, _FakeStream())
    monkeypatch.setattr(dp, 'stream_chat_completions', fake)
    # 用产品入口 ask_ai，但把 _run_task 换成同步执行（不起线程，测完即知）
    p._run_task = lambda text, images=None: p._ai_worker(text, images)

    p.ask_ai('这句只说一遍')

    assert fake.payloads, '没有发出请求，测试自身失效'
    msgs = fake.payloads[0]['messages']
    n = _count_user(msgs, '这句只说一遍')
    assert n == 1, (
        '请求体里当前消息出现 %d 次（应 1 次）—— 这才是「AI 说你发两次」的真因' % n)
    # 顺带确认没有把上一句也搞重复
    assert _count_user(msgs, '上一句') == 1


# ---------- C. 早退路径也不能丢历史 ----------
def test_queued_path_still_records(tmp_path):
    """忙碌 + 排队：消息入历史，并真的进了队列"""
    p = _pet(tmp_path, _ai_busy=True, follow_up_mode='queue')

    p.ask_ai('排队的一句话')

    assert _count_user(p.chat_history_msgs, '排队的一句话') == 1
    assert any(t.get('text') == '排队的一句话' for t in p._task_queue), (
        '排队路径没进队列')


def test_ai_disabled_path_still_records(tmp_path):
    """AI 未配置：仍然记住用户说了什么"""
    p = _pet(tmp_path, ai_enabled=False)

    p.ask_ai('没配 key 时说的话')

    assert _count_user(p.chat_history_msgs, '没配 key 时说的话') == 1


# ---------- D. 源码护栏：防回潮 ----------
def test_single_append_site_in_source():
    """`chat_history_msgs.append({'role': 'user'...})` 全仓只能有一处

    这条是防回潮的：本次 bug 就是「两处都 append + ctx 再追加」叠出来的，
    将来有人图省事在另一个入口再补一句，就会原样复发。
    """
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    n = src.count("chat_history_msgs.append({'role': 'user'")
    assert n == 1, (
        '用户消息入历史出现了 %d 处（应 1 处，位于 ask_ai 开头）' % n)
    # ctx 不得再手工追加当前消息
    assert "[-30:] + [{'role': 'user'" not in src, (
        'ctx 又手工追加当前消息了 —— 这会与历史里的那条重复')
