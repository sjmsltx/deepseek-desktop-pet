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
import platform_layer as pl  # v6.73 批次3：平台能力统一门面
import ast
import datetime
import operator
import urllib.parse
import urllib.request


def get_time_str():
    """当前日期时间字符串"""
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


# 安全表达式求值：AST 白名单（替换原 eval 实现）
# 背景（2026-09-12 安全审查）：原实现虽做了字符白名单，但 9**9**9 这类幂塔
# 会让进程算到卡死在 eval 里（无长度/幂次限制），且此处根本不需要 eval。
_ALLOWED_BIN = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_ALLOWED_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_MAX_EXPR_LEN = 200     # 表达式长度上限
_MAX_POW = 64           # 幂指数上限（防 9**9**9 幂塔卡死）
_MAX_BITS = 16000       # 结果位宽上限（约 4800 位十进制）


def _eval_node(node):
    """按白名单递归求值；出现任何白名单外语法直接抛 ValueError"""
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError('仅支持数字')
        return node.value
    if isinstance(node, ast.UnaryOp):
        op = _ALLOWED_UNARY.get(type(node.op))
        if op is None:
            raise ValueError('不支持的运算符')
        return op(_eval_node(node.operand))
    if isinstance(node, ast.BinOp):
        op = _ALLOWED_BIN.get(type(node.op))
        if op is None:
            raise ValueError('不支持的运算符')
        left, right = _eval_node(node.left), _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and (abs(right) > _MAX_POW or abs(left) > 10 ** 6):
            raise ValueError('幂运算过大')
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and right == 0:
            raise ValueError('除数不能为 0')
        return op(left, right)
    raise ValueError('表达式含不支持的语法')


def calculate_expr(expr):
    """安全表达式计算：AST 白名单求值 + 长度/幂次/位宽上限"""
    text = str(expr or '').strip()
    if not text:
        return '表达式为空'
    if len(text) > _MAX_EXPR_LEN:
        return f'表达式过长（上限 {_MAX_EXPR_LEN} 字符）'
    try:
        tree = ast.parse(text, mode='eval')
    except SyntaxError:
        return '表达式无法解析'
    try:
        value = _eval_node(tree)
    except ValueError as e:
        return f'表达式无法计算（{e}）'
    except ZeroDivisionError:
        return '表达式无法计算（除数不能为 0）'
    except Exception:
        return '表达式无法计算'
    if isinstance(value, int) and value.bit_length() > _MAX_BITS:
        return '计算结果过大'
    if isinstance(value, float) and (value != value or value in (float('inf'), float('-inf'))):
        return '计算结果无效'
    return f'{text} = {value}'


def lock_screen_now():
    """锁定 Windows 屏幕"""
    try:
        import ctypes
        pl.lock_screen()
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
