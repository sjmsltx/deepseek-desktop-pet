# -*- coding: utf-8 -*-
"""
prompt_builder.py — Prompt 构建·纯逻辑层（P1/P2 模块化拆分）
============================================================
从 desktop_pet.py 拆出的无 UI 纯函数：
- guess_status：按用户消息关键词预判 AI 处理状态（天气/时间/文件/进程等）
- build_memory_block：生成注入 system prompt 的记忆块（角色过滤 + 预算裁剪）
- build_todo_block：生成注入 prompt 的待办清单块

模块化说明：纯函数，读入状态数据、返回字符串，可独立单测。
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


def build_memory_block(facts, summaries, current):
    """生成注入 system prompt 的记忆块（按当前角色过滤，预算：事实 ≤1000 字符 + 摘要 ≤900）"""
    lines = []
    budget = 1000
    # 角色过滤：roles=both（或无 roles 字段=共享）或 roles==当前角色
    fs = [f for f in facts
          if f.get('status') == 'active'
          and (f.get('roles', 'both') == 'both' or f.get('roles') == current)]
    fs.sort(key=lambda x: -x.get('importance', 3))
    for f in fs:
        text = f.get('content', '').strip()
        if not text:
            continue
        if budget - len(text) < 0:
            break
        lines.append(f'★{f.get("importance", 3)} {text}')
        budget -= len(text)
    block = '\n'.join(lines)
    # 会话摘要（最多 3 条，每条 ≤300 字符）
    sm = []
    for s in summaries[-3:]:
        t = (s.get('content') or '').strip()[:300]
        if t:
            sm.append(t)
    if sm:
        block += ('\n【之前的对话摘要】\n' + '\n'.join(sm)) if block else '【之前的对话摘要】\n' + '\n'.join(sm)
    return block.strip()


def build_todo_block(todos):
    """生成注入 prompt 的待办清单块"""
    if not todos:
        return ''
    lines = []
    for t in todos:
        mark = '✅' if t.get('done') else '⬜'
        lines.append(f'{mark} {t.get("text", "")}')
    return '\n'.join(lines)
