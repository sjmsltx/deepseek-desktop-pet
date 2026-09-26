# -*- coding: utf-8 -*-
"""B2 护栏：`rt_summary`（L1 摘要**规则模板**）

盯死四条（设计 v1.1 §2 + §8）：
  ① 模板三段齐：**@点名? + 首句 + 字数** ✓
  ② **确定性**：同输入 → 同输出 ✓（幂等的前提 ✓）
  ③ **退化不炸**：空/None/超长/异常形状 → 退化摘要**留痕** ✓ 不抛 ✗ 不静默 ✗
  ④ **纯函数边界**：不读文件 ✗ 不出网 ✗（AST ✓）
"""
from __future__ import annotations

import ast
import io
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOD = ROOT / 'rt_summary.py'


def _m():
    import rt_summary
    return rt_summary


# ── ① 模板三段 ──────────────────────────────────────────────────────
def test_template_has_mention_head_and_count():
    m = _m()
    s = m.make('@flash 建议先做最小存储；其余后置。后面还有很长内容' * 3, 'flash|2026-09-26|0042')
    assert s.startswith('[@flash] '), s
    assert '建议先做最小存储；' in s, s
    assert re.search(r'（\d+ 字）$', s), s


def test_mention_extraction_rules():
    m = _m()
    assert m.extract_mention('@pro 请注意口径') == 'pro'
    assert m.extract_mention('没有点名的一段话') == ''
    assert m.extract_mention('@whatever', mention='flash') == 'flash', '显式给的点名优先 ✓'


# ── ② 确定性（幂等前提）──────────────────────────────────────────────
def test_deterministic():
    m = _m()
    a = m.make('内容内容内容。', 'flash|2026-09-26|0001')
    b = m.make('内容内容内容。', 'flash|2026-09-26|0001')
    assert a == b, '同输入必须同输出 ✓（否则幂等失效 ✗）'
    assert a.count('（') == 1 and a.count('字）') == 1


# ── 首句 + 截断边界 ─────────────────────────────────────────────────
def test_first_sentence_and_truncation():
    m = _m()
    assert m.first_sentence('第一句。第二句。') == '第一句。'
    assert m.first_sentence('没有句末符的一段话') == '没有句末符的一段话'
    long1 = 'x' * 500
    got = m.first_sentence(long1, max_chars=20)
    assert len(got) <= 21 and got.endswith('…'), (len(got), got[-3:])
    # 换行也算句末 ✓（实现会把尾换行 strip 掉 ✓ 更干净 ✓）
    assert m.first_sentence('第一行\n第二行') == '第一行'


def test_char_count_counts_chars():
    m = _m()
    assert m.char_count('字字字') == 3
    assert m.char_count('  a  b \n c ') == 5          # 折叠空白 ✓


# ── ③ 退化：留痕、不炸、不静默 ───────────────────────────────────────
def test_degraded_on_empty_and_weird_inputs():
    m = _m()
    for bad in ('', None, '   ', '\n\n'):
        s = m.make(bad, 'flash|2026-09-26|0009')
        assert m.is_degraded(s), s
        assert 'flash|2026-09-26|0009' in s, '退化摘要必须带 ptr 留痕 ✓ 不静默 ✗'
    # 异常形状（非字符串）也不炸 ✓
    assert isinstance(m.make(12345, 'p'), str)
    assert isinstance(m.make(['a', 'b'], 'p'), str)
    assert isinstance(m.make(object(), 'p'), str)


# ── ④ 纯函数边界：无文件/无网 ────────────────────────────────────────
def test_pure_no_file_no_network():
    src = io.open(MOD, encoding='utf-8').read()
    tree = ast.parse(src)
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            nm = getattr(node.func, 'id', None) or getattr(node.func, 'attr', None)
            if nm in ('open', 'urlopen', 'request', 'get', 'post'):
                bad.append('%s@%d' % (nm, node.lineno))
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split('.')[0] in ('requests', 'http', 'socket', 'urllib'):
                    bad.append('import:%s@%d' % (a.name, node.lineno))
        if isinstance(node, ast.ImportFrom) and (node.module or '').split('.')[0] in ('requests', 'http', 'socket', 'urllib'):
            bad.append('from:%s@%d' % (node.module, node.lineno))
    assert not bad, f'rt_summary 必须纯 ✓（不得读文件/出网 ✗）：{bad}'
    # 不掺时间/随机（确定性 ✓）
    for badword in ('time.', 'datetime', 'random', 'now('):
        assert badword not in src, f'rt_summary 不得掺 {badword} ✗（破坏确定性 ✗）'


# ── 与 rt_store 协作：同 ptr 同摘要 → 幂等（不写新行 ✓）──────────────
def test_integration_idempotent_with_store(tmp_path):
    import rt_store
    m = _m()
    st = rt_store.Store(str(tmp_path / 'rt'))
    ptr = st.append('flash', 'role', '@flash 做最小存储。')
    s1 = m.make('@flash 做最小存储。', ptr)
    s2 = m.make('@flash 做最小存储。', ptr)
    assert s1 == s2
    assert st.add_summary(ptr, s1, round_id='r-1') is True
    assert st.add_summary(ptr, s2, round_id='r-1') is False, '同 ptr 同摘要必须幂等 ✓'
