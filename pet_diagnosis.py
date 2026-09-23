# -*- coding: utf-8 -*-
"""pet_diagnosis.py —— 失败归因（L2 v0）

职责：把「异常对象」变成**用户可读的归因结构**（层 / 原因 / 影响 / 下一步）。

边界（微信侧 2026-09-23 89 号所立，必须遵守）：
  ① **只做纯函数**：不读文件 ✗、不出网 ✗（读日志交 `pet_log`、出网交 `pet_net`）
  ② **不得反向 `import desktop_pet`** ✗（与 `pet_anim` 同风格：只被调用、不反向依赖）
  ③ 护栏：本文件出现 `import desktop_pet` / `open(` / 网络请求 即红（见 `tests/test_pet_diagnosis.py`）

v0 说明：先按异常类型做**最小归因**；微信侧的「13 类归因分类表」到齐后只扩 `_MAP` / 追加分支即可（不改变本文件结构）。
"""
from __future__ import annotations

import socket
import urllib.error as _ue
from typing import NamedTuple


class Diag(NamedTuple):
    """归因结构（四段 + 原始错误摘要）"""
    layer: str       # 出在哪一层：网络 / 认证 / 服务端 / 请求 / 模型 / 本地 / 未知
    cause: str       # 原因（人话）
    impact: str      # 影响（用户会看到什么）
    next_step: str   # 下一步（用户能做什么）
    raw: str = ''    # 原始错误摘要（可折叠展示）


# ── 关键词兜底（异常对象信息不足时用；纯字符串判断，不涉 IO）───────────────
_AUTH_HINTS = ('api key', 'apikey', 'unauthorized', 'authentication', '401', '403', 'invalid_api_key')
_RATE_HINTS = ('rate limit', 'too many requests', '429', 'quota')
_NET_HINTS = ('timed out', 'timeout', 'connection refused', 'connection reset',
              'name resolution', 'temporary failure', 'unreachable')
_SERVER_HINTS = ('internal server error', 'bad gateway', 'service unavailable', '502', '503', '504', '500')


def explain_error(exc, *, status=None, detail='', context=''):
    """异常对象 → 四段归因（纯函数）

    :param exc: 捕获到的异常
    :param status: HTTP 状态码（若已知；未给则尝试取 exc.code）
    :param detail: 服务端返回的具体原因（如 DeepSeek error.message），并入 raw
    :param context: 出错时的动作描述（如“流式对话”），并入 cause 前缀
    """
    code = status if status is not None else getattr(exc, 'code', None)
    text = ' '.join(x for x in (str(exc), str(detail)) if x).strip()
    low = text.lower()
    raw = _clip(text or exc.__class__.__name__, 160)
    head = ('%s时：' % context) if context else ''

    # 1) HTTP 状态码优先（HTTPError 是 URLError 子类，必须先判）
    if code is not None:
        try:
            n = int(code)
        except Exception:
            n = 0
        if n in (401, 403):
            return Diag('认证', head + '密钥被拒绝（HTTP %d）' % n,
                        '这一轮没有回答，对话历史已保留',
                        '到「设置 → 模型」检查 API Key 是否有效/是否过期', raw)
        if n == 429:
            return Diag('服务端', head + '请求太频繁被限流（HTTP 429）',
                        '这一轮没有回答',
                        '等几分钟再发一次；若频繁出现可降低重试频率', raw)
        if 500 <= n < 600:
            return Diag('服务端', head + '服务方内部错误（HTTP %d）' % n,
                        '这一轮没有回答，通常是暂时的',
                        '稍等再试；连续多次可看「最近错误」', raw)
        if 400 <= n < 500:
            return Diag('请求', head + '请求被拒绝（HTTP %d）' % n,
                        '这一轮没有回答',
                        '若反复出现，多半是模型名/参数不对，可在设置里更换模型', raw)

    # 2) 超时 / 连不上
    if isinstance(exc, (TimeoutError, socket.timeout)) or any(h in low for h in ('timed out', 'timeout')):
        return Diag('网络', head + '连接超时', '这一轮没有回答',
                    '检查网络或代理；稍后重试', raw)
    if isinstance(exc, (ConnectionError, _ue.URLError)) or any(h in low for h in _NET_HINTS):
        return Diag('网络', head + '连不上服务端', '这一轮没有回答',
                    '检查网络/代理是否可用，再重试', raw)

    # 3) 关键词兜底（异常对象没带状态码时）
    if any(h in low for h in _AUTH_HINTS):
        return Diag('认证', head + '密钥校验没过', '这一轮没有回答',
                    '到「设置 → 模型」检查 API Key', raw)
    if any(h in low for h in _RATE_HINTS):
        return Diag('服务端', head + '被限流', '这一轮没有回答', '等几分钟再试', raw)
    if any(h in low for h in _SERVER_HINTS):
        return Diag('服务端', head + '服务方错误', '这一轮没有回答', '稍后重试', raw)

    # 4) 未知：如实说“不知道”，并给出可行动的下一步
    return Diag('未知', head + '遇到没见过的错误', '这一轮没有回答',
                '这条会记进审计；把「原始错误」发我即可定位', raw)


def to_card(diag: Diag) -> str:
    """归因结构 → 用户可读的失败卡片文本（一行标题 + 三段明细 + 可选原始错误）"""
    lines = [
        '❌ 这一轮没答上：%s' % diag.cause,
        '　· 出在哪：%s' % diag.layer,
        '　· 影响：%s' % diag.impact,
        '　· 下一步：%s' % diag.next_step,
    ]
    if diag.raw:
        lines.append('　· 原始错误：%s' % diag.raw)
    return '\n'.join(lines)


def _clip(s: str, n: int) -> str:
    s = (s or '').replace('\n', ' ').strip()
    return s if len(s) <= n else s[:n] + '…'
