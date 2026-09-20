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
