# -*- coding: utf-8 -*-
"""net_local.py — 环回地址一律绕代理的薄封装（2026-10-25）

## 为什么需要它（实测数据，不是推断）

本机开着系统代理（龙猫云 / ApexCore，`127.0.0.1:7890`），注册表 `ProxyOverride`
里已含 `127.*;localhost`。实测三种配置：

| 配置 | `proxy_bypass('127.0.0.1')` | 打本地活服务的结果 |
|---|---|---|
| ① 只有系统代理（注册表） | **True** | OK 200，0.02s |
| ② 另设了 `http_proxy` 环境变量 | **False** | **HTTPError 502**，0.42s |
| ③ `http_proxy` + `no_proxy=127.0.0.1` | True | OK 200，0.00s |
| ④ 显式 `ProxyHandler({})` | —（不查） | OK 200，0.02s |

⇒ 三个事实：

1. **只有系统代理时，本地请求本来就不走代理** —— 注册表的 `ProxyOverride` 被
   `urllib.request.proxy_bypass()` 正确采纳。
2. **一旦有人设了 `http_proxy` 环境变量**，Python 改用环境变量逻辑，
   **忽略注册表里的 `ProxyOverride`** ⇒ 127.0.0.1 的请求被送进代理 ⇒ 502。
3. 因此"要不要绕代理"取决于环境，**不能靠运气**。

## 它解决什么

只在**环回地址**上显式绕代理：

- 远程地址（`api.deepseek.com`、云端 ASR/TTS）**行为完全不变**，该走代理还是走代理
- 环回地址（本机 TTS / relay / 健康检查）**永不被代理接管**

## ⛔ 不要扩大范围

只判 `127.0.0.0/8`、`localhost`、`::1`、`0.0.0.0`。
判定**按 host、与 scheme 无关**（`ftp://127.0.0.1` 也算环回）。
**不要**把 `192.168.*` / `10.*` 这类局域网地址也算进来 —— 那些走不走代理是
另一件事（注册表里也单独列了），没实测过就不要动。
"""
import urllib.parse
import urllib.request

LOOPBACK_HOSTS = frozenset(('localhost', '::1', '0.0.0.0', 'localhost.localdomain'))


def _host_of(url):
    """取 URL（或 Request）的 host，小写。解析不了返回空串。

    ⛔ 为什么单独一个函数：静默护栏的 `broad-swallow` 判据是
       「try 体 >= N 句 且 handler 不落痕」⇒ 判「宽泛吞异常」。
       把取 host 单独拿出来，try 体只剩一句 return，
       异常范围**精确到解析这一步**，读代码时看得见 —— 这比"看着干净"更重要。
    """
    target = (url.full_url if isinstance(url, urllib.request.Request)
              else str(url or ''))
    try:
        return (urllib.parse.urlsplit(target).hostname or '').strip().lower()
    except (ValueError, TypeError, AttributeError):
        # 只兜"输入解析不了"：urlsplit 遇畸形 IPv6（如 http://[::1）抛 ValueError，
        # str() 遇怪对象可能 TypeError / AttributeError。
        # ⛔ 不写 except Exception —— 那会把真 bug 也吞掉。
        return ''


def is_loopback(url):
    """这个 URL（或 Request）是不是指向本机环回地址。

    ⛔ 解析失败一律当 False（宁可走默认行为，也不擅自改变远程请求的路由）
    """
    host = _host_of(url)
    if not host:
        return False
    if host in LOOPBACK_HOSTS:
        return True
    if host.startswith('127.'):
        parts = host.split('.')
        return len(parts) == 4 and all(p.isdigit() for p in parts)
    return False


_OPENER = None


def _no_proxy_opener():
    """只构造一次（build_opener 有开销）。"""
    global _OPENER
    if _OPENER is None:
        _OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return _OPENER


def urlopen(url, data=None, timeout=None, **kwargs):
    """等价于 urllib.request.urlopen，但环回地址显式绕代理。

    ⚠ timeout 的默认值：这里用 `None` 表示"沿用 urllib 自己的默认"，
      而不是把它当成"永不超时"。urllib 的默认是 socket._GLOBAL_DEFAULT_TIMEOUT。
    """
    import socket as _socket
    if timeout is None:
        timeout = _socket._GLOBAL_DEFAULT_TIMEOUT
    if is_loopback(url):
        return _no_proxy_opener().open(url, data=data, timeout=timeout, **kwargs)
    return urllib.request.urlopen(url, data=data, timeout=timeout, **kwargs)
