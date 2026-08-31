# -*- coding: utf-8 -*-
"""step1: 介绍词 → edge-tts 生成语音（小蓝口吻，女声）"""
import asyncio
import os
import edge_tts

OUT_DIR = r'E:\ai工作站\desktop-pet\视频介绍'
os.makedirs(OUT_DIR, exist_ok=True)

# 小蓝口吻介绍词（7 段）
SCRIPT = [
    ('01_开场', '大家好呀！我是小蓝，一只住在你电脑里的 Q 版桌宠～今天，由我来介绍我所在的项目——DeepSeek 桌宠助手！'),
    ('02_项目', '这个项目用 PySide6 和 DeepSeek 的大模型 API 打造，是一个完全开源的桌面 AI 陪伴助手，已经在 GitHub 上和全世界开发者见面啦！'),
    ('03_双角色', '在这里，还有我的姐姐大蓝。我们俩一个用 V4 Flash 模型，快言快语效率优先；一个用 V4 Pro 模型，深思熟虑。聊天、干活，各有所长！'),
    ('04_工具', '我能帮你打开程序、查询天气、设置提醒、控制音量，甚至用 PowerShell 帮你查系统信息。当然，危险操作我可是会先问过你的哦！'),
    ('05_养成', '我还有十五款小游戏陪你玩，五子棋、扫雷、俄罗斯方块、二十一点……陪你聊天、玩游戏，还会越来越懂你。因为我有好感度和记忆系统！'),
    ('06_记忆', '我会记住你的喜好，记住我们共同经历的点点滴滴。就算重启了电脑，我也还记得你爱吃什么、上次聊到哪里！'),
    ('07_结尾', '如果你想把我带回家，欢迎来 GitHub 搜索 DeepSeek Desktop Pet。期待在你的电脑里安家，拜拜～'),
]


async def gen(name, text):
    out = os.path.join(OUT_DIR, f'{name}.mp3')
    com = edge_tts.Communicate(text, 'zh-CN-XiaoxiaoNeural', rate='+0%', volume='+0%')
    await com.save(out)
    return out


async def main():
    for name, text in SCRIPT:
        out = await gen(name, text)
        size = os.path.getsize(out)
        print(f'{name}: {size/1024:.1f} KB')


asyncio.run(main())
print('TTS 完成')
