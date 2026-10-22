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
v1-B（2026-09-25）：落剩下的 **3 类**——本地闸门 · 工具失败 · 本地异常 ✓（经下三个工厂入口，
仍为纯函数、不涉 IO ✓）。加上 L3 的「上游公告」（由 `pet_net.probe_status()` 提前告知 ✓）
合计 **13 类**，与微信侧表一致 ✓。
"""
from __future__ import annotations

import re
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
            # 批 B（缺陷 4）：⭐ 明确这是**账户级**余额（共享 ✗）不是桌宠专属 ✓
            return Diag('额度', head + '账户余额不足（含其他项目消费）', '这一轮没有回答',
                        '到「设置 → 用量与计费」查账户余额（该账户可能被其它项目共用 ✗）或充值', raw)
        if 500 <= n < 600:
            return Diag('上游故障', head + '上游服务故障（不是你的问题）',
                        '这一轮没有回答，通常是暂时的', '稍等再发；连续多次去「最近错误」看看', raw)
        if 400 <= n < 500:
            return Diag('请求错误', head + '请求被拒绝', '这一轮没有回答',
                        '多半是模型名/参数不对 → 去「设置 → 模型」确认', raw)

    # 2) 额度 / 内容安全（SSE error 里带关键词的，**必须先于“流中断”判** ✓）
    if any(h in low for h in _QUOTA_HINTS):
        return Diag('额度', head + '账户余额不足（含其他项目消费）', '这一轮没有回答',
                    '到「设置 → 用量与计费」查账户余额（该账户可能被其它项目共用 ✗）或充值', raw)
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


# ── L4-1：最近错误（**纯函数** ✓ 不读文件、不出网 ✗；读审计交 governance.read_recent ✓）──
ERROR_KINDS = ('error', 'deny')          # 判错类：error（失败）/ deny（拒绝）
_LAYER_RX = re.compile(r'层=([^｜|]+)')

# 13 类归因层名（与微信侧表逐字一致 ✓）—— 用于：独立出现的层名段在摘要里**去掉** ✓
LAYERS = ('本地网络', '上游限流', '上游故障', '上游超时', '流中断', '鉴权', '请求错误',
          '额度', '本地闸门', '内容安全', '工具失败', '本地异常', '上游公告', '未知')


def _summary_of(detail, kind=''):
    """从 detail 提取摘要：去掉 `层=xxx` 段、空段、**独立层名段**（如 `未知 ｜`）✓

    修复（微信侧 2026-09-25 指出）：原文案拼接后摘要会残留 `未知   原因` 这类引导词 ✗
    """
    parts = []
    for seg in str(detail or '').split('｜'):
        s = seg.strip()
        if not s or s.startswith('层=') or s in LAYERS:
            continue                       # 无信息量段 → 去掉 ✓
        parts.append(s)
    joined = ' '.join(parts).strip()
    return joined or (str(kind or '') or '（无摘要）')


def recent_errors(records, *, limit=20, layer=None):
    """把**审计记录**整理成「最近错误」列表（纯函数 ✓）。

    输出每条字段固定（**字段齐** ✓）：``{'time','kind','actor','action','layer','summary','allowed'}``

    - 只保留判错类：``kind ∈ ERROR_KINDS`` **或** ``allowed is False`` ✓
    - **新 → 旧**（倒序 ✓，按时间排；无时间字段的按输入顺序稳定保留 ✓）
    - ``limit`` 为**条数上限** ✓（≤0 视为默认 20）
    - ``layer`` 非空时只留该层（层名与 13 类表**逐字一致** ✓）
    - 坏记录（非 dict / 缺字段 / 类型异常）**跳过不炸** ✓
    """
    lim = int(limit) if isinstance(limit, (int, float)) and int(limit) > 0 else 20
    rows = []
    for idx, r in enumerate(records or []):
        if not isinstance(r, dict):
            continue
        try:
            kind = str(r.get('kind', '') or '')
            allowed = r.get('allowed', True)
            if kind not in ERROR_KINDS and allowed is not False:
                continue
            detail = str(r.get('detail', '') or '')
            m = _LAYER_RX.search(detail)
            lay = m.group(1).strip() if m else ''
            if layer and lay != str(layer):
                continue
            summary = _summary_of(detail, kind)
            rows.append({
                'time': str(r.get('ts', '') or r.get('time', '') or ''),
                'kind': kind,
                'actor': str(r.get('actor', '') or ''),
                'action': str(r.get('action', '') or ''),
                'layer': lay or '未知',
                'summary': _clip(summary, 120),
                'allowed': bool(allowed),
                '_i': idx,
            })
        except Exception:
            continue                       # 坏记录跳过不炸 ✓
    rows.sort(key=lambda x: (x['time'], -x['_i']), reverse=True)   # 新→旧 ✓
    for r in rows:
        r.pop('_i', None)
    return rows[:lim]


def gate_diag(reason='', *, detail=''):
    """本地闸门（类 9）：被**本地**策略拦下（日成本上限 / 额度上限）——不是故障 ✓

    与“上游限流/额度”区别：那两个是**上游拒绝** ✓；这个是**我方自己未发出调用** ✗。
    """
    cause = ('本轮被本地成本闸门暂停（不是故障）' if not reason else str(reason))
    return Diag('本地闸门', cause, '本次调用未发出',
                '等到次日额度重置，或到「设置 → 用量与计费」调高每日上限',
                _clip(detail, 160))


def tool_diag(tool='', exc=None, *, detail=''):
    """工具失败（类 11）：本地工具执行出错（打开文件 / 看图 / 搜索…）✓"""
    err = exc if exc is not None else ''
    raw = _clip(' '.join(x for x in (str(err), str(detail)) if x) or (getattr(err, '__class__', type(err)).__name__ if err else ''), 160)
    name = str(tool or '工具')
    return Diag('工具失败', '工具「%s」没有执行成功' % name, '这次操作没有完成',
                '换一种说法再试一次；连续失败可到「最近错误」看摘要', raw)


def local_diag(exc, *, context=''):
    """本地异常（类 12）：非网络、非上游的本地错误（文件 / 权限 / 解析等）✓

    ⭐ 只用于**用户可感知**的本地路径（见宿主 `_silent_log(..., user_facing=True)`）✓；
    内部清理、降级、逐条跳过等**有意不标** ✗（否则刷屏）。
    """
    head = ('%s时：' % context) if context else ''
    raw = _clip('%s: %s' % (type(exc).__name__, exc), 160)
    return Diag('本地异常', head + '本地处理出错', '这次操作没有完成',
                '重试一次；仍然失败可把「原始错误」复制发我', raw)


def to_card(diag: Diag, notice: str = '') -> str:
    """归因结构 → 用户可读的失败卡片文本（一行标题 + 三段明细 + 可选原始错误）

    L3-1：``notice`` = **上游公告**（由 `pet_net.probe_status()` 取得 ✓ 纯函数不收网 ✗）；
    **为空则整行不出现** ✓（护栏③：无公告不显示）
    """
    lines = [
        '❌ 这一轮没答上：%s' % diag.cause,
        '　· 出在哪：%s' % diag.layer,
        '　· 影响：%s' % diag.impact,
        '　· 下一步：%s' % diag.next_step,
    ]
    if notice:
        lines.append('　· 上游公告：%s' % str(notice).strip())
    if diag.raw:
        lines.append('　· 原始错误：%s' % diag.raw)
    return '\n'.join(lines)


def _clip(s: str, n: int) -> str:
    s = (s or '').replace('\n', ' ').strip()
    return s if len(s) <= n else s[:n] + '…'
