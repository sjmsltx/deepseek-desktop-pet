# -*- coding: utf-8 -*-
"""vision_helper.py — 图片直接送模型（视觉）辅助（v6.62）

背景
----
`deepseek-flash` 原生支持图片输入（已实测：造一张写着「余额 70.68」的图，
按官方格式 base64 直送 messages，模型准确读到内容）。原先桌宠的图片一律走
本地 OCR → 纯文本，图表趋势、界面布局、示意图这类**非文字信息全部丢失**。

本模块只做一件事：把本地图片编成官方 `chat/completions` 能吃的 data URL，
并控制体积 —— 长边缩到 1568px、单图原始字节 ≤ 2MB，避免一张 4K 截图把请求撑爆。

依赖：仅 Pillow（已随项目安装）。不依赖 PySide6，纯函数，便于单测。
"""
import base64
import io
import os

# 可交给模型的图片格式（与 _add_attachment 的图片判定保持一致）
VISION_EXTS = ('.png', '.jpg', '.jpeg', '.bmp', '.webp', '.gif')

MAX_SIDE = 1568              # 长边上限（官方推荐量级）
MAX_BYTES = 2 * 1024 * 1024  # 单图编码后字节上限
JPEG_QUALITY = 88
MAX_IMAGES = 4               # 一条消息最多附带几张图（防误拖一堆图把费用顶上去）


def is_image_path(path):
    """按扩展名判断是不是可直接送模型的图片"""
    return os.path.splitext(str(path or ''))[1].lower() in VISION_EXTS


def _resize_to(im, side):
    """按长边缩放到 side 像素（只缩小不放大）"""
    w, h = im.size
    longest = max(w, h)
    if longest <= side or longest <= 0:
        return im
    k = float(side) / longest
    return im.resize((max(1, int(w * k)), max(1, int(h * k))))


def encode_image_data_url(path, max_side=MAX_SIDE, max_bytes=MAX_BYTES):
    """本地图片 → data URL。返回 (data_url, error)；失败时 data_url 为 None。

    编码顺序：先无损 PNG（截图文字最清晰）；PNG 超限 → 转 JPEG 并逐级降长边；
    仍超限 → 降质量兜底。全程不抛异常，把原因回给调用方。
    """
    try:
        from PIL import Image
        with Image.open(path) as im:
            im = im.convert('RGB')
            im = _resize_to(im, max_side)
            buf = io.BytesIO()
            im.save(buf, 'PNG')
            raw, mime = buf.getvalue(), 'image/png'
            if len(raw) > max_bytes:
                for side in (max_side, int(max_side * 0.6), int(max_side * 0.4)):
                    small = _resize_to(im, side)
                    buf = io.BytesIO()
                    small.save(buf, 'JPEG', quality=JPEG_QUALITY, optimize=True)
                    raw, mime = buf.getvalue(), 'image/jpeg'
                    if len(raw) <= max_bytes:
                        break
            if len(raw) > max_bytes:
                buf = io.BytesIO()
                im.save(buf, 'JPEG', quality=60, optimize=True)
                raw, mime = buf.getvalue(), 'image/jpeg'
        return 'data:%s;base64,%s' % (mime, base64.b64encode(raw).decode('ascii')), None
    except Exception as e:
        return None, '%s: %s' % (type(e).__name__, e)


def build_vision_content(text, paths, max_images=MAX_IMAGES):
    """构造 user 消息的 content。

    - 没有可用图片 → 原样返回纯文本（字符串）
    - 有图片       → 返回数组 [{type:text},{type:image_url}...]（官方多模态格式）

    返回 (content, used, errors)：used = 成功编码的图片数（0 表示调用方该回退 OCR）。
    """
    paths = [p for p in (paths or []) if p]
    if not paths:
        return text, 0, []
    parts = []
    if text:
        parts.append({'type': 'text', 'text': text})
    used, errors = 0, []
    for p in paths[:max_images]:
        url, err = encode_image_data_url(p)
        if url:
            parts.append({'type': 'image_url', 'image_url': {'url': url}})
            used += 1
        else:
            errors.append('%s：%s' % (os.path.basename(str(p)), err))
    if not used:
        return text, 0, errors
    return parts, used, errors
