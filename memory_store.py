# -*- coding: utf-8 -*-
"""
memory_store.py — 长期记忆存储层（P1 模块化拆分）
==================================================
从 desktop_pet.py 拆出的记忆数据操作（纯函数，无 UI 依赖）：
- load_memory：读 memory.json（facts + summaries）
- save_memory：原子写 memory.json（带 updated_at）
- remember_fact：memorize 工具的 add/update/delete 事实操作（返回新 facts + 提示文本）

模块化说明：remember_fact 为纯函数（不落盘），由调用方持有状态并调用 save_memory。
"""
import datetime
import json
import os

from pet_storage import atomic_write_json


def load_memory(path):
    """加载 memory.json（事实 + 摘要）"""
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return (data.get('facts', []) or [], data.get('summaries', []) or [])
    except Exception:
        pass
    return ([], [])


def save_memory(path, facts, summaries):
    """保存 memory.json（原子写 + updated_at）"""
    try:
        atomic_write_json(path, {
            'facts': facts,
            'summaries': summaries,
            'updated_at': datetime.datetime.now().isoformat(),
        })
    except Exception:
        pass


def remember_fact(facts, action, content='', importance=3, fid='', role='both'):
    """memorize 工具处理：add/update/delete 长期事实（纯函数，不落盘）。
    role: both=共享 / flash / pro。返回 (new_facts, 提示文本)。"""
    now = datetime.datetime.now().isoformat(timespec='seconds')
    try:
        importance = max(1, min(int(importance), 5))
    except Exception:
        importance = 3
    if role not in ('flash', 'pro', 'both'):
        role = 'both'
    content = (content or '').strip()
    facts = list(facts)

    if action == 'add':
        if not content:
            return facts, '内容为空，未保存'
        # 相似内容已存在则更新（软覆盖）
        for f in facts:
            if f.get('status') == 'active' and (f.get('content') == content or content in f.get('content', '') or f.get('content', '') in content):
                f['content'] = content
                f['importance'] = importance
                f['roles'] = role
                f['updated_at'] = now
                return facts, f'已更新已有记忆 #{f["id"]}'
        fid = f'f{int(datetime.datetime.now().timestamp() * 1000)}'
        facts.append({'id': fid, 'content': content, 'importance': importance,
                      'created_at': now, 'updated_at': now, 'status': 'active', 'roles': role})
        # 遗忘机制：超 50 条按 重要度升序+旧 淘汰
        if len(facts) > 50:
            facts.sort(key=lambda x: (x.get('importance', 3), x.get('updated_at', '')))
            facts = facts[-50:]
        return facts, f'已记住（重要度 {importance}/5）'

    if action == 'delete':
        for f in facts:
            if f.get('id') == fid or f.get('content') == content:
                f['status'] = 'superseded'
                f['updated_at'] = now
                return facts, f'已遗忘 #{f["id"]}'
        return facts, '未找到对应记忆'

    if action == 'update':
        for f in facts:
            if f.get('id') == fid:
                f['content'] = content or f.get('content', '')
                f['importance'] = importance
                f['updated_at'] = now
                f['status'] = 'active'
                return facts, f'已更新 #{fid}'
        return facts, '未找到对应记忆 ID'

    return facts, '未知操作（add/update/delete）'
