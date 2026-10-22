# -*- coding: utf-8 -*-
"""pet_net.py — 技能包出网入口（受白名单管控）
==================================================
技能包要联网时**不要直接 import urllib/requests**（安装时会被拒绝），改用这里：

    import pet_net
    data, err = pet_net.http_get('https://api.example.com/data.json')
    data, err = pet_net.http_post_json('https://api.example.com/v1', {'a': 1})

- 先查出网白名单（config.json 的 net_allowlist，域名模式，支持 *.example.com）
- 响应大小有上限（默认 4 MB）
- 每次调用都写审计日志（放行/拒绝都写）

为什么这么绕：技能包与桌宠同进程，进程内没法在系统层面拦住它自己 import urllib；
所以改成"声明式约束 + 统一入口"，让白名单真的能起作用（v6.69）。
"""
import governance as _gov


def http_get(url, timeout=15, max_bytes=4 * 1024 * 1024):
    """受限 GET。返回 (bytes|None, 错误文本)"""
    return _gov.http_get(url, timeout=timeout, max_bytes=max_bytes)


def http_post_json(url, payload, timeout=20, max_bytes=4 * 1024 * 1024):
    """受限 POST(JSON)。返回 (bytes|None, 错误文本)"""
    return _gov.http_post_json(url, payload, timeout=timeout, max_bytes=max_bytes)


def get_text(url, encoding='utf-8', timeout=15, max_bytes=4 * 1024 * 1024):
    data, err = http_get(url, timeout=timeout, max_bytes=max_bytes)
    if data is None:
        return None, err
    try:
        return data.decode(encoding, 'replace'), ''
    except Exception as e:
        return None, '解码失败：%s' % e


def get_json(url, timeout=15, max_bytes=4 * 1024 * 1024):
    import json
    text, err = get_text(url, timeout=timeout, max_bytes=max_bytes)
    if text is None:
        return None, err
    try:
        return json.loads(text), ''
    except Exception as e:
        return None, '不是合法 JSON：%s' % e


def allowed(url):
    """只查白名单，不发起请求（给技能做预检用）"""
    return _gov.net_allowed(url)


# ── L3：上游状态/公告探测（只读 ✓ 走既有白名单 ✓ 不新增出网口 ✗）──────────────
UPSTREAM_STATES = ('ok', 'notice', 'unknown', 'denied', 'error')


def probe_status(url='', *, timeout=3.0, max_bytes=64 * 1024):
    """探测**上游状态/公告**，供失败卡片在「上游超时/故障/限流」时附一行说明 ✓

    返回 ``{'state', 'text', 'url'}``，state ∈ :data:`UPSTREAM_STATES`：

    - ``'unknown'``：**未配置 url** → 调用方**不显示**公告行 ✓（默认态）
    - ``'denied'``：url 不在白名单 → **不发起任何请求** ✓（护栏①）
    - ``'error'``：超时/网络/解析失败 → **绝不抛异常、绝不阻塞调用方** ✓（护栏②）
    - ``'notice'``：拿到公告文本（JSON 常见字段或纯文本首行）
    - ``'ok'``：请求成功但**无公告内容** → 调用方不显示行 ✓（护栏③）

    为什么放这里：出网只允许走 `pet_net` ✓（`pet_diagnosis` 保持纯函数 ✗）
    """
    url = str(url or '').strip()
    if not url:
        return {'state': 'unknown', 'text': '', 'url': ''}
    try:
        ok, why = allowed(url)              # 先预检：白名单外不发请求 ✓
        if not ok:
            return {'state': 'denied', 'text': str(why or ''), 'url': url}
        data, err = get_json(url, timeout=timeout, max_bytes=max_bytes)
        if data is None:
            text, err2 = get_text(url, timeout=timeout, max_bytes=max_bytes)
            if text is None:
                return {'state': 'error', 'text': str(err or err2 or ''), 'url': url}
            first = next((l.strip() for l in text.splitlines() if l.strip()), '')
            return {'state': 'notice' if first else 'ok', 'text': first[:200], 'url': url}
        t = _notice_from_json(data)
        return {'state': 'notice' if t else 'ok', 'text': t[:200], 'url': url}
    except Exception as e:                  # 护栏②：异常一律吞掉，转 error ✓
        return {'state': 'error', 'text': '%s: %s' % (type(e).__name__, e), 'url': url}


def _notice_from_json(data):
    """从常见字段里取公告文本（取不到返回空串 → 视为 ok ✓ 不显示行）"""
    if isinstance(data, dict):
        for k in ('notice', 'announcement', 'message', 'title', 'description'):
            v = data.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        st = data.get('status')
        if isinstance(st, dict):
            for k in ('description', 'status', 'message'):
                v = st.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
        if isinstance(st, str) and st.strip() and st.strip().lower() not in ('ok', 'up', 'normal', 'operational'):
            return st.strip()
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return _notice_from_json(data[0])
    return ''
