# -*- coding: utf-8 -*-
"""step2: PIL 合成帧（背景渐变+立绘+截图+标题+字幕）→ cv2 写视频段"""
import math
import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

BASE = r'E:\ai工作站\desktop-pet'
OUT = os.path.join(BASE, '视频介绍')
W, H, FPS = 1280, 720, 30

FONT_TITLE = r'C:\Windows\Fonts\msyhbd.ttc'   # 微软雅黑粗体
FONT_TEXT = r'C:\Windows\Fonts\msyh.ttc'       # 微软雅黑
FONT_SUB = r'C:\Windows\Fonts\msyh.ttc'

PET = os.path.join(BASE, 'assets', 'flash', 'flash_idle.png')
PET_HAPPY = os.path.join(BASE, 'assets', 'flash', 'flash_happy.png')
SHOTS = os.path.join(BASE, 'screenshots')


def load_pet(path, height):
    img = Image.open(path).convert('RGBA')
    r = height / img.height
    return img.resize((int(img.width * r), height), Image.LANCZOS)


def gradient_bg(top=(24, 48, 84), bottom=(12, 28, 48)):
    img = Image.new('RGB', (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        c = tuple(int(a + (b - a) * t) for a, b in zip(top, bottom))
        d.line([(0, y), (W, y)], fill=c)
    return img


def fit_shot(path, max_w, max_h):
    img = Image.open(path).convert('RGB')
    r = min(max_w / img.width, max_h / img.height)
    return img.resize((int(img.width * r), int(img.height * r)), Image.LANCZOS)


def draw_text_center(d, text, y, font, fill=(255, 255, 255)):
    bbox = d.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    d.text(((W - tw) // 2, y), text, font=font, fill=fill)


def draw_text_left(d, text, x, y, font, fill=(255, 255, 255)):
    d.text((x, y), text, font=font, fill=fill)


def wrap_text(d, text, font, max_w):
    """按宽度换行"""
    lines = []
    cur = ''
    for ch in text:
        if d.textlength(cur + ch, font=font) > max_w:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


def make_frame(pet_img, pet_xy, title, subtitle, shot=None, shot_box=None, caption=''):
    img = gradient_bg()
    d = ImageDraw.Draw(img)
    if shot is not None and shot_box is not None:
        sx, sy, sw, sh = shot_box
        img.paste(shot, (sx, sy))
    if pet_img is not None:
        img.paste(pet_img, pet_xy, pet_img)
    # 标题
    if title:
        draw_text_center(d, title, 60, ImageFont.truetype(FONT_TITLE, 52), (255, 255, 255))
    if subtitle:
        draw_text_center(d, subtitle, 130, ImageFont.truetype(FONT_TEXT, 26), (160, 190, 230))
    # 字幕（底部）
    if caption:
        cf = ImageFont.truetype(FONT_SUB, 30)
        lines = wrap_text(d, caption, cf, W - 160)
        y = H - 60 - len(lines) * 42
        for ln in lines:
            draw_text_center(d, ln, y, cf, (235, 240, 250))
            y += 42
    return np.array(img)


def build_segment(name, pet, pet_xy, title, subtitle, shot_path=None, shot_box=None, caption='', duration=5.0):
    shot = None
    if shot_path and os.path.exists(shot_path):
        shot = fit_shot(shot_path, shot_box[2], shot_box[3]) if shot_box else None
    n = int(duration * FPS)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out_path = os.path.join(OUT, f'seg_{name}.mp4')
    vw = cv2.VideoWriter(out_path, fourcc, FPS, (W, H))
    for _ in range(n):
        frame = make_frame(pet, pet_xy, title, subtitle, shot, shot_box, caption)
        vw.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
    vw.release()
    print(f'seg_{name}: {duration:.1f}s -> {out_path}')


def main():
    pet_big = load_pet(PET, 500)
    pet_small = load_pet(PET, 230)
    pet_happy = load_pet(PET_HAPPY, 260)

    # 段1 开场：立绘居中右 + 大标题
    build_segment('01', pet_big, (W - 560, H - 560), 'DeepSeek 桌宠助手',
                  '小蓝带你认识我 · 开源桌面 AI 陪伴助手', caption='大家好呀！我是小蓝，一只住在你电脑里的 Q 版桌宠～',
                  duration=6.0)
    # 段2 项目：立绘左 + 右侧技术说明
    build_segment('02', pet_small, (60, H - 280), '技术栈',
                  'PySide6 桌面界面 + DeepSeek API 大模型',
                  caption='这个项目用 PySide6 和 DeepSeek 的大模型 API 打造，是开源的桌面 AI 陪伴助手！',
                  duration=6.5)
    # 段3 双角色：hero 截图
    build_segment('03', pet_small, (W - 300, H - 260), '双角色系统',
                  'V4 Flash 小蓝 ⚡ 快言快语  ·  V4 Pro 大蓝 🐋 深思熟虑',
                  shot_path=os.path.join(SHOTS, 'hero.png'), shot_box=(250, 200, 700, 380),
                  caption='我和姐姐大蓝，一个快言快语，一个深思熟虑，各有所长！',
                  duration=6.5)
    # 段4 工具：demo-chat 截图
    build_segment('04', pet_small, (W - 300, H - 260), '能聊也能干活',
                  '查天气 · 开程序 · 设提醒 · 控制音量 · PowerShell 系统查询',
                  shot_path=os.path.join(SHOTS, 'demo-chat.png'), shot_box=(250, 200, 700, 380),
                  caption='我能帮你打开程序、查询天气、设置提醒、控制音量，危险操作会先问过你哦！',
                  duration=7.0)
    # 段5 养成：小游戏截图
    build_segment('05', pet_happy, (W - 330, H - 280), '15 款小游戏 + 好感度养成',
                  '五子棋 · 扫雷 · 俄罗斯方块 · 21 点 · Farkle …',
                  shot_path=os.path.join(SHOTS, 'pet_v630_blackjack.png'), shot_box=(250, 200, 700, 380),
                  caption='我还有十五款小游戏陪你玩，还会越来越懂你，因为我有好感度系统！',
                  duration=7.0)
    # 段6 记忆：回忆相册截图
    build_segment('06', pet_small, (W - 300, H - 260), '三层记忆系统',
                  '对话记忆 · 事实记忆 · 事件回忆',
                  shot_path=os.path.join(SHOTS, 'pet_v630_memories.png'), shot_box=(250, 200, 700, 380),
                  caption='我会记住你的喜好和共同经历，重启电脑也不会忘记！',
                  duration=6.5)
    # 段7 结尾：立绘 + 欢迎
    build_segment('07', pet_big, (W - 560, H - 560), '欢迎来 GitHub 找我',
                  '搜索 DeepSeek Desktop Pet · MIT 开源',
                  caption='期待在你的电脑里安家，拜拜～', duration=6.0)


if __name__ == '__main__':
    main()
    print('全部视频段生成完成')
