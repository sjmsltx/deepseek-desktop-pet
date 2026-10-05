# -*- coding: utf-8 -*-
"""⭐ B9／`D1-3`：⭐ 轮询**退避 ＋ 抖动 ＋ 上限**（⭐ 采纳微信侧 `WX-51` §一 的分工：⭐ 此项**归电脑侧** ✓）。

⭐ 要解决（⭐ 现状 ✗）：⭐ 两处启动探测都写死 ⭐ `time.sleep(poll)`（**固定 0.3s** ✗）
   ⇒ ⭐ ① 冷启动头几秒**探得太密**（⭐ 空转 ✗）② 尾巴上**探得太疏**（⭐ 慢启动吃满预算也探不到 ✓）
   ⭐ ③ 两线同时起服务 ⇒ ⭐ **探测节拍同步** ⇒ ⭐ 撞在一起 ✗（⭐ 需要**抖动**打散 ✓）

⭐ 口径（⭐ 参数为**我方选定** ✓ —— ⭐ 微信侧说"参数建议已给"✗，⭐ 但我在 `-51` 里**没找到** ✗
   ⇒ ⭐ 我按工程常规定，⭐ 并在此**写明依据** ✓，⭐ 请对方复核 ✓）：
   · ⭐ `base = 0.3s`（⭐ 保持原粒度 ✓ 不改变"最快响应"手感 ✓）
   · ⭐ `cap  = 2.0s`（⭐ ⚠️ **不能大** ✗ —— ⭐ `start_budget` 只有 **40s** ✓，
     ⭐ cap 太大 ⇒ ⭐ 后面几次探测**间隔过长** ⇒ ⭐ 服务其实起来了却探不到 ✗）
   · ⭐ `jitter = 0.25`（⭐ ±25% ✓ —— ⭐ 足以打散两线同步 ✓，⭐ 又不至于让"最长等"不可预期 ✓）
   · ⭐ 序列：⭐ `0.3 → 0.6 → 1.2 → 2.0(cap) → 2.0 …`（⭐ 每步再乘 (1 ± 0.25) ✓）

⭐ 用法：⭐ `time.sleep(next_delay(i))` ✓（⭐ `i` 从 0 起 ✓）
"""
from __future__ import annotations

import random

BASE = 0.3
CAP = 2.0
JITTER = 0.25


def next_delay(attempt: int, base: float = BASE, cap: float = CAP,
               jitter: float = JITTER, rand=None) -> float:
    """⭐ 第 `attempt` 次（⭐ 0 起 ✓）探测应等多久 ✓ —— ⭐ 指数退避 ＋ 上限 ＋ 抖动 ✓。

    ⭐ 三重保证（⭐ 各有护栏 ✓）：
      · ⭐ **不退化为负** ✗（⭐ `max(0.0, …)` ✓）
      · ⭐ **不超过 `cap`** 的**上界附近**（⭐ 抖动后最高 `cap * (1 + jitter)` ✓ 故护栏按此判 ✓）
      · ⭐ **同参数两次调用不相等** ✗（⭐ 抖动生效 ✓ 防同步 ✓）
    """
    r = rand if rand is not None else random.random
    try:
        n = int(attempt)
    except Exception:
        n = 0
    n = max(0, n)
    raw = float(base) * (2.0 ** n)
    capped = min(float(cap), raw) if float(cap) > 0 else raw
    if jitter:
        capped = capped * (1.0 + (r() * 2.0 - 1.0) * float(jitter))
    return max(0.0, capped)


def label(attempt: int, **kw) -> str:
    """⭐ 便于日志：⭐ "第 N 次探测等 1.23s" ✓。"""
    return '第 %d 次探测等 %.2fs' % (int(attempt) + 1, next_delay(attempt, **kw))
