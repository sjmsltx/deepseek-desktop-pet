# -*- coding: utf-8 -*-
"""风险 1 后续护栏：**关键路径**（落盘 / 用户数据）不得被静默吞 ✗。

口径（沿用 2026-10-03 风险 1）：
  · 只过**关键路径** —— 模型调用 / 文件写 / 网络 / 审计 / 用户数据 ✓
  · ⭐ **合理兜底一律不动** ✓（解析失败回默认值 ✓ 主题/UI 类 ✓）
  · ⭐ 防“空扫永远通过”：必须有**反向断言** ＋ ⭐ **对本护栏的自证**（能抓到修复前的版本 ✓）
"""
import ast
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PET = os.path.join(ROOT, 'desktop_pet.py')

# ⭐ 落盘类调用：绝不允许被“静默”吞 ✗
WRITE_CALLS = ('_atomic_write_json', 'write_json', 'json.dump', 'fh.write',
               'f.write', 'shutil.copy', 'os.replace', '_save_memory', '_save_todos',
               '_save_reminders')


def _silent(handler) -> bool:
    """handler 体是否**静默**（只有 pass / 裸常量 ✗）。"""
    return all(isinstance(b, ast.Pass) or
               (isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant))
               for b in handler.body)


def _seg(node) -> str:
    return ast.dump(node)


def _scan(path):
    """⭐ 返回 `(handlers, silent_handlers, try_handler_pairs)`。

    ⚠️ **踩过的坑（本批自证时揪出 ✗）**：起初只拿 `ExceptHandler` 节点去搜落盘调用 ✗ ——
    而**落盘调用在 `try` 体里** ✓，不在 handler 节点里 ✗ → 扫描**永远零命中** ✗
    （＝“空扫永远通过” ✗）→ ⭐ 必须把 handler 与它的 `Try` **配对**才能看到 try 体 ✓
    """
    src = io.open(path, encoding='utf-8').read()
    tree = ast.parse(src)
    handlers = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)]
    pairs = []
    for t in ast.walk(tree):
        if not isinstance(t, ast.Try):
            continue
        for h in t.handlers:
            pairs.append((t, h))
    return handlers, [h for h in handlers if _silent(h)], pairs


def _silent_write_sites(path):
    """返回被静默吞掉的**落盘点** [(行号, 命中词)] ✓。"""
    _, _, pairs = _scan(path)
    bad = []
    for t, h in pairs:
        if not _silent(h):
            continue
        seg = _seg(t).replace('.', '')          # ⭐ 检 **try 体** ✓
        for call in WRITE_CALLS:
            if call.replace('.', '') in seg:
                bad.append((h.lineno, call))
    return bad


# ── 1. ⭐ 反向护栏：必须**真扫到**（否则“零命中”毫无意义 ✗）────────────
def test_scan_actually_finds_things():
    handlers, silent, pairs = _scan(PET)
    assert len(handlers) > 50, '⭐ 扫到的 except 太少 ✗ 说明扫描失效了 ✗'
    assert len(silent) > 20, '⭐ 静默块太少 ✗ 扫描可能没生效 ✗'
    assert len(pairs) > 50, '⭐ Try／handler 配对太少 ✗'


# ── 2. ⭐⭐ 核心：**落盘调用**不得被静默吞 ✗（可泛化 ✓ 不只钉三个函数）──
def test_no_silent_write_paths():
    bad = _silent_write_sites(PET)
    assert not bad, '⛔ 这些落盘调用被静默吞了 ✗（用户会以为存上了 ✗）：%s' % bad


# ── 3. ⭐⭐ 自证：本护栏**必须能抓到修复前**的版本（否则等于没护栏 ✗）──
def test_guard_has_teeth_on_known_bad_source():
    """⭐ 用一段**人为含静默落盘**的源码，证明护栏会判红 ✓（防空扫 ✓）。"""
    bad_src = (
        'def f():\n'
        '    try:\n'
        '        self._atomic_write_json(P, data)\n'
        '    except Exception:\n'
        '        pass\n'
    )
    p = os.path.join(os.environ.get('TEMP', '.'), '_teeth_probe_%d.py' % os.getpid())
    io.open(p, 'w', encoding='utf-8', newline='').write(bad_src)
    try:
        hits = _silent_write_sites(p)
        assert hits, '⛔ 护栏对“静默落盘”样本**未判红** ✗ ＝ 空扫 ✗（护栏无效 ✗）'
        assert hits[0][1] == '_atomic_write_json'
    finally:
        try:
            os.remove(p)
        except OSError:
            pass


# ── 4. ⭐ 三处具体点位的**行为**断言（源码级 ✓ 双向钉）───────────────
def _fn_seg(src, name):
    seg = src[src.index('def %s(' % name):]
    return seg[:seg.index('\n    def ')] if '\n    def ' in seg else seg


def test_three_key_saves_report_failure():
    src = io.open(PET, encoding='utf-8').read()
    for fn in ('_save_todos', '_save_reminders', '_summarize_old'):
        assert '_silent_log' in _fn_seg(src, fn), '⭐ %s 的失败必须留痕 ✗' % fn
    for fn in ('_save_todos', '_save_reminders'):
        assert '_notify' in _fn_seg(src, fn), '⭐ %s 失败应对用户可见 ✗' % fn


# ── 5. ⭐ 合理兜底**保持不动**（不得被“修”成弹窗/报错 ✗）──────────────
def test_reasonable_fallbacks_untouched():
    """解析/UI/主题类兜底保留 ✓ —— 防以后有人一律加弹窗把体验搞坏 ✗。"""
    src = io.open(PET, encoding='utf-8').read()
    seg = _fn_seg(src, '_parse_rerank_ids')
    assert 'except Exception' in seg, '解析函数应保留兜底 ✓'
    assert '_notify' not in seg, '⛔ 解析兜底不该弹窗（会被噪声淹 ✗）'
