# -*- coding: utf-8 -*-
"""
tools_executor.py — 工具执行器·纯逻辑层（方案 A 收官）
=======================================================
从 desktop_pet.py 的 _execute_tool 拆出的**无 UI 依赖**工具实现（可独立单测）：
- get_time_str：当前时间
- calculate_expr：安全表达式计算（白名单字符）
- lock_screen_now：锁屏（ctypes）
- query_weather：wttr.in 联网查天气
- parse_choices：offer_choices 选项解析（支持 str / {text, affect}）

复杂工具（open_app/read_file/write_file/edit_own_code/插件/主题等）深度依赖
PetWidget 状态（别名库/文件系统/插件管理器/主题），保留在主文件 _execute_tool。
"""
import datetime
import urllib.parse
import urllib.request


def get_time_str():
    """当前日期时间字符串"""
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def calculate_expr(expr):
    """安全表达式计算：仅允许数字/运算符，非法返回提示"""
    expr = str(expr or '').replace(' ', '')
    if all(ch in '0123456789+-*/().%' for ch in expr):
        try:
            return f'{expr} = {eval(expr)}'
        except Exception:
            return '表达式无法计算'
    return '表达式含非法字符'


def lock_screen_now():
    """锁定 Windows 屏幕"""
    try:
        import ctypes
        ctypes.windll.user32.LockWorkStation()
        return '已锁定屏幕'
    except Exception:
        return '锁屏失败'


def query_weather(city):
    """wttr.in 联网查天气（城市可空，空则返回提示）"""
    if not city:
        return '（未指定城市）'
    try:
        url = f'https://wttr.in/{urllib.parse.quote(city)}?format=3&lang=zh'
        req = urllib.request.Request(url, headers={'User-Agent': 'curl/8.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = resp.read().decode('utf-8').strip()
        if result:
            return f'{city} 的天气：{result}'
        return f'没查到 {city} 的天气'
    except Exception:
        return f'查询 {city} 天气失败（网络异常）'


def parse_choices(raw):
    """offer_choices 选项解析：支持字符串或 {text, affect} 对象，返回 [{text, affect}]"""
    choices = []
    for c in raw or []:
        if isinstance(c, dict):
            t = str(c.get('text') or '').strip()[:20]
            if t:
                choices.append({'text': t, 'affect': c.get('affect') or c.get('affection')})
        else:
            t = str(c).strip()[:20]
            if t:
                choices.append({'text': t, 'affect': None})
    return choices[:3]
