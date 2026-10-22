# -*- coding: utf-8 -*-
"""rt_summary.py — L1 摘要**规则模板**（第 3 批 · B2）

设计依据：《设计 v1.1》§2（Owner 口径：**MVP 用规则模板** ✓ 后置可选议长模型 ✓）
模板：**@点名? + 首句 + 字数** ✓（例：``[@flash] 建议先做最小存储…（128 字）`` ✓）

边界（务必遵守 ✗）：
  - **纯函数** ✓：不读文件 ✗、不出网 ✗（AST 护栏 `tests/test_rt_summary.py`）
  - **确定性** ✓：同输入 → 同输出（便于幂等 ✓ 便于单测 ✓ 不掺时间/随机 ✗）
  - **退化**：空/None/超长/异常形状 → 返回**退化摘要** ✓ **绝不抛异常** ✗（L1 必须留下痕迹 ✓ 不静默跳过 ✗）
"""
from __future__ import annotations

import re

MAX_CHARS_DEFAULT = 120
DEGRADED = '（摘要生成失败）'
_SENT_END = re.compile(r'[。！？!?；;\n\r]')
_WRAP = ('…', '.', '~', '。', '！', '？')
_MENTION = re.compile(r'@([A-Za-z0-9_\-\u4e00-\u9fff]{1,32})')


def first_sentence(text, max_chars=MAX_CHARS_DEFAULT):
    """首句（到第一个句末符为止 ✓）并按 ``max_chars`` 截断（截断加 … ✓）"""
    s = str(text or '').strip()
    if not s:
        return ''
    cut = len(s)
    m = _SENT_END.search(s)
    if m:
        cut = m.start() + 1                      # 含句末符 ✓
    s = s[:cut].strip()
    n = int(max_chars) if int(max_chars) > 0 else MAX_CHARS_DEFAULT
    if len(s) > n:
        s = s[:n].rstrip() + '…'
    return s


def char_count(text):
    """字数（按**字符**计 ✓ 去首尾空白 ✓ 换行折成空格 ✓）"""
    return len(re.sub(r'\s+', ' ', str(text or '')).strip())


def extract_mention(text, mention=None):
    """@点名：显式给了就用 ✓ 否则从文本里取**第一个** @xxx ✓（都没有 → '' ✓）"""
    if mention:
        return str(mention).lstrip('@')
    m = _MENTION.search(str(text or ''))
    return m.group(1) if m else ''


def make(text, ptr='', *, max_chars=MAX_CHARS_DEFAULT, mention=None):
    """生成 L1 摘要（**纯函数** ✓ 确定性 ✓ **不抛异常** ✗）

    ⭐ 退化规则：输入为空/形状异常 → ``'（摘要生成失败）'`` + ``ptr`` ✓（**留痕不静默** ✗）
    """
    try:
        s = str(text or '').strip()
        if not s:
            return _degraded(ptr)
        head = first_sentence(s, max_chars=max_chars)
        if not head:
            return _degraded(ptr)
        who = extract_mention(s, mention)
        tag = '[@%s] ' % who if who else ''
        return '%s%s（%d 字）' % (tag, head, char_count(s))
    except Exception:
        return _degraded(ptr)


def _degraded(ptr=''):
    return '%s%s' % (DEGRADED, (' ← %s' % ptr) if ptr else '')


def is_degraded(s):
    return DEGRADED in str(s or '')
