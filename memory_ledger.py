# -*- coding: utf-8 -*-
"""memory_ledger.py — 记忆线台账（JSONL 追加，可后置分析）
==========================================================
2026-11-06 建。记忆线三件事（写入边界 / 注入 / 引用）都需要「事后能查」，
否则只能靠猜。统一走这里，避免三处各写一个日志格式。

## 为什么不是普通日志

`pet_log` 写的是**人读的**滚动文本，适合排错；
这里要的是**机器统计的**（每条一行 JSON，字段固定），
比如「本周注入 N 条、其中被引用 M 条」这种要按字段聚合。

## 约定

- 一行一个 JSON 对象，字段固定：`ts` / `kind` / 其余随 kind 而定
- `kind` 取值：
    `write`   写入决策（这条记忆去了 facts / events / 被丢弃）
    `inject`  本轮注入了哪些记忆（供「注入但未引用」统计）
    `usage`   回复落地后，判定哪些被引用
- **失败不抛**：台账是观测设施，不许拖垮对话；失败写 warning 到 pet.log
- 有大小上限并滚动（默认 4 MB × 2 份），避免长驻进程把磁盘写满

## 测试

`set_path()` 可切到临时目录（用例不污染仓库 logs/）。
"""
import datetime
import json
import os
import threading

from pet_log import LOG_DIR, get_logger

_log = get_logger('memory_ledger')

#: 默认台账文件
DEFAULT_NAME = 'memory_ledger.jsonl'
MAX_BYTES = 4 * 1024 * 1024
_LOCK = threading.Lock()
_PATH_OVERRIDE = None


def set_path(path):
    """把台账切到指定路径（测试用）。传 None 恢复默认。"""
    global _PATH_OVERRIDE
    _PATH_OVERRIDE = path


def path():
    if _PATH_OVERRIDE:
        return _PATH_OVERRIDE
    return os.path.join(LOG_DIR, DEFAULT_NAME)


def _rotate_if_needed(p):
    """超上限就滚动成 .1（只留一份旧文件，够用且不会无限堆）"""
    try:
        if os.path.getsize(p) < MAX_BYTES:
            return
    except OSError:
        return
    try:
        os.replace(p, p + '.1')
    except OSError as exc:
        _log.warning('台账滚动失败（继续追加到原文件）：%s', exc)


def append(kind, payload=None, **fields):
    """追加一条。`kind` 必填；`payload` 为 dict，其余关键字并入同一行。

    返回写入的行（dict）；失败返回 None（原因进 pet.log）。
    """
    rec = {'ts': datetime.datetime.now().isoformat(timespec='seconds'),
           'kind': str(kind or '')[:24]}
    if isinstance(payload, dict):
        rec.update(payload)
    rec.update(fields)
    p = path()
    try:
        d = os.path.dirname(p)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        line = json.dumps(rec, ensure_ascii=False)
        with _LOCK:
            _rotate_if_needed(p)
            with open(p, 'a', encoding='utf-8') as fh:
                fh.write(line + '\n')
        return rec
    except Exception as exc:
        # 观测设施不许影响主流程，但必须留痕（silent_guard 红线）
        _log.warning('台账写入失败 path=%s: %s', p, exc)
        return None


def read_all(limit=0):
    """读回全部记录（按写入顺序）。limit>0 时只取最后 N 条。"""
    p = path()
    if not os.path.exists(p):
        return []
    out = []
    bad = 0
    try:
        with open(p, encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError as _exc:
                    # 半行（上次崩在中途）跳过，不影响其余 —— 记一条便于发现"台账老是被截断"
                    bad += 1
                    if bad == 1:
                        _log.warning('台账有坏行（跳过，继续读其余）path=%s: %s', p, _exc)
    except OSError as exc:
        _log.warning('台账读取失败 path=%s: %s', p, exc)
        return []
    return out[-limit:] if limit else out
