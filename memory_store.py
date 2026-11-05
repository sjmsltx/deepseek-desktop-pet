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
from pet_log import get_logger

_log = get_logger('memory_store')


def load_memory(path):
    """加载 memory.json（事实 + 摘要）"""
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return (data.get('facts', []) or [], data.get('summaries', []) or [])
    except Exception as e:
        # 原先静默 pass：记忆文件坏了用户只会觉得"它怎么不记得了"
        _log.warning('memory.json 读取失败，本次按"无记忆"启动：%s', e)
    return ([], [])


def save_memory(path, facts, summaries):
    """保存 memory.json（原子写 + updated_at）"""
    try:
        atomic_write_json(path, {
            'facts': facts,
            'summaries': summaries,
            'updated_at': datetime.datetime.now().isoformat(),
        })
    except Exception as e:
        # 记忆写入失败 = 用户说的话白说了，必须留痕
        _log.error('memory.json 写入失败，本次记忆修改已丢失：%s', e)


def _next_fact_id(facts):
    """生成不撞号的记忆 id（格式 `f<毫秒>`，撞号则加 `-n` 后缀）。

    原实现是 `f{int(now.timestamp() * 1000)}` —— **纯毫秒时间戳，无任何撞号检查**。
    自动抽取一次写多条是在同一循环里连写（desktop_pet L3083-3088），同毫秒必然撞号。

    存量已撞 3 组（6 条**内容完全不同**的真实记忆共用 3 个 id，且两份都 active）：
        f1792549566216 / f1793010722059 / f1793377316145
    后果（都实测过）：
      · `_bump_fact_hits` 用 {id: f} 建索引 ⇒ 只加到其中一份，另一份 weight 永远 None
      · 一次 query 命中同 id 的两条 ⇒ 同一 id 在 prompt 里出现两次、内容还不一样
      · `remember_fact('delete')` 命中第一份就 return ⇒ 用户说「忘了」，回执「已遗忘」，
        但另一半仍 active、仍会被检索到

    实测：连续 add 200 次 → 唯一 id **1 个**、撞号 49 组（98%）。

    照 memory_events._next_id 的写法 —— 那边早已修过同一个坑，facts 侧漏了。
    """
    used = {f.get('id') for f in facts if isinstance(f, dict)}
    base = int(datetime.datetime.now().timestamp() * 1000)
    cand = 'f%d' % base
    n = 0
    while cand in used and n < 10000:
        n += 1
        cand = 'f%d-%d' % (base, n)
    return cand


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
        fid = _next_fact_id(facts)
        facts.append({'id': fid, 'content': content, 'importance': importance,
                      'created_at': now, 'updated_at': now, 'status': 'active', 'roles': role})
        # ⛔ 2026-11-05 删除：此处原有「超 50 条按 (importance, updated_at) 升序物理截断」。
        #   它是 v3.0 之前的容量治理，与 2026-11-04 新增的 _enforce_memory_cap **重复，且更早触发**：
        #     · 判的是**全部** facts（含 superseded），不看 status ⇒ 作废条目占着名额
        #     · 判据只有 importance + 时间，不认 weight / bump / 衰减 / _CRITICAL_PATTERNS
        #     · **物理删除**，不写台账、不留痕
        #   ⇒ 台账、critical 保护、400 条上限（FACTS_MAX），在真实写入路径上**全部形同虚设**。
        #   实测（verify_wx179.py）：真实库 44 条，**再加 7 条即触发**；
        #     投入 49 条普通 + 1 条「对花生过敏」→ add 一条后，**过敏被物理删除**；
        #     台账行数前后都是 0（静默消失）。
        #   容量治理只留一条路：`_save_memory` → `_enforce_memory_cap`
        #   （status='evicted'，可恢复，写 memory_evicted_facts.jsonl）。
        #   顺带修掉一个隐性副作用：`facts.sort()` 会**原地打乱整库顺序**，
        #   而 `_extract_worker` 用 `self.memory_facts[-10:]` 取「已有记忆」当抽取上下文。
        #   ⚠ 别再把它加回来：test_remember_fact_never_physically_drops 会红。
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
