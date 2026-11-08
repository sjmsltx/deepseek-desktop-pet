# -*- coding: utf-8 -*-
"""403 闸门必须先排空请求体（2026-11-08）

## 为什么加这组

`do_POST` 的 403 分支原先不读请求体就回包。未读数据留在接收缓冲，
`close` 时 Windows 发 RST，客户端读状态行抛 `ConnectionAbortedError: [WinError 10053]`。

它表现为「单跑绿、全量里偶发红」：`test_c5_err_appends_err_code_keeps_old_fields`
连续两次全量都在同一位置红过，而单跑 8/8 绿。我上一轮把它登记成「已知 flake」，
其实可定位。

实测（各 200 次，本机）：
    不排空 → aborted 17 / 200 = 8.50%
    先排空 → aborted  0 / 200 = 0.00%
    恢复后复核 → 0 / 200

## 两条锁

1. 行为锁：反复打 403 路径，不许出现 ConnectionAbortedError（次数取 30，兼顾稳定与耗时）
2. 结构锁：403 分支必须调用 `_drain_body()`（防以后有人重构时又删掉）
"""
import io
import json
import os
import threading
import time
import urllib.error
import urllib.request

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys
if BASE not in sys.path:
    sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'collab'))

import relay_log          # noqa: E402
import relay_server       # noqa: E402


def _serve(tmp_path):
    lg = relay_log.RelayLog(str(tmp_path / 'c.jsonl'))
    httpd, port = relay_server.create_server(lg, '127.0.0.1', 0, ui_path='')
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    for _ in range(80):
        try:
            urllib.request.urlopen('http://127.0.0.1:%d/api/health' % port, timeout=2).read()
            break
        except Exception:
            time.sleep(0.05)
    return httpd, port


def test_403_path_does_not_abort_connection(tmp_path):
    """重复打 403 路径，不许出现连接被中止。

    改前实测 8.5% 的连接会被 RST；30 次里几乎必现，所以这个次数足以抓到回归。
    """
    httpd, port = _serve(tmp_path)
    body = json.dumps({'k': 'v' * 200}).encode('utf-8')
    aborted = []
    try:
        for i in range(30):
            req = urllib.request.Request('http://127.0.0.1:%d/api/step' % port,
                                         data=body,
                                         headers={'Content-Type': 'application/json'})
            try:
                urllib.request.urlopen(req, timeout=5).read()
            except urllib.error.HTTPError as exc:
                assert exc.code == 403, '期望 403，实际 %d' % exc.code
                try:
                    exc.read()
                except Exception:
                    pass
            except ConnectionAbortedError as exc:
                aborted.append((i, repr(exc)))
    finally:
        httpd.shutdown()

    assert not aborted, (
        '403 路径出现 %d 次连接中止（示例 %r）—— 请求体没排空就回包，'
        'Windows 会发 RST' % (len(aborted), aborted[0] if aborted else None))


def test_403_branch_calls_drain_body():
    """结构锁：403 分支必须调用 `_drain_body()`。

    只锁「调用存在」，不锁顺序/参数 —— 措辞与实现可改，这一行不能丢。
    """
    src = io.open(os.path.join(BASE, 'collab', 'relay_server.py'),
                  encoding='utf-8-sig').read()
    i = src.find("return self._err(403,")
    assert i > 0, '找不到 403 返回语句'
    # 取 403 返回前 600 字范围内找排空调用
    window = src[max(0, i - 600):i]
    assert '_drain_body()' in window, (
        '403 返回前没有 `_drain_body()` —— 不排空请求体就回包会让客户端收到 RST')
