# -*- coding: utf-8 -*-
"""
pet_storage.py — 存储层（P1 模块化拆分）
=========================================
从 desktop_pet.py 拆出的 JSON 持久化工具：
- atomic_write_json：原子写 JSON（临时文件 + os.replace，防崩溃损坏）
- atomic_write_text：原子写纯文本（v6.53，用于聊天导出/存档）
- load_json：安全读 JSON（文件缺失/损坏返回默认值）

模块化说明：纯函数，无 UI/主程序依赖。
"""
import json
import os


def atomic_write_json(path, data, pretty=True):
    """原子写 JSON：先写临时文件再 os.replace 替换。
    防止程序崩溃/断电时直接损坏原文件（JSON 直接 open('w') 会截断原内容）。"""
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2 if pretty else None)
    os.replace(tmp, path)


def atomic_write_text(path, text):
    """v6.53：原子写纯文本（临时文件 + os.replace）——
    防导出/存档写到一半失败时留下半截文件、覆盖掉原有的好文件。"""
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(text)
    os.replace(tmp, path)


def load_json(path, default=None):
    """安全读 JSON：文件不存在/解析失败返回 default（不抛异常）"""
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return default
