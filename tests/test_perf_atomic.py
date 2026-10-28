# -*- coding: utf-8 -*-
"""回归测试：calls 缓冲扩容 + 应用索引缺图标 + 统计档原子写（2026-10-28）

## 钉住 5 件事

1. `KEEP_CALLS` 是 2000，且 `_load` / `_save` / `record` 三处都用它（不再有字面量 200）
2. `record()` 之后 `calls` 不超过 `KEEP_CALLS`（**原有缺陷：内存无限涨**）
3. `_build_app_index` 里「缺 DisplayIcon」不再连带丢掉 DisplayName
4. 缺图标的项走 `log.debug`（不写盘），不是 `_silent_log`（INFO 级，会写 478 条噪声）
5. `_save` 原子：写失败时原档不被截断，且不残留 `.tmp`
"""
import ast
import io
import json
import os
import sys
import textwrap

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)


# ---------------- ① KEEP_CALLS ----------------

def test_keep_calls_is_2000():
    import api_stats
    assert api_stats.ApiStats.KEEP_CALLS == 2000


def test_no_hardcoded_200_in_calls_paths():
    """三处（_load / _save）都不能再有字面量 -200: 控制 calls 长度

    为什么要有这条：扩容时最容易漏改某处，结果「加载裁到 200、保存写 2000」。
    """
    p = os.path.join(BASE, 'api_stats.py')
    src = io.open(p, encoding='utf-8').read()
    assert '[-200:]' not in src, '还有硬编码 [-200:]'
    assert "get('calls', [])[-200:]" not in src, '还有硬编码 200 的 _load'


def test_record_trims_calls(tmp_path):
    """★ 原有缺陷：record 里 append 后不裁剪 ⇒ 单次运行内存无限涨"""
    import api_stats
    p = tmp_path / 'api_stats.json'
    p.write_text(json.dumps({'by_day': {}, 'calls': []}), encoding='utf-8')
    st = api_stats.ApiStats(str(p))
    st.KEEP_CALLS = 5
    for _ in range(12):
        st.record({'prompt_tokens': 10, 'completion_tokens': 5},
                  model='m', purpose='chat')
    assert len(st.calls) <= 5, 'record 后 calls 有 %d 条（应 ≤5）' % len(st.calls)


def test_load_and_save_use_keep_calls(tmp_path):
    import api_stats
    p = tmp_path / 'api_stats.json'
    n = api_stats.ApiStats.KEEP_CALLS + 300
    calls = [{'time': '2026-10-28 10:00:00', 'model': 'm', 'prompt': 1,
              'completion': 1, 'total': 2, 'cost': 0.0,
              'cache_hit': 0, 'cache_miss': 1} for _ in range(n)]
    p.write_text(json.dumps({'by_day': {}, 'calls': calls}), encoding='utf-8')
    st = api_stats.ApiStats(str(p))
    assert len(st.calls) == api_stats.ApiStats.KEEP_CALLS
    st._save()
    saved = json.loads(p.read_text(encoding='utf-8'))
    assert len(saved['calls']) == api_stats.ApiStats.KEEP_CALLS


# ---------------- ② 应用索引 ----------------

def _app_index_blk():
    src = io.open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8',
                  errors='replace').read()
    blk = src[src.index('def _build_app_index'):src.index('def _load_app_index')]
    # 方法体是 4 空格缩进，直接塞进 class 会 IndentationError ⇒ 先 dedent
    return textwrap.dedent(blk)


def test_display_name_and_icon_are_separate_try():
    """★ 缺 DisplayIcon 不能连带丢掉 DisplayName

    实测：596 项里 478 项无图标，其中 378 项有名无图标；
    原实现把它俩挤在一个 try 里 ⇒ 369 个应用从没进过索引。
    """
    blk = _app_index_blk()
    tree = ast.parse(blk)

    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            seg = ast.get_source_segment(blk, node) or ''
            if 'DisplayName' in seg or 'DisplayIcon' in seg:
                found.append(seg)
    assert found, '找不到取 DisplayName/DisplayIcon 的 try'

    # 必须存在「只取 DisplayIcon」的独立 try
    icon_only = [s for s in found if 'DisplayIcon' in s and 'DisplayName' not in s]
    assert icon_only, (
        'DisplayIcon 仍与 DisplayName 挤在同一个 try ⇒ 缺图标会连名字一起丢')

    # 该 try 的 handler 必须置空 icon，而不是 continue
    assert any('icon = ' in s for s in icon_only), (
        'DisplayIcon 的 handler 里没有 icon 置空 ⇒ 可能还在 continue 丢掉整个应用')


def _icon_try_handler_src():
    """取「只含 DisplayIcon」那个 try 的 handler 源码（AST 定位，不受注释干扰）"""
    blk = _app_index_blk()
    tree = ast.parse(blk)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        try_seg = ast.get_source_segment(blk, node) or ''
        if 'DisplayIcon' not in try_seg or 'DisplayName' in try_seg:
            continue
        # 只看 handler（except 块），不看 try 体
        parts = []
        for h in node.handlers:
            seg = ast.get_source_segment(blk, h) or ''
            parts.append(seg)
        return '\n'.join(parts)
    return None


def test_missing_icon_uses_debug_not_silent_log():
    """★ 缺图标是常态（实测 478/596），必须用 log.debug（不落盘）

    原来的 478 条日志噪声就是这么来的：pet_log 的文件 handler 是 INFO 级，
    `_silent_log` 走 info() ⇒ 每条都写盘。

    ⚠ 判据必须按 **AST 取 handler**，不能按字符串窗口：
      补丁注释里也写着「DisplayIcon」，`str.index()` 会落在注释上，
      窗口整个错位 —— 证伪 B 时就是这么全绿放过的。
    """
    h = _icon_try_handler_src()
    assert h is not None, '找不到「只取 DisplayIcon」的 try'
    assert 'debug' in h, '缺图标的 handler 没有 debug 级日志（无法落痕）'
    assert '_silent_log' not in h, (
        'DisplayIcon 缺失仍走 _silent_log ⇒ 会刷 478 条 INFO 噪声')


# ---------------- ③ 原子写 ----------------

def _mk(tmp_path):
    import api_stats
    p = tmp_path / 'api_stats.json'
    p.write_text(json.dumps({'by_day': {}, 'calls': []}), encoding='utf-8')
    return api_stats.ApiStats(str(p)), p


def test_save_is_atomic_on_failure(tmp_path, monkeypatch):
    """★ 写失败时原档不能被截断

    原实现 `open(path,'w')` 先清零再写 450 KB，
    中途崩溃 ⇒ 半截 JSON ⇒ _load 从零开始 ⇒ by_day 历史全丢。
    """
    st, p = _mk(tmp_path)
    st.by_day = {'2026-10-28': {'cost': 1.23, 'count': 5}}
    st._save()
    good = p.read_text(encoding='utf-8')
    assert '2026-10-28' in good

    def boom(*a, **k):
        raise IOError('模拟磁盘满')

    monkeypatch.setattr(json, 'dump', boom)
    st.by_day = {'2026-10-28': {'cost': 999}}
    st._save()           # 内部 catch，不抛
    monkeypatch.undo()

    assert p.read_text(encoding='utf-8') == good, '写失败后原档被破坏了'
    assert not os.path.exists(str(p) + '.tmp'), '失败后残留 .tmp'


def test_save_success_leaves_no_tmp(tmp_path):
    st, p = _mk(tmp_path)
    st._save()
    assert p.exists()
    assert not os.path.exists(str(p) + '.tmp')


def test_balance_history_save_is_atomic(tmp_path, monkeypatch):
    st, p = _mk(tmp_path)
    st.set_balance({'ok': True, 'total': 50.0, 'granted': 0.0, 'topped_up': 50.0,
                    'currency': 'CNY', 'at': '2026-10-28 10:00:00'})
    hp = tmp_path / 'balance_history.json'
    good = hp.read_text(encoding='utf-8')

    def boom(*a, **k):
        raise IOError('模拟磁盘满')

    monkeypatch.setattr(json, 'dump', boom)
    st.set_balance({'ok': True, 'total': 40.0, 'granted': 0.0, 'topped_up': 40.0,
                    'currency': 'CNY', 'at': '2026-10-28 11:00:00'})
    monkeypatch.undo()
    assert hp.read_text(encoding='utf-8') == good, '余额历史被写坏了'
    assert not os.path.exists(str(hp) + '.tmp')
