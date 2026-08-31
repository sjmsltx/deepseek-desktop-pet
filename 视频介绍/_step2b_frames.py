# -*- coding: utf-8 -*-
"""step2b: 按语音时长重新生成视频段（时长 = mp3 时长 + 0.8s 缓冲）"""
import os
import glob
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mutagen.mp3 import MP3
from _step2_frames import build_segment, load_pet, fit_shot, PET, PET_HAPPY, SHOTS, OUT

# 读语音时长
durations = {}
for f in glob.glob(os.path.join(OUT, '*.mp3')):
    name = os.path.basename(f).replace('.mp3', '')
    durations[name] = MP3(f).info.length
print('语音时长:', {k: round(v, 1) for k, v in durations.items()})

pet_big = load_pet(PET, 500)
pet_small = load_pet(PET, 230)
pet_happy = load_pet(PET_HAPPY, 260)


def D(name):
    return durations[name] + 0.8


# 删除旧段
for f in glob.glob(os.path.join(OUT, 'seg_*.mp4')):
    os.remove(f)

build_segment('01', pet_big, (1280 - 560, 720 - 560), 'DeepSeek 桌宠助手',
              '小蓝带你认识我 · 开源桌面 AI 陪伴助手', caption='大家好呀！我是小蓝，一只住在你电脑里的 Q 版桌宠～',
              duration=D('01_开场'))
build_segment('02', pet_small, (60, 720 - 280), '技术栈',
              'PySide6 桌面界面 + DeepSeek API 大模型',
              caption='这个项目用 PySide6 和 DeepSeek 的大模型 API 打造，是开源的桌面 AI 陪伴助手！',
              duration=D('02_项目'))
build_segment('03', pet_small, (1280 - 300, 720 - 260), '双角色系统',
              'V4 Flash 小蓝 ⚡ 快言快语  ·  V4 Pro 大蓝 🐋 深思熟虑',
              shot_path=os.path.join(SHOTS, 'hero.png'), shot_box=(250, 200, 700, 380),
              caption='我和姐姐大蓝，一个快言快语，一个深思熟虑，各有所长！',
              duration=D('03_双角色'))
build_segment('04', pet_small, (1280 - 300, 720 - 260), '能聊也能干活',
              '查天气 · 开程序 · 设提醒 · 控制音量 · PowerShell 系统查询',
              shot_path=os.path.join(SHOTS, 'demo-chat.png'), shot_box=(250, 200, 700, 380),
              caption='我能帮你打开程序、查询天气、设置提醒、控制音量，危险操作会先问过你哦！',
              duration=D('04_工具'))
build_segment('05', pet_happy, (1280 - 330, 720 - 280), '15 款小游戏 + 好感度养成',
              '五子棋 · 扫雷 · 俄罗斯方块 · 21 点 · Farkle …',
              shot_path=os.path.join(SHOTS, 'pet_v630_blackjack.png'), shot_box=(250, 200, 700, 380),
              caption='我还有十五款小游戏陪你玩，还会越来越懂你，因为我有好感度系统！',
              duration=D('05_养成'))
build_segment('06', pet_small, (1280 - 300, 720 - 260), '三层记忆系统',
              '对话记忆 · 事实记忆 · 事件回忆',
              shot_path=os.path.join(SHOTS, 'pet_v630_memories.png'), shot_box=(250, 200, 700, 380),
              caption='我会记住你的喜好和共同经历，重启电脑也不会忘记！',
              duration=D('06_记忆'))
build_segment('07', pet_big, (1280 - 560, 720 - 560), '欢迎来 GitHub 找我',
              '搜索 DeepSeek Desktop Pet · MIT 开源',
              caption='期待在你的电脑里安家，拜拜～', duration=D('07_结尾'))
print('全部视频段按语音时长重新生成完成')
