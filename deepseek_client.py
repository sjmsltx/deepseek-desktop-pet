# -*- coding: utf-8 -*-
"""
deepseek_client.py — DeepSeek API 网络层（P1 模块化拆分）
=========================================================
从 desktop_pet.py 的 _ai_worker 拆出的纯网络函数：
- chat_completions：非流式 POST（服务繁忙/网络波动自动重试，指数退避）
- stream_chat_completions：SSE 流式（yield reasoning/content/tool_calls 分块）

模块化说明：无 UI 依赖。重试状态通过 status_cb(文本) 回调通知调用方；
调用方负责注入 api_key、语言判断、状态信号、用量记录。
"""
import json as _json
import time
import urllib.request
import urllib.error

from model_registry import DEFAULT_ENDPOINT

# 全项目唯一的接口地址默认值（定义在 model_registry）。实际请求地址由调用方
# 从模型档案（models.json）传入 endpoint；此常量仅作丢参时的兜底。
API_URL = DEFAULT_ENDPOINT
RETRY_CODES = (429, 500, 502, 503)


def chat_completions(api_key, data, status_cb=None, status_zh='', status_en='', is_en=False,
                     endpoint=None):
    """非流式 API 请求：503/429/500/502 服务繁忙自动重试（等 5 秒，最多 2 次）。
    返回解析后的 JSON 响应。
    endpoint：接口地址（由调用方从模型档案传入）；None 时用模块默认地址。"""
    req = urllib.request.Request(
        endpoint or API_URL,
        data=data,
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return _json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in RETRY_CODES and attempt < 2:
                wait = 5 * (attempt + 1)  # 指数退避：第1次等5秒，第2次等10秒
                if status_cb:
                    status_cb((status_en if is_en else status_zh) +
                              f'（服务繁忙，{wait} 秒后第 {attempt + 2} 次重试…）')
                time.sleep(wait)
                continue
            raise
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            # 网络类错误（10061 连接拒绝/超时/DNS）：也自动重试，网络恢复后自动成功
            if attempt < 2:
                wait = 5 * (attempt + 1)  # 指数退避：第1次等5秒，第2次等10秒
                if status_cb:
                    status_cb((status_en if is_en else status_zh) +
                              f'（网络波动，{wait} 秒后第 {attempt + 2} 次重试…）')
                time.sleep(wait)
                continue
            raise


def stream_chat_completions(api_key, data, status_cb=None, status_zh='', status_en='', is_en=False,
                            endpoint=None):
    """SSE 流式请求：yield ('reasoning', chunk) / ('content', chunk) / ('done', full)。
    重试逻辑与 chat_completions 一致；endpoint 语义同上。"""
    req = urllib.request.Request(
        endpoint or API_URL,
        data=data,
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                buffer = b''
                reasoning_buf = []
                content_buf = []
                tool_calls = {}
                usage = None  # stream_options.include_usage 时，末尾 chunk 携带 usage
                for chunk in resp:
                    buffer += chunk
                    while b'\n' in buffer:
                        line, buffer = buffer.split(b'\n', 1)
                        line = line.strip()
                        if not line.startswith(b'data:'):
                            continue
                        payload = line[5:].strip()
                        if payload == b'[DONE]':
                            break
                        try:
                            obj = _json.loads(payload)
                        except Exception:
                            continue
                        if obj.get('usage'):
                            usage = obj['usage']
                            continue
                        try:
                            delta = obj['choices'][0].get('delta', {})
                        except Exception:
                            continue
                        rc = delta.get('reasoning_content')
                        if rc:
                            reasoning_buf.append(rc)
                            yield ('reasoning', rc)
                        c = delta.get('content')
                        if c:
                            content_buf.append(c)
                            yield ('content', c)
                        for tc in delta.get('tool_calls') or []:
                            idx = tc.get('index', 0)
                            t = tool_calls.setdefault(idx, {'id': '', 'type': 'function', 'function': {'name': '', 'arguments': ''}})
                            if tc.get('id'):
                                t['id'] += tc['id']
                            fn = tc.get('function', {})
                            if fn.get('name'):
                                t['function']['name'] += fn['name']
                            if fn.get('arguments'):
                                t['function']['arguments'] += fn['arguments']
                full = {
                    'content': ''.join(content_buf),
                    'reasoning_content': ''.join(reasoning_buf),
                    'tool_calls': list(tool_calls.values()) if tool_calls else None,
                    'usage': usage,
                }
                yield ('done', full)
                return
        except urllib.error.HTTPError as e:
            if e.code in RETRY_CODES and attempt < 2:
                wait = 5 * (attempt + 1)
                if status_cb:
                    status_cb((status_en if is_en else status_zh) +
                              f'（服务繁忙，{wait} 秒后第 {attempt + 2} 次重试…）')
                time.sleep(wait)
                continue
            raise
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            if attempt < 2:
                wait = 5 * (attempt + 1)
                if status_cb:
                    status_cb((status_en if is_en else status_zh) +
                              f'（网络波动，{wait} 秒后第 {attempt + 2} 次重试…）')
                time.sleep(wait)
                continue
            raise


def models_url(endpoint=None):
    """由 chat 接口地址推出官方的模型列表地址。
    例：…/chat/completions → …/models（换中转/代理时也跟着走）。"""
    base = (endpoint or API_URL).strip().rstrip('/')
    if base.endswith('/chat/completions'):
        base = base[:-len('/chat/completions')]
    return base + '/models'


def _http_err_text(e):
    """把 HTTPError 的响应体里那句 error.message 抽出来（失败时退回状态码）"""
    try:
        body = _json.loads(e.read().decode())
        msg = (body.get('error') or {}).get('message') or ''
        if msg:
            return msg[:160]
    except Exception:
        pass
    return ''


def list_models(api_key, endpoint=None, timeout=20):
    """拉取官方当前可用模型列表（GET /models）。
    返回 (模型 ID 列表, 错误文本)；成功时错误文本为空串。"""
    try:
        req = urllib.request.Request(
            models_url(endpoint),
            headers={'Authorization': f'Bearer {api_key}'},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = _json.loads(resp.read().decode())
        ids = [m.get('id') for m in (data.get('data') or []) if m.get('id')]
        return ids, ''
    except urllib.error.HTTPError as e:
        return [], f'HTTP {e.code} {_http_err_text(e)}'.strip()
    except Exception as e:
        return [], str(e)[:160]


def probe_model(api_key, model_id, endpoint=None, timeout=30):
    """连通性自检：发一个最小请求（max_tokens=1），看能不能通、响应里回的真实模型是谁。
    返回 (是否成功, 响应里的真实 model, 耗时秒, 错误文本)。"""
    t0 = time.time()
    body = _json.dumps({'model': model_id,
                        'messages': [{'role': 'user', 'content': 'hi'}],
                        'max_tokens': 1}).encode()
    try:
        req = urllib.request.Request(
            endpoint or API_URL, data=body,
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = _json.loads(resp.read().decode())
        return True, (data.get('model') or ''), time.time() - t0, ''
    except urllib.error.HTTPError as e:
        return False, '', time.time() - t0, f'HTTP {e.code} {_http_err_text(e)}'.strip()
    except Exception as e:
        return False, '', time.time() - t0, str(e)[:160]
