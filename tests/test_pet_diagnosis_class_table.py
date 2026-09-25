# -*- coding: utf-8 -*-
"""L2 归因分类表护栏（护栏①静态 + ②③④动态）

与微信侧《13 类归因分类表》逐字对齐（2026-09-24 WX-桌宠-01）。
护栏① **用 AST 抽 `Diag(...)` 的 layer 字面量** ✗ —— 不用 grep 层名（会命中 docstring/注释 = 假红 ✓）
护栏②③④ 用**参数化行为测试**：每类一个触发样本 → 四段非空 / 无裸 HTTP 码 / 鉴权声明已保留历史
"""
from __future__ import annotations

import ast
import io
import socket
import urllib.error as ue
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MOD = ROOT / "pet_diagnosis.py"

# ── 表（与微信侧 13 类表逐行对应；in_explain_error=False 表示归 L3、不进本模块）──────
CLASS_TABLE = [
    ("本地网络", True),
    ("上游限流", True),
    ("上游故障", True),
    ("上游超时", True),
    ("流中断", True),
    ("鉴权", True),
    ("请求错误", True),
    ("额度", True),
    ("本地闸门", True),   # v1-B：经 gate_diag() 入口（成本闸门是 emit、不 raise ✓）
    ("内容安全", True),
    ("工具失败", True),   # v1-B：经 tool_diag() 入口（工具执行异常 ✓）
    ("本地异常", True),   # v1-B：经 local_diag() 入口（用户可感知白名单 = 显式标记 ✓）
    ("上游公告", False),   # L3（pet_net.probe_status），不进 explain_error
    ("未知", True),        # 兜底
]


def _load():
    import importlib.util
    spec = importlib.util.spec_from_file_location("pet_diagnosis_under_test", MOD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _layers_in_code() -> set:
    """AST 抽 `return Diag('<layer>', ...)` 的第一个位置参数字面量（含 return 与直接 return）。"""
    tree = ast.parse(io.open(MOD, encoding="utf-8").read())
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        fname = getattr(func, "id", None) or getattr(func, "attr", None)
        if fname != "Diag" or not node.args:
            continue
        a0 = node.args[0]
        if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
            out.add(a0.value)
    return out


# ── 护栏①：13 类每一类都必须在代码里有可达分支（漏一类即红）──────────────
def test_class_table_covered_by_code():
    """护栏①（静态）：表 ↔ 代码**双向**比对，差集非空即红。"""
    want = {name for name, in_mod in CLASS_TABLE if in_mod}
    have = _layers_in_code()
    missing_in_code = sorted(want - have)
    extra_in_code = sorted(have - want)
    assert not missing_in_code, f"表里有、代码里没有分支（漏写）✗：{missing_in_code}"
    assert not extra_in_code, f"代码里有、表里没登记（漏登记）✗：{extra_in_code}"


# ── 护栏②③④：参数化行为（每类一个触发样本）──────────────────────────
def _exc_arg(kind: str):
    """构造该类的触发样本（返回 (exc, kwargs)）"""
    if kind == "本地网络":
        return ConnectionError('Connection refused'), {}
    if kind == "上游限流":
        return ue.HTTPError('https://x', 429, 'Too Many Requests', {}, None), {}
    if kind == "上游故障":
        return ue.HTTPError('https://x', 503, 'Service Unavailable', {}, None), {}
    if kind == "上游超时":
        return socket.timeout('timed out'), {'phase': 'streaming'}
    if kind == "流中断":
        return type('StreamInterrupted', (RuntimeError,), {})('stream cut'), {}
    if kind == "鉴权":
        return ue.HTTPError('https://x', 401, 'Unauthorized', {}, None), {}
    if kind == "请求错误":
        return ue.HTTPError('https://x', 400, 'Bad Request', {}, None), {}
    if kind == "额度":
        return RuntimeError('insufficient balance'), {}
    if kind == "内容安全":
        return RuntimeError('内容审核不通过'), {}
    if kind == "未知":
        return RuntimeError('something weird'), {}
    return None, None


@pytest.mark.parametrize("layer,in_mod", CLASS_TABLE)
def test_each_class_samples(layer, in_mod):
    """护栏②③④：每一类都必须有可达样本 → 四段非空、正文无裸 HTTP 码、鉴权声明历史已保留。

    v1-B：本地闸门 / 工具失败 / 本地异常走**专用工厂入口**（不在 explain_error 里 ✓）
    """
    if layer == "上游公告":
        pytest.skip("上游公告 属 L3（pet_net.probe_status），不进 explain_error")
    m = _load()
    if layer == "本地闸门":
        d = m.gate_diag('日成本上限已用尽')
    elif layer == "工具失败":
        d = m.tool_diag('_smart_open', ValueError('bad path'))
    elif layer == "本地异常":
        d = m.local_diag(KeyError('missing'), context='_save_position')
    else:
        exc, kw = _exc_arg(layer)
        assert exc is not None, f"{layer} 缺触发样本"
        d = m.explain_error(exc, **kw)
    assert d.layer == layer, f"{layer} 样本被归成了 {d.layer}"
    # ② 四段任一为空即红
    for field in ("layer", "cause", "impact", "next_step"):
        assert str(getattr(d, field)).strip(), f"{layer} 的 {field} 为空"
    # ③ 四段正文不得出现裸 HTTP 码（只允许在 raw 里）
    body = "%s %s %s" % (d.cause, d.impact, d.next_step)
    assert not __import__('re').search(r"HTTP\s*\d{3}|\b[45]\d\d\b", body), \
        f"{layer} 正文出现裸技术码：{body}"
    # ④ 鉴权类必须声明“对话历史已保留”
    if layer == "鉴权":
        assert "对话历史已保留" in d.impact


def test_quota_and_safety_are_not_swallowed_by_stream_error():
    """顺序护栏：额度/内容安全的 SSE 错误，不得被“流中断”吃掉 ✗"""
    m = _load()
    StreamError = type('StreamError', (RuntimeError,), {})
    d1 = m.explain_error(StreamError('insufficient_quota'))
    d2 = m.explain_error(StreamError('content policy violation'))
    assert d1.layer == '额度', d1.layer
    assert d2.layer == '内容安全', d2.layer
