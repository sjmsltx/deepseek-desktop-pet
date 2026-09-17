# -*- coding: utf-8 -*-
"""v6.57 / A1：主题 token 唯一源 + "硬编码颜色只减不增"护栏。

背景
----
主题 token 原先内联在 desktop_pet.py（DEFAULT_THEME），而 settings_ui.py 又另写了一套
配色（`#14161f` / `rgba(255,255,255,0.05)` 等）——"主题源不唯一"。后果：AI 想改外观时
该走主题的地方未必有 token，去改源码又定位不准（提示词还谎称"所有颜色都在主题系统里"）。

本测试锁住三件事：
  1. 唯一源 `pet_theme.py` 存在，且 `desktop_pet.py` 不再内联 DEFAULT_THEME；
  2. token 表自身合法（值非空、TOKEN_GROUPS 引用有效、无未归类 token）；
  3. 各模块的硬编码颜色**只减不增**（ratchet，对照 tests/golden/theme_hardcoded_baseline.json）。

用法：
    python -m pytest tests/test_theme_tokens.py -q
    python tests/test_theme_tokens.py capture     # 重新采集基线（仅在确认数量减少后使用）
    python tests/test_theme_tokens.py list        # 打印当前硬编码颜色清单（A2 迁移用）
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(ROOT, 'tests', 'golden', 'theme_hardcoded_baseline.json')
sys.path.insert(0, ROOT)

HEX = re.compile(r'#[0-9a-fA-F]{3,8}\b')
RGBA = re.compile(r'\brgba?\s*\(')  # theme-exempt（本行是护栏自身的正则）

# 这些文件允许出现颜色字面量：唯一源本身 / system prompt 里的示例 / 工具描述文档
ALLOW_FILES = {'pet_theme.py', 'prompt_builder.py', 'tools_registry.py', 'test_theme_tokens.py',
               'regression_test.py'}
SKIP_DIRS = {'__pycache__', 'backup', 'build', 'dist', 'release_build', 'logs',
             '.git', '.pytest_cache', 'screenshots', '视频介绍', 'tests'}
# 说明：tests/ 不在护栏范围内——测试需要写颜色字面量来断言主题色（夹具不算产品代码）。


def _iter_py():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith('.py'):
                yield os.path.join(dirpath, fn)


def _hit(line):
    s = line.strip()
    if s.startswith('#'):
        return False
    if 'theme-exempt' in line:      # 显式豁免标记
        return False
    return bool(HEX.search(line) or RGBA.search(line))


def scan(detail=False):
    """扫描项目内硬编码颜色。返回 {相对路径: 行数}；detail=True 时返回明细列表。"""
    counts, rows = {}, []
    for path in _iter_py():
        rel = os.path.relpath(path, ROOT).replace('\\', '/')
        if os.path.basename(rel) in ALLOW_FILES:
            continue
        try:
            lines = open(path, encoding='utf-8', errors='replace').read().splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines, 1):
            if _hit(line):
                counts[rel] = counts.get(rel, 0) + 1
                if detail:
                    rows.append((rel, i, line.strip()[:110]))
    return rows if detail else counts


# --------------------------------------------------------------------------
# 测试
# --------------------------------------------------------------------------
def test_single_source_exists():
    assert os.path.exists(os.path.join(ROOT, 'pet_theme.py')), '缺少唯一源 pet_theme.py'
    src = open(os.path.join(ROOT, 'desktop_pet.py'), encoding='utf-8-sig').read()
    assert 'DEFAULT_THEME = {' not in src, \
        'desktop_pet.py 不应再内联 DEFAULT_THEME（唯一源已迁到 pet_theme.py）'


def test_tokens_valid():
    from pet_theme import DEFAULT_THEME, TOKEN_GROUPS
    for k, v in DEFAULT_THEME.items():
        assert isinstance(v, str) and v.strip(), f'token {k} 的值不是非空字符串'
    for grp, keys in TOKEN_GROUPS.items():
        for k in keys:
            assert k in DEFAULT_THEME, f'TOKEN_GROUPS[{grp}] 引用了不存在的 token：{k}'
    grouped = {k for keys in TOKEN_GROUPS.values() for k in keys}
    missing = sorted(set(DEFAULT_THEME) - grouped)
    assert not missing, f'以下 token 未归入任何 TOKEN_GROUPS 分组：{missing}'


def test_settings_dialog_uses_tokens():
    """设置窗口不得再有硬编码颜色（v6.57 前它有 14 处，是"第二套主题"）。"""
    path = os.path.join(ROOT, 'settings_ui.py')
    src = open(path, encoding='utf-8-sig').read()
    assert 'from pet_theme import DEFAULT_THEME' in src, 'settings_ui.py 应从唯一源取色'
    bad = [(i, l.strip()[:90]) for i, l in enumerate(src.splitlines(), 1) if _hit(l)]
    assert not bad, f'settings_ui.py 仍有硬编码颜色：{bad[:5]}'


def test_prompt_points_to_token_source():
    src = open(os.path.join(ROOT, 'prompt_builder.py'), encoding='utf-8-sig').read()
    assert 'pet_theme.py' in src, 'system prompt 必须告诉 AI：token 唯一源是 pet_theme.py'
    assert '只有 pet_theme.py 里确实没有对应 token 时' in src, \
        'prompt 必须诚实说明"没有 token 时才允许改源码"（否则 AI 会瞎猜）'


def test_no_new_hardcoded_colors():
    """ratchet：任何文件的硬编码颜色都不允许增加（A2 完成后应为 0）。"""
    if not os.path.exists(BASELINE):
        raise AssertionError(f'缺少基线文件 {BASELINE}（用 capture 生成）')
    base = json.load(open(BASELINE, encoding='utf-8'))['files']
    cur = scan()
    worse = {f: {'基线': base.get(f, 0), '现在': n}
             for f, n in sorted(cur.items()) if n > base.get(f, 0)}
    total_base, total_cur = sum(base.values()), sum(cur.values())
    print(f'[theme] 硬编码颜色：基线 {total_base} → 现在 {total_cur}')
    assert not worse, f'硬编码颜色增加了（只减不增）：{worse}'


def test_all_used_token_keys_exist():
    """主题取色助手引用到的 token 键必须都在唯一源里定义。

    防拼写错误（例如 `_T('ui_hint_dark')` 写了个不存在的键）——那会静默回退成洋红兜底色。
    注意：只查**主题取色助手**（`_T` / `_tk` / `pet_theme.color` / 显式 `color as T` 的别名），
    不查应用里的翻译函数 `T()`（i18n）与 Qt 的 `.color()`。"""
    from pet_theme import DEFAULT_THEME
    checked = 0
    missing = {}
    for path in _iter_py():
        rel = os.path.relpath(path, ROOT).replace('\\', '/')
        try:
            src = open(path, encoding='utf-8', errors='replace').read()
        except Exception:
            continue
        aliases = ['_T', '_tk']
        m = re.search(r'from pet_theme import[^\n]*\bcolor as (\w+)', src)
        if m:
            aliases.append(m.group(1))
        if 'import pet_theme' in src:
            aliases.append('pet_theme.color')
        pats = [r'\b%s\(\s*[\'\"]([a-z0-9_]+)[\'\"]' % re.escape(a) for a in aliases]
        keys = set()
        for pat in pats:
            keys |= set(re.findall(pat, src))
        keys = {k for k in keys if not k.startswith('__')}
        if not keys:
            continue
        checked += len(keys)
        bad = sorted(k for k in keys if k not in DEFAULT_THEME)
        if bad:
            missing[rel] = bad
    assert checked > 20, '护栏没扫到取色助手调用（别名识别可能失效）：%d' % checked
    assert not missing, f'引用了未定义的 token（会渲染成洋红兜底色）：{missing}'


def test_product_code_has_no_hardcoded_colors():
    """A2 完成后：**产品代码里不允许再有硬编码颜色**（0 处）。

    例外只允许两类，且必须在 pet_theme.py 里（唯一源）或以 # theme-exempt 显式豁免：
    角色档案数据、system prompt 里的示例、护栏自身的正则。"""
    cur = scan()
    assert not cur, f'产品代码仍有硬编码颜色（A2 目标为 0）：{cur}'


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _capture():
    counts = scan()
    os.makedirs(os.path.dirname(BASELINE), exist_ok=True)
    payload = {'note': 'A1 基线：迁移前各文件硬编码颜色数量（只减不增）',
               'files': dict(sorted(counts.items())),
               'total': sum(counts.values())}
    with open(BASELINE, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f'已写入基线 {BASELINE}')
    for f, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f'  {f:<24} {n:>3}')
    print(f'  合计 {sum(counts.values())}')


def _list():
    rows = scan(detail=True)
    for rel, i, s in rows:
        print(f'{rel}:{i}  {s}')
    print(f'共 {len(rows)} 处')


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'list'
    if cmd == 'capture':
        _capture()
    else:
        _list()
