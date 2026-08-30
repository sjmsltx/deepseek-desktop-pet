# -*- coding: utf-8 -*-
"""
care_engine.py — 主动关心引擎·网络与判断层（P3 模块化拆分）
============================================================
从 desktop_pet.py 拆出的主动关心逻辑（无 UI 依赖）：
- user_idle_minutes：用户空闲分钟数（GetLastInputInfo，纯 ctypes）
- judge_wakeup：链式唤醒判断（轻量请求 AI 决定是否主动 + 下次唤醒间隔）
- followup_message：回访关心消息生成（带状态感知）

模块化说明：网络 + JSON 解析逻辑；API 用量记录通过 record_cb 回调注入。
"""
import datetime
import json
import re
import urllib.request

API_URL = 'https://api.deepseek.com/chat/completions'


def user_idle_minutes():
    """用户空闲分钟数（GetLastInputInfo，纯 ctypes）"""
    try:
        import ctypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [('cbSize', ctypes.c_uint), ('dwTime', ctypes.c_uint)]

        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
        millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
        return millis / 60000.0
    except Exception:
        return 0.0


def judge_wakeup(api_key, model, state, char_name, record_cb=None):
    """链式唤醒判断：轻量请求 AI 决定 是否主动找用户 + 下次唤醒间隔（独立上下文，不污染主对话）。
    返回解析后的 JSON dict，失败返回 None。"""
    try:
        prompt = (f'{state}。你是桌宠{char_name}。请判断现在要不要主动找用户说句话。'
                  f'规则：用户空闲超过30分钟、或深夜(23:00-8:00)、或用户明显在忙时不打扰；'
                  f'如果最近有值得关心的事（未完成的话题/重要事件）可以主动。'
                  f'只返回 JSON：{{"act":"yes"或"no","message":"要说话时的1-2句自然关心语(act=yes时)","next_minutes":下次唤醒间隔分钟数(10-360)}}')
        data = json.dumps({'model': model,
                           'messages': [{'role': 'user', 'content': prompt}], 'max_tokens': 200}).encode()
        req = urllib.request.Request(API_URL, data=data,
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'})
        with urllib.request.urlopen(req, timeout=25) as resp:
            r = json.loads(resp.read().decode())
        if record_cb:
            record_cb(r)
        content = (r['choices'][0]['message'].get('content') or '')
        m = re.search(r'\{[^{}]*\}', content, re.S)
        if m:
            return json.loads(m.group(0))
    except Exception:
        pass
    return None


def followup_message(api_key, model, state, topic, char_name, record_cb=None):
    """回访机制：对话中安排的回访到点 → 主动生成关心消息（带状态感知 v6.18）。返回消息文本或 None。"""
    try:
        prompt = (f'{state}。用户之前提到：{topic}。作为{char_name}，'
                  f'现在按约定主动关心一下，1-2句话，自然不刻意。'
                  f'根据状态调整语气：用户空闲超过60分钟→体谅/不催促（可能不在或很忙）；'
                  f'空闲不到10分钟→语气可以亲近自然。可带[emotion:xxx]。')
        data = json.dumps({'model': model,
                           'messages': [{'role': 'user', 'content': prompt}], 'max_tokens': 150}).encode()
        req = urllib.request.Request(API_URL, data=data,
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'})
        with urllib.request.urlopen(req, timeout=25) as resp:
            r = json.loads(resp.read().decode())
        if record_cb:
            record_cb(r)
        return (r['choices'][0]['message'].get('content') or '').strip() or None
    except Exception:
        return None
