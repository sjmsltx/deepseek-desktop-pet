# -*- coding: utf-8 -*-
"""L2 v0 护栏：`pet_diagnosis` 是纯函数模块 + 四段归因分类正确 + 卡片可读

范本：tests/test_foreground_privacy.py（只扫源码 / 不依赖运行环境 / 独立可回退）
边界（微信侧 2026-09-23 89 号）：① 只做纯函数（不读文件、不出网）② 不得反向 import desktop_pet
"""
from __future__ import annotations

import ast
import io
import re
import socket
import urllib.error as ue
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def src() -> str:
    return io.open(ROOT / "pet_diagnosis.py", encoding="utf-8").read()


def _strip_docstrings_and_comments(src_text: str) -> str:
    """用 AST 精确剔掉模块/类/函数 docstring，再去掉纯注释行。

    为什么不用「按行看有没有三引号」：多行 docstring 只有首尾行带三引号，
    中间行会被当代码 → 护栏把「文档里写的规则」判成违规（假红，和假绿一样消耗信任）。
    """
    lines = src_text.splitlines()
    try:
        tree = ast.parse(src_text)
    except SyntaxError:
        return src_text
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant) \
                and isinstance(first.value.value, str):
            for i in range(first.lineno - 1, getattr(first, "end_lineno", first.lineno)):
                if 0 <= i < len(lines):
                    lines[i] = ""
    return "\n".join(l for l in lines if not l.strip().startswith("#"))


def _diag():
    """按路径加载 pet_diagnosis（不 import 产品模块，避免拉起 Qt 依赖）。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("pet_diagnosis_under_test", ROOT / "pet_diagnosis.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 1. 模块卫生：禁反向依赖、禁 IO、禁网络请求 ──────────────────────────
def test_module_hygiene_no_reverse_import_and_no_io():
    """pet_diagnosis 只做纯函数：不得 import desktop_pet、不得 open()/读写文件、不得发网络请求。"""
    body = _strip_docstrings_and_comments(src())
    forbidden = {
        "反向 import desktop_pet": r"^\s*(?:import|from)\s+desktop_pet",
        "文件读写 open(": r"\bopen\s*\(",
        "requests 库": r"\bimport\s+requests\b|\brequests\.",
        "网络请求 urlopen/urlretrieve/http.client": r"\burlopen\b|\burlretrieve\b|http\.client|requests\.(get|post)",
    }
    bad = [name for name, pat in forbidden.items() if re.search(pat, body, re.M)]
    assert not bad, f"pet_diagnosis 违反纯函数边界：{bad}"


# ── 2. 归因分类（v0：六类，覆盖用户最常见失败）────────────────────────
def test_http_401_is_auth_layer():
    err = ue.HTTPError('https://x', 401, 'Unauthorized', {}, None)
    d = _diag().explain_error(err)
    assert d.layer == '鉴权' and 'Key' in d.next_step


def test_http_429_is_rate_limited():
    err = ue.HTTPError('https://x', 429, 'Too Many Requests', {}, None)
    d = _diag().explain_error(err)
    assert d.layer == '上游限流' and '限流' in d.cause


def test_http_500_is_server_side():
    err = ue.HTTPError('https://x', 500, 'Internal Server Error', {}, None)
    d = _diag().explain_error(err)
    assert d.layer == '上游故障'


def test_timeout_is_local_network_by_default():
    """未给 phase 时：超时按 v0 语义归「本地网络」（建连阶段）✓"""
    d = _diag().explain_error(socket.timeout('timed out'))
    assert d.layer == '本地网络' and '超时' in d.cause


def test_timeout_during_streaming_is_upstream_timeout():
    """⭐ v1-A 边界修正：已发出请求后的读超时 → 「上游超时」✗（不是“你的网络不行”✗）"""
    d = _diag().explain_error(socket.timeout('timed out'), phase='streaming')
    assert d.layer == '上游超时'


def test_connection_error_is_local_network():
    d = _diag().explain_error(ConnectionError('connection refused'))
    assert d.layer == '本地网络'


def test_unknown_error_says_unknown_not_guess():
    """未知错误必须如实说「未知」并给可行动作（不许编原因）。"""
    d = _diag().explain_error(RuntimeError('something weird'))
    assert d.layer == '未知' and d.next_step


# ── 3. 卡片：四段齐全、含原始错误摘要 ────────────────────────────────
def test_card_has_four_sections_and_raw():
    m = _diag()
    d = m.explain_error(ue.HTTPError('https://x', 401, 'Unauthorized', {}, None),
                        detail='invalid api key provided')
    card = m.to_card(d)
    for key in ('❌ 这一轮没答上：', '出在哪：', '影响：', '下一步：', '原始错误：'):
        assert key in card, f'失败卡片缺少「{key}」'
    assert 'invalid api key' in card


# ── 4. 参数与兜底路径 ──────────────────────────────────────────────
def test_context_prefix_is_used():
    d = _diag().explain_error(socket.timeout('timed out'), context='对话')
    assert d.cause.startswith('对话')


def test_status_param_overrides_exception_code():
    d = _diag().explain_error(RuntimeError('boom'), status=403)
    assert d.layer == '鉴权'
