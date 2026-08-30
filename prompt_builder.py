# -*- coding: utf-8 -*-
"""
prompt_builder.py — Prompt 构建·纯逻辑层（P1/P2 模块化拆分）
============================================================
从 desktop_pet.py 拆出的无 UI 纯函数：
- guess_status：按用户消息关键词预判 AI 处理状态（天气/时间/文件/进程等）

模块化说明：纯规则匹配，无依赖，可独立单测。
"""


def guess_status(text):
    """按用户消息关键词预判 AI 状态（猜测，工具确认后会覆盖）——返回 (状态文本, 语言) 交由调用方适配"""
    t = (text or '').lower()
    rules = [
        (['天气', '温度', '下雨', '降雨', '气温', '雾霾', '空气质量', '湿度'], ('正在查询天气', 'Checking weather')),
        (['时间', '几点', '日期', '星期'], ('正在获取时间', 'Getting time')),
        (['文件', '搜索', '查找', '找到', '哪个目录'], ('正在搜索文件', 'Searching files')),
        (['进程', '卡顿', '内存', 'cpu', '占用', '后台'], ('正在读取系统状态', 'Reading system status')),
        (['打开', '启动', '运行', '启动程序', '开一下'], ('正在打开程序', 'Opening app')),
        (['音量', '静音', '声音', '喇叭'], ('正在调整音量', 'Adjusting volume')),
        (['提醒', '闹钟', '待办', 'todo', '记得', '任务'], ('正在安排提醒/待办', 'Setting reminder/todo')),
        (['锁屏', '锁定'], ('正在锁定屏幕', 'Locking screen')),
        (['剪贴板', '复制', '粘贴'], ('正在读取剪贴板', 'Reading clipboard')),
        (['计算', '算一下', '等于'], ('正在计算', 'Calculating')),
        (['吃什么', '美食', '景点', '推荐', '介绍', '历史', '攻略'], ('正在组织回答', 'Preparing answer')),
    ]
    for keys, status in rules:
        if any(k in t for k in keys):
            return status
    return ('正在思考', 'Thinking')
