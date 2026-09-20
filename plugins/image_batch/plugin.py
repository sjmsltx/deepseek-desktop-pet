# -*- coding: utf-8 -*-
"""官方技能包：图片批处理（image_batch）
=============================================
纯本地（Pillow），**不联网、不上传**。结果统一落到 输出/<子目录>/ 下，不改动你的原图。
一次最多处理 MAX_FILES 张，防止误点一下刷出上千个文件。
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

OUT_DIR = os.path.join(BASE, '输出')
EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif', '.tif', '.tiff')
MAX_FILES = 50
MAX_W = 4096


def _resolve(src):
    s = str(src or '').strip().strip('"')
    if not s:
        return ''
    return s if os.path.isabs(s) else os.path.join(BASE, s)


def _safe_dir(name):
    raw = os.path.basename(str(name or '').strip()) or '图片处理'
    d = os.path.join(OUT_DIR, raw)
    os.makedirs(d, exist_ok=True)
    return d


def _collect(src):
    """src 可以是文件夹或单个文件；返回图片绝对路径列表（已排序、已截断）"""
    src = _resolve(src)
    if os.path.isfile(src):
        return [src]
    if not os.path.isdir(src):
        return []
    files = [os.path.join(src, f) for f in sorted(os.listdir(src))
             if f.lower().endswith(EXTS) and os.path.isfile(os.path.join(src, f))]
    return files[:MAX_FILES]


def image_batch(args):
    args = args or {}
    action = str(args.get('action') or 'info').strip().lower()
    try:
        from PIL import Image
    except Exception as e:
        return '没装 Pillow，无法处理图片：%s' % e

    files = _collect(args.get('src'))
    if not files:
        return '没找到图片（src 给文件夹或单张图片；支持的格式：%s）' % '、'.join(EXTS)

    if action == 'info':
        lines = ['共 %d 张图片：' % len(files)]
        for f in files[:15]:
            try:
                with Image.open(f) as im:
                    lines.append('  %s —— %d×%d，%s'
                                 % (os.path.basename(f), im.width, im.height, im.format))
            except Exception as e:
                lines.append('  %s —— 读取失败（%s）' % (os.path.basename(f), type(e).__name__))
        if len(files) > 15:
            lines.append('  …（还有 %d 张）' % (len(files) - 15))
        return '\n'.join(lines)

    if action == 'resize':
        try:
            tw = int(float(args.get('width') or 0))
            th = int(float(args.get('height') or 0))
        except Exception:
            return 'width / height 要给数字。'
        if not tw and not th:
            return '请给 width 或 height（等比缩放，给一个就够）。'
        tw = min(tw, MAX_W) if tw else 0      # ★ 没给的那个保持 0，不能拿 MAX_W 去填
        th = min(th, MAX_W) if th else 0
        out_dir = _safe_dir(args.get('name') or '图片缩放')
        made = 0
        for f in files:
            try:
                with Image.open(f) as im:
                    if tw and th:
                        size = (tw, th)
                    elif tw:
                        size = (tw, max(1, round(im.height * tw / im.width)))
                    else:
                        size = (max(1, round(im.width * th / im.height)), th)
                    im2 = im.resize(size, Image.LANCZOS)
                    if im2.mode in ('RGBA', 'P') and os.path.splitext(f)[1].lower() in ('.jpg', '.jpeg'):
                        im2 = im2.convert('RGB')
                    ext = os.path.splitext(f)[1].lower()
                    im2.save(os.path.join(out_dir, os.path.splitext(os.path.basename(f))[0] + ext))
                    made += 1
            except Exception:
                continue
        return '已缩放 %d 张 → 输出\\%s\\' % (made, os.path.basename(out_dir))

    if action == 'convert':
        fmt = str(args.get('format') or 'jpg').strip().lower().lstrip('.')
        if fmt in ('jpeg', 'jpg'):
            fmt, ext, pil_fmt = 'jpg', '.jpg', 'JPEG'
        elif fmt == 'png':
            ext, pil_fmt = '.png', 'PNG'
        elif fmt == 'webp':
            ext, pil_fmt = '.webp', 'WEBP'
        else:
            return '不支持的格式：%s（可用 jpg / png / webp）' % fmt
        out_dir = _safe_dir(args.get('name') or ('转' + fmt))
        made = 0
        for f in files:
            try:
                with Image.open(f) as im:
                    im2 = im
                    if pil_fmt == 'JPEG' and im.mode in ('RGBA', 'P', 'LA'):
                        im2 = im.convert('RGB')
                    im2.save(os.path.join(out_dir, os.path.splitext(os.path.basename(f))[0] + ext),
                             pil_fmt)
                    made += 1
            except Exception:
                continue
        return '已转换 %d 张为 %s → 输出\\%s\\' % (made, fmt, os.path.basename(out_dir))

    if action == 'rename':
        prefix = str(args.get('prefix') or '').strip() or '图片'
        out_dir = _safe_dir(args.get('name') or '图片重命名')
        made = 0
        for i, f in enumerate(files, 1):
            ext = os.path.splitext(f)[1].lower()
            dst = os.path.join(out_dir, '%s_%03d%s' % (prefix, i, ext))
            try:
                with open(f, 'rb') as r, open(dst, 'wb') as w:
                    w.write(r.read())          # 复制而不是改名：不动原图
                made += 1
            except Exception:
                continue
        return '已复制并重命名 %d 张 → 输出\\%s\\（原图未改动）' % (made, os.path.basename(out_dir))

    return '未知 action：%s（可用：info / resize / convert / rename）' % action
