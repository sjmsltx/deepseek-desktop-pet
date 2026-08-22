# -*- coding: utf-8 -*-
"""
vision 插件：用 deepseek-v4-flash-vision-exp 看图（v6.22 内置示例插件）
- 工具：vision_describe(path, prompt)
- 图片经 Base64 内联发送，detail=low（512×512，省 token）
- 单张图最多 384 token ≈ 0.0006 元（空闲时段）
"""
import base64
import json
import os
import urllib.request

API_URL = 'https://api.deepseek.com/chat/completions'
MODEL = 'deepseek-v4-flash-vision-exp'
ALLOWED_EXT = ('jpeg', 'jpg', 'png', 'gif', 'webp')


def _api_key():
    """从桌宠 config.json 读 key（从插件目录向上找，最多 4 级）"""
    try:
        d = os.path.dirname(os.path.abspath(__file__))
        for _ in range(4):
            cfg = os.path.join(d, 'config.json')
            if os.path.isfile(cfg):
                with open(cfg, 'r', encoding='utf-8') as f:
                    return json.load(f).get('deepseek_api_key', '') or ''
            d = os.path.dirname(d)
    except Exception:
        pass
    return ''


def vision_describe(args):
    """描述/识别图片内容"""
    args = args or {}
    path = str(args.get('path', '')).strip()
    prompt = str(args.get('prompt', '请描述这张图片的内容')).strip()
    if not path:
        return '（请提供图片路径）'
    if not os.path.isfile(path):
        return f'（图片不存在：{path}）'
    key = _api_key()
    if not key:
        return '（未配置 deepseek_api_key，请先在 config.json 填写）'
    try:
        with open(path, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode()
        ext = os.path.splitext(path)[1].lower().lstrip('.') or 'png'
        if ext not in ALLOWED_EXT:
            ext = 'png'
        payload = {
            'model': MODEL,
            'messages': [{
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': prompt},
                    {'type': 'image_url',
                     'image_url': {'url': f'data:image/{ext};base64,{b64}', 'detail': 'low'}},
                ],
            }],
            'max_tokens': 800,
        }
        req = urllib.request.Request(
            API_URL,
            data=json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'},
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            r = json.loads(resp.read().decode())
        content = (r['choices'][0]['message'].get('content') or '').strip()
        return content or '（模型无输出）'
    except Exception as e:
        return f'（vision 调用失败：{e}）'
