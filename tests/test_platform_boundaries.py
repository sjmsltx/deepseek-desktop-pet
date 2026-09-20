# -*- coding: utf-8 -*-
"""平台边界守护（v6.73 批次 3）：调用方**不得直连平台接口**，一律走 platform_layer。

为什么要有这条：抽象层的价值全靠"没有旁路"维持 —— 只要有一个调用点直连
`ctypes.windll.user32.*` / `winsound` / `os.startfile`，跨平台迁移与能力探测就不再可信。
（与项目既有的"硬编码颜色只减不增"护栏同一思路：把架构约束钉成测试。）

例外：行尾写 `# platform-exempt` 表示有意豁免（请在同一行说明理由）。
"""
import os
import re

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 文件 → 禁止出现的调用模式（正则，已避开 pl.* 与 def 行）
FORBIDDEN = {
    'desktop_pet.py': [
        r'\bos\.startfile\(',
        r'(?<![\w.])winsound\.',
        r'ctypes\.windll\.user32\.',
        r'(?<![\w.])fgwin\.',
        r'(?<![\w.])ocr_image\(',
        r'(?<![\w.])_open_url\(',
        r'(?<![\w.])_open_shell_target\(',
        r'(?<![\w.])_read_clipboard_text\(',
        r'(?<![\w.])_write_clipboard_text\(',
        r'(?<!def )(?<![\w.])_hotkey_filter_factory\(',
    ],
    'settings_ui.py': [r'(?<![\w.])fgwin\.', r'ctypes\.windll\.user32\.'],
    'tools_executor.py': [r'ctypes\.windll\.user32\.', r'(?<![\w.])winsound\.'],
}


def _scan_text(text, pattern):
    """纯文本扫描（便于对"豁免行/合法路径"做反向测试）"""
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        if 'platform-exempt' in line:
            continue
        stripped = line.strip()
        if stripped.startswith('#'):
            continue
        if re.search(pattern, line):
            hits.append((i, stripped[:110]))
    return hits


def _scan(name, pattern):
    path = os.path.join(BASE, name)
    if not os.path.isfile(path):
        return []
    with open(path, encoding='utf-8', errors='ignore') as f:
        return _scan_text(f.read(), pattern)


@pytest.mark.parametrize('name', sorted(FORBIDDEN))
def test_callers_go_through_platform_layer(name):
    bad = []
    for pat in FORBIDDEN[name]:
        for lineno, line in _scan(name, pat):
            bad.append(f'{name}:{lineno} 命中 {pat} → {line}')
    assert not bad, '调用方直连了平台接口，请改走 platform_layer：\n  ' + '\n  '.join(bad)


@pytest.mark.parametrize('name', ['desktop_pet.py', 'settings_ui.py', 'tools_executor.py'])
def test_callers_import_platform_layer(name):
    path = os.path.join(BASE, name)
    if not os.path.isfile(path):
        pytest.skip('文件不存在')
    src = open(path, encoding='utf-8', errors='ignore').read()
    assert 'import platform_layer as pl' in src, f'{name} 应 import platform_layer 走统一门面'


def test_capability_keys_are_reported():
    """能力清单必须如实（13 项），且都带 via 说明"""
    import sys
    if BASE not in sys.path:
        sys.path.insert(0, BASE)
    import platform_layer as pl
    caps = pl.capabilities()
    assert len(caps) == 13, f'能力项数变了：{sorted(caps)}'
    for key, info in caps.items():
        assert info['via'] in ('module', 'host', 'unavailable'), key
    # 报告里应能看出"经谁实现"
    rep = pl.report()
    for key in caps:
        assert key in rep


# ---------------------------------------------------------------- 反向测试（防守护被稀释）

def test_scanner_flags_real_direct_call():
    """正向：真·直连必须被抓到"""
    text = 'os.startfile(target)\nctypes.windll.user32.LockWorkStation()\n'
    assert len(_scan_text(text, r'\bos\.startfile\(')) == 1
    assert len(_scan_text(text, r'ctypes\.windll\.user32\.')) == 1


def test_scanner_allows_layer_calls():
    """合法路径：走平台抽象层的调用不该被抓（否则谁都不敢动）"""
    text = 'pl.open_path(target)\npl.lock_screen()\npl.beep("msg")\npl.ocr_image(p, PS1)\n'
    for pat in (r'\bos\.startfile\(', r'(?<![\w.])winsound\.', r'ctypes\.windll\.user32\.',
                r'(?<![\w.])ocr_image\('):
        assert _scan_text(text, pat) == [], pat


def test_exempt_marker_is_honored():
    """豁免：行尾带 `# platform-exempt` 且有理由 → 放行（但必须留理由，见 HANDOFF 豁免清单）"""
    text = 'os.startfile(target)  # platform-exempt: 平台专用，已在 HANDOFF 登记\n'
    assert _scan_text(text, r'\bos\.startfile\(') == []


def test_comment_lines_are_ignored():
    text = '# os.startfile(x) —— 注释里的例子不算违规\n'
    assert _scan_text(text, r'\bos\.startfile\(') == []
