# -*- coding: utf-8 -*-
"""⭐ C5／`D2-5`：**错误码表**（⭐ 采纳微信侧 `WX-…-20261005-51` 草稿 2 ✓）。

⭐ 码形：⭐ **`<域>-<类别>-<序号>`** ✓（例 `ACT-403-01` ✓）
⭐ ⚠️ **兼容硬约束**（⭐ 草稿 2 明写 ✓）：⭐ ⭐ **现有 `stop_reason` 等旧字段一律保留** ✗ ——
   ⭐ 只**另加** `code` 字段 ✓（⛔ 不改旧字段、不改旧文案 ✗）。
⭐ ⚠️ ⭐ **人话 `message` 必须同时给** ✗（⛔ 只给码不给话 ✗）—— ⭐ 用户看不懂 `ACT-403-01` ✓。
"""
from __future__ import annotations

# ⭐ 码表（⭐ 域 → 类别 → 说明 ＋ 现有落点 ✓）
CODES = {
    'ACT-403-01':   '动作端点未开启（需服务端 --enable-actions）',
    'ACT-404-01':   '未知动作',
    'SELF-403-01':  '自改码未开启（P0-1 闸门默认关）',
    'SELF-403-02':  '属围栏文件，永不可自改（P0-2）',
    'SELF-400-01':  '不是 git 仓库，拒绝自改（需版本保护）',
    'SPAWN-403-01': '程序不在子进程白名单（P0-3）',
    'LOCK-409-01':  '锁被占用（超时）',
    'TODO-409-01':  '待办已被其他运行器 claim',
    'NET-500-01':   '动作端点内部异常',
    'NET-502-01':   'provider 连续失败',
    'THUMB-500-01': '缩略图生成失败',
    'CFG-400-01':   '配置载荷非法',
}

# ⭐ 旧文案 → 码 的**宽松映射**（⭐ 用**子串**匹配 ✓ —— 因为旧落点文案不一 ✓
#   ⚠️ 这是**过渡期**手段 ✓；⭐ 新落点请**直接传 `code=`** ✗）
_HINTS = (
    ('ACT-403-01',   ('动作端点未开启', 'enable-actions')),
    ('ACT-404-01',   ('未知动作',)),
    ('SELF-403-01',  ('自改码未开启',)),
    ('SELF-403-02',  ('拒绝修改', '围栏')),
    ('SELF-400-01',  ('不是 git 仓库',)),
    ('SPAWN-403-01', ('白名单',)),
    ('LOCK-409-01',  ('占用',)),
    ('TODO-409-01',  ('claim',)),
    ('THUMB-500-01', ('缩略图',)),
)


def code_for(text: str) -> str:
    """⭐ 由**旧文案**推出码 ✓（⭐ 推不出 ⇒ 空串 ✓ ⛔ 不硬编一个假码 ✗）。"""
    t = str(text or '')
    for code, hints in _HINTS:
        if any(h in t for h in hints):
            return code
    return ''


def message_of(code: str) -> str:
    """⭐ 码 → 人话 ✓（⭐ 未知码 ⇒ 空串 ✓）。"""
    return CODES.get(str(code or ''), '')


def wrap(code: str, message: str = '') -> dict:
    """⭐ 统一包装：⭐ `{code, message}` ✓（⭐ `code` 空则只给 message ✓ 承兼容 ✓）。"""
    return {'code': str(code or ''), 'message': str(message or message_of(code) or '')}
