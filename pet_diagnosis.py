# -*- coding: utf-8 -*-
"""pet_diagnosis.py —— 失败归因（L2 v1-A）

职责：把「异常对象」变成**用户可读的归因结构**（层 / 原因 / 影响 / 下一步）。

边界（微信侧 2026-09-23 89 号所立，必须遵守）：
  ① **只做纯函数**：不读文件 ✗、不出网 ✗（读日志交 `pet_log`、出网交 `pet_net`）
  ② **不得反向 `import desktop_pet`** ✗（与 `pet_anim` 同风格：只被调用、不反向依赖）
  ③ 护栏：本文件出现 `import desktop_pet` / `open(` / 网络请求 即红（见 `tests/test_pet_diagnosis.py`）

v1-A（2026-09-24）：层名与微信侧《13 类归因分类表》**逐字对齐**（共用同一套归因 ✗ 不两套 ✓）。
本批落 **10 类 + 未知兜底**：本地网络 · 上游限流 · 上游故障 · 上游超时 · 流中断 · 鉴权 ·
请求错误 · 额度 · 内容安全 · 未知。
v1-B（下一批）落剩 3 类：**本地闸门 · 工具失败 · 本地异常**（**都要接线到调用点** ✗，
且「本地异常」须先定“用户可感知白名单” ✓ —— 实测 `_silent_log` 有 **76 处** ✗ 全量出卡片会刷屏）。
「上游公告」属 L3（`pet_net.probe_status()` ✓），不进 `explain_error` ✗。
"""
from __future__ import annotations

import socket
import urllib.error as _ue
from typing import NamedTuple


class Diag(NamedTuple):
    """归因结构（四段 + 原始错误摘要）"""
    layer: str       # 层（与 13 类表逐字一致）
    cause: str       # 原因（人话）
    impact: str      # 影响（用户会看到什么）
    next_step: str   # 下一步（用户能做什么）
    raw: str = ''    # 原始错误摘要（可折叠展示；裸技术码只允许出现在这里）


# ── 关键词（纯字符串判断，不涉 IO）──────────────────────────────────────
_AUTH_HINTS = ('api key', 'apikey', 'unauthorized', 'authentication', 'invalid_api_key')
_RATE_HINTS = ('rate limit', 'too many requests', '429')
_NET_HINTS = ('connection refused', 'connection reset', 'name resolution',
              'temporary failure', 'unreachable', 'no route to host')
_SERVER_HINTS = ('internal server error', 'bad gateway', 'service unavailable')
_QUOTA_HINTS = ('余额不足', '额度不足', '欠费', 'insufficient balance', 'insufficient_quota',
                'billing', 'payment required')
_SAFETY_HINTS = ('内容审核', '审核不通过', '违规', '风险内容', 'content policy', 'safety', 'flagged')
_TIMEOUT_HINTS = ('timed out', 'timeout')


def explain_error(exc, *, status=None, detail='', context='', phase=None):
    """异常对象 → 四段归因（纯函数）

    :param exc: 捕获到的异常
    :param status: HTTP 状态码（若已知；未给则尝试取 exc.code）
    :param detail: 服务端返回的具体原因（如 DeepSeek error.message），并入 raw
    :param context: 出错时的动作描述（如“对话”），并入 cause 前缀
    :param phase: 出错阶段：``'connecting'``（还没建连）/ ``'streaming'``（已发出请求、在等数据）/ ``None``

    ⭐ 为什么需要 ``phase``（v1-A 的一处**边界修正**）：**同样是 timeout** ——
    建连阶段失败 = **本地网络**（类 1）✓；已发出请求后的读超时 = **上游超时**（类 4）✓。
    不区分就会撞在一起、把“上游不吐数据”误归成“你的网络不行”✗。
    """
    code = status if status is not None else getattr(exc, 'code', None)
    text = ' '.join(x for x in (str(exc), str(detail)) if x).strip()
    low = text.lower()
    raw = _clip(text or exc.__class__.__name__, 160)
    head = ('%s时：' % context) if context else ''
    name = type(exc).__name__

    # 1) HTTP 状态码优先（HTTPError 是 URLError 子类，必须先判）
    if code is not None:
        try:
            n = int(code)
        except Exception:
            n = 0
        if n in (401, 403):
            return Diag('鉴权', head + '密钥被拒绝', '这一轮没有回答，对话历史已保留',
                        '到「设置 → 模型」检查 API Key 是否有效/是否过期', raw)
        if n == 429:
            return Diag('上游限流', head + '请求太频繁被限流', '这一轮没有回答',
                        '等 1 分钟再发；频繁出现就降低重试频率', raw)
        if n == 402 or any(h in low for h in _QUOTA_HINTS):
            return Diag('额度', head + '账户额度不足', '这一轮没有回答',
                        '去「设置 → 用量与计费」查余额或充值', raw)
        if 500 <= n < 600:
            return Diag('上游故障', head + '上游服务故障（不是你的问题）',
                        '这一轮没有回答，通常是暂时的', '稍等再发；连续多次去「最近错误」看看', raw)
        if 400 <= n < 500:
            return Diag('请求错误', head + '请求被拒绝', '这一轮没有回答',
                        '多半是模型名/参数不对 → 去「设置 → 模型」确认', raw)

    # 2) 额度 / 内容安全（SSE error 里带关键词的，**必须先于“流中断”判** ✓）
    if any(h in low for h in _QUOTA_HINTS):
        return Diag('额度', head + '账户额度不足', '这一轮没有回答',
                    '去「设置 → 用量与计费」查余额或充值', raw)
    if any(h in low for h in _SAFETY_HINTS):
        return Diag('内容安全', head + '被上游安全策略拦下（不是故障）', '这一轮没有回答',
                    '换个说法再试一次', raw)

    # 3) 流中断（不 import deepseek_client：保持纯函数，只认类名字符串 ✓）
    if name == 'StreamInterrupted':
        return Diag('流中断', head + '回复被中断（上游断开）', '已收到的内容保留',
                    '再发一次继续', raw)
    if name == 'StreamError':
        # 通用 SSE 错误（额度/安全已在前一步被截走）→ 当“上游断开”处理
        return Diag('流中断', head + '回复被中断（上游断开）', '已收到的内容保留',
                    '再发一次继续', raw)

    # 4) 超时：按阶段分「本地网络」vs「上游超时」（v1-A 边界修正 ✓）
    _is_timeout = isinstance(exc, (TimeoutError, socket.timeout)) or any(h in low for h in _TIMEOUT_HINTS)
    if _is_timeout and phase == 'streaming':
        return Diag('上游超时', head + '上游长时间没响应', '已等到超时后放弃本轮',
                    '重发；多次如此可换成更快的模型', raw)
    if _is_timeout:
        return Diag('本地网络', head + '连接超时（不是上游的问题）', '这一轮没有回答',
                    '检查网络或代理是否可用，再重发', raw)
    if isinstance(exc, (ConnectionError, _ue.URLError)) or any(h in low for h in _NET_HINTS):
        return Diag('本地网络', head + '连不上服务端', '这一轮没有回答',
                    '检查网络/代理是否可用，再重发', raw)

    # 5) 关键词兜底（异常对象没带状态码时）
    if any(h in low for h in _AUTH_HINTS):
        return Diag('鉴权', head + '密钥校验没过', '这一轮没有回答，对话历史已保留',
                    '到「设置 → 模型」检查 API Key', raw)
    if any(h in low for h in _RATE_HINTS):
        return Diag('上游限流', head + '被限流', '这一轮没有回答', '等 1 分钟再发', raw)
    if any(h in low for h in _SERVER_HINTS):
        return Diag('上游故障', head + '上游服务故障（不是你的问题）', '这一轮没有回答',
                    '稍等再发', raw)

    # 6) 未知：如实说“未知”，并给可行动的下一步（不编原因 ✗）
    return Diag('未知', head + '遇到没见过的错误', '这一轮没有回答',
                '这条会记进审计；把「原始错误」复制发我即可定位', raw)


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
