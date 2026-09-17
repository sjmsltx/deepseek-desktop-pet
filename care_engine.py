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
import random
import urllib.request

from model_registry import DEFAULT_ENDPOINT

# 全项目唯一的接口地址默认值定义在 model_registry；实际请求地址由调用方从模型档案传入。
API_URL = DEFAULT_ENDPOINT

from pet_log import get_logger  # noqa: E402

_log = get_logger('care_engine')


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


def judge_wakeup(api_key, model, state, char_name, record_cb=None, endpoint=None, busy_hint=None):
    """链式唤醒判断：轻量请求 AI 决定 是否主动找用户 + 下次唤醒间隔（独立上下文，不污染主对话）。
    返回解析后的 JSON dict，失败返回 None。endpoint 为 None 时用模块默认地址。

    busy_hint（v6.59，可选）：前台程序信号，形如「当前前台程序：zoom.exe（会议 / 通话）。」。
    默认 None —— 不传时行为与旧版完全一致（向后兼容）。只包含程序名与类别，
    不含窗口标题、不含路径（由 pet_foreground 保证）。
    """
    try:
        prompt = (f'{state}。你是桌宠{char_name}。请判断现在要不要主动找用户说句话。'
                  f'规则：用户空闲超过30分钟、或深夜(23:00-8:00)、或用户明显在忙时不打扰；'
                  f'如果最近有值得关心的事（未完成的话题/重要事件）可以主动。')
        if busy_hint:
            prompt += (f'前台程序信号：{busy_hint}'
                       f'对该信号的额外规则：若属于会议/通话、游戏、视频播放 → 视为高度专注，'
                       f'默认不打扰（act=no）；若属于写代码/设计或文档办公 → 可以打扰，但 message '
                       f'必须更短更轻；若属于浏览器/终端/其他 → 忽略此信号，按原规则判断。')
        prompt += ('只返回 JSON：{"act":"yes"或"no","message":"要说话时的1-2句自然关心语(act=yes时)",'
                   '"next_minutes":下次唤醒间隔分钟数(10-360)}')
        data = json.dumps({'model': model,
                           'messages': [{'role': 'user', 'content': prompt}], 'max_tokens': 200}).encode()
        req = urllib.request.Request(endpoint or API_URL, data=data,
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'})
        with urllib.request.urlopen(req, timeout=25) as resp:
            r = json.loads(resp.read().decode())
        if record_cb:
            record_cb(r)
        content = (r['choices'][0]['message'].get('content') or '')
        m = re.search(r'\{[^{}]*\}', content, re.S)
        if m:
            return json.loads(m.group(0))
    except Exception as e:
        _log.debug('唤醒判定返回内容无法解析为 JSON（按不唤醒处理）：%s', e)
    return None


# ============ v6.60 批 4：无 AI 时的关心措辞库（多样化，避免固定模板句） ============
# 背景：此前兜底只有 4 句固定台词（“该喝水啦～”等），重复出现时非常人机。
# 这里按意图分组，每种 6 句；调用方负责避免与上一条重复（见 desktop_pet._pick_care_line）。
_FALLBACK = {
    'zh': {
        'rest': ['坐挺久了吧，起来伸个懒腰？', '要不要站起来走走？我等你回来。',
                 '转一下脖子吧，别僵住了。', '眼睛离屏幕远一点，歇一小会儿？',
                 '手边有水吗？喝两口再继续。', '忙了这么久，给自己两分钟放空吧。'],
        'chat': ['我在呢，想聊两句随时说。', '刚想到个事——你最近有想做的事吗？',
                 '随便问一句，今天过得怎么样？', '窗外什么天气？我猜你没往外面看。',
                 '还在忙呀？随手记的东西别忘了。', '需要我做点什么随时叫我。'],
        'care': ['有点安静，过来看看你还在不在。', '你那边还好吗？不用回我。',
                 '我就看一眼，你继续忙。', '在写什么重要的东西吗？加油。',
                 '别忘了起来动动。', '手头这件事快完成了吧？'],
    },
    'en': {
        'rest': ['Been sitting a while — stretch?', 'Take a short walk, I will wait.',
                 'Roll your shoulders a bit.', 'Look away from the screen for a moment?',
                 'Water nearby? Take a sip.', 'Busy long enough — give yourself two minutes.'],
        'chat': ['I am here if you want to chat.', 'Random question: anything you look forward to?',
                 'How is today going so far?', 'What is the weather like out there?',
                 'Still busy? Do not forget your notes.', 'Call me if you need anything.'],
        'care': ['Just dropping by to check you are around.', 'No reply needed, hope you are fine.',
                 'Just a peek, carry on.', 'Writing something important? Keep going.',
                 'Remember to move a bit.', 'That task is nearly done, right?'],
    },
}


def fallback_lines(lang='zh', kind='all'):
    """无 AI 时的关心措辞库（v6.60 批 4）

    lang: 'zh' / 'en'；kind: 'rest' / 'chat' / 'care' / 'all'
    返回去重后的句子列表（不会为空：未知语言回退 zh）。
    """
    table = _FALLBACK.get(lang) or _FALLBACK['zh']
    if kind == 'all':
        out = []
        for k in ('care', 'rest', 'chat'):
            out.extend(table.get(k, []))
        return out
    return list(table.get(kind) or table.get('care') or [])


def pick_fallback(lang='zh', kind='care', last=''):
    """挑一句不重复的兜底措辞（与上一条不同；库很小时允许回退）"""
    lines = fallback_lines(lang, kind)
    pool = [l for l in lines if l != last] or lines
    return random.choice(pool) if pool else ''


def followup_message(api_key, model, state, topic, char_name, record_cb=None, endpoint=None):
    """回访机制：对话中安排的回访到点 → 主动生成关心消息（带状态感知 v6.18）。返回消息文本或 None。"""
    try:
        prompt = (f'{state}。用户之前提到：{topic}。作为{char_name}，'
                  f'现在按约定主动关心一下，1-2句话，自然不刻意。'
                  f'根据状态调整语气：用户空闲超过60分钟→体谅/不催促（可能不在或很忙）；'
                  f'空闲不到10分钟→语气可以亲近自然。可带[emotion:xxx]。')
        data = json.dumps({'model': model,
                           'messages': [{'role': 'user', 'content': prompt}], 'max_tokens': 150}).encode()
        req = urllib.request.Request(endpoint or API_URL, data=data,
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'})
        with urllib.request.urlopen(req, timeout=25) as resp:
            r = json.loads(resp.read().decode())
        if record_cb:
            record_cb(r)
        return (r['choices'][0]['message'].get('content') or '').strip() or None
    except Exception as e:
        _log.warning('回访消息生成失败（本轮跳过关心）：%s', e)
        return None
