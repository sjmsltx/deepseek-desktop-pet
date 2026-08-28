# -*- coding: utf-8 -*-
"""
memory_events.py — 回忆日志（事件记忆层）

三层记忆架构中的「事件记忆」：
- 对话记忆（chat_memory*.json）：近期对话，滚动压缩 —— 现有
- 事实记忆（memory.json）：用户偏好/事实，memorize 工具 —— 现有
- 事件记忆（本模块）：共同经历时间线，长期，上限 MAX_MEMORIES 条滚动淘汰 —— 新增

回忆条目结构：
{id, time, role, type, title, detail, emotion, affection_at}
type: milestone(成就/里程碑) | event(事件) | user_mark(用户标记) | memory(事实记忆双写)
"""
import json
import os
import threading
import time

MAX_MEMORIES = 200          # 滚动淘汰上限
INJECT_COUNT = 3            # prompt 注入最近 N 条

_TYPES = {'milestone', 'event', 'user_mark', 'memory'}


class MemoryEvents:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._memories = self._load()

    # ---------- 持久化 ----------
    def _load(self) -> list:
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except Exception:
            pass
        return []

    def _save(self):
        tmp = self.path + '.tmp'
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self._memories, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.remove(tmp)
            except Exception:
                pass

    # ---------- 写入 ----------
    def add(self, role: str, type_: str, title: str, detail: str = '',
            emotion: str = '', affection_at=None) -> dict:
        """新增一条回忆。超上限滚动淘汰最旧。"""
        if type_ not in _TYPES:
            type_ = 'event'
        entry = {
            'id': int(time.time() * 1000) % 10000000,
            'time': time.strftime('%Y-%m-%d %H:%M'),
            'role': role,
            'type': type_,
            'title': title,
            'detail': detail,
            'emotion': emotion,
            'affection_at': affection_at,
        }
        with self._lock:
            self._memories.append(entry)
            if len(self._memories) > MAX_MEMORIES:
                self._memories = self._memories[-MAX_MEMORIES:]
            self._save()
            return entry

    # ---------- 读取 ----------
    def recent(self, role: str, n: int = INJECT_COUNT) -> list:
        """该角色最近 n 条（时间倒序）"""
        with self._lock:
            items = [m for m in self._memories if m.get('role') == role]
            return list(reversed(items[-n:]))

    def all(self, role=None) -> list:
        """全部（时间倒序）。role 为空返回所有角色。"""
        with self._lock:
            items = self._memories if role is None else [m for m in self._memories if m.get('role') == role]
            return list(reversed(items))

    def clear(self, role=None):
        """清空（可按角色）"""
        with self._lock:
            if role is None:
                self._memories = []
            else:
                self._memories = [m for m in self._memories if m.get('role') != role]
            self._save()

    # ---------- prompt 注入 ----------
    def prompt_hint(self, role: str) -> str:
        """拼成注入 system prompt 的回忆提示段（无回忆返回空串）"""
        items = self.recent(role, INJECT_COUNT)
        if not items:
            return ''
        lines = []
        for m in reversed(items):  # 时间正序
            title = m.get('title', '')
            detail = m.get('detail', '')
            lines.append(f"- {title}" + (f"（{detail}）" if detail else ""))
        return '\n\n【我们的回忆（可以自然提及，不要生硬罗列）】\n' + '\n'.join(lines)
