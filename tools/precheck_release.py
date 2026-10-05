# -*- coding: utf-8 -*-
"""tools/precheck_release.py —— ⭐ 阶段 D-4「发布前检查」（可反复跑 ✓ 只读 ✓）

⭐ 口径（路线图 D-4 ✓）：⭐ **打包隔离 ✓ ／ 敏感参数不内置 ✓ ／ 隐私不泄露 ✓ ／ 仓库干净 ✓ ／ 文档齐 ✓**
⭐ 纪律：⛔ **只读** ✗（不删不改不打包 ✗）；⭐ 每一项都给**原始命中行**（⛔ 不打印"应该没问题" ✗）

用法:
    python tools\\precheck_release.py                # 扫默认仓库 ✓
    python tools\\precheck_release.py --base . --strict  # 仓库必须干净（发布时用 ✓）
退出码：0 = 全绿 ✓ ｜ 1 = 有需人工确认项 ✗ ｜ 2 = 有硬缺陷（敏感/隐私命中）✗
"""
from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ⭐ 敏感/隐私模式（⛔ 命中即硬缺陷 ✗）—— 允许显式登记的例外 ✓
SECRET_PATTERNS = [
    (r'sk-[A-Za-z0-9]{16,}', '疑似 API Key（sk-…）'),
    (r'(?i)api[_-]?key\s*[=:]\s*[\'"][^\'"\s]{12,}[\'"]', '疑似硬编码 api_key'),
    (r'(?i)(secret|passwd|password)\s*[=:]\s*[\'"][^\'"\s]{8,}[\'"]', '疑似硬编码口令'),
    (r'(?i)bearer\s+[A-Za-z0-9\-_\.]{20,}', '疑似 Bearer token'),
]
PRIVACY_PATTERNS = [
    (r'李滨宇', '真实姓名（中文）'),
    (r'lby13', '本机用户名'),
    (r'[0-9]{5,}@qq\.com', 'QQ 邮箱（应用 GitHub noreply ✓）'),
    (r'[A-Za-z]:\\\\?Users\\\\?[A-Za-z0-9_.-]+', '本机绝对路径'),
]
ALLOWLIST = [
    # ⭐ 显式登记：这些出现在"应当出现"的地方（示例/说明 ✓），不算缺陷
    r'tools/precheck_release\.py',
    r'tests/test_precheck_release\.py',
]


def sh(base, *args):
    try:
        # ⭐ `core.quotepath=false` —— 否则中文路径会被 git 转义输出 ✗（实测：契约文件“找不到”✗）
        p = subprocess.run(['git', '-c', 'core.quotepath=false'] + list(args), cwd=base,
                           capture_output=True, text=True, timeout=40, encoding='utf-8', errors='replace')
        return p.stdout
    except Exception as e:
        return 'ERR %r' % e


def tracked(base):
    out = sh(base, 'ls-files')
    return [f for f in out.splitlines() if f.strip()]


def scan(base, files, patterns, skip_allow=True):
    hits = []
    for rel in files:
        if skip_allow and any(re.search(a, rel) for a in ALLOWLIST):
            continue
        p = os.path.join(base, rel)
        try:
            txt = io.open(p, encoding='utf-8', errors='ignore').read()
        except Exception:
            continue
        for pat, label in patterns:
            for m in re.finditer(pat, txt):
                ln = txt[:m.start()].count('\n') + 1
                hits.append((rel, ln, label, m.group(0)[:60]))
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default=REPO)
    ap.add_argument('--strict', action='store_true', help='仓库必须干净（发布时 ✓）')
    a = ap.parse_args()
    base = os.path.abspath(a.base)
    files = tracked(base)
    print('=== 阶段 D-4 发布前检查 | %s | 被跟踪文件 %d ===' % (base, len(files)))
    hard = []
    soft = []

    # ① 仓库干净
    dirty = [l for l in sh(base, 'status', '--porcelain').splitlines() if l.strip()]
    ok = (not dirty) if a.strict else True
    print('  %s ① 仓库干净            %s' % ('✓' if (not dirty) else ('✗' if a.strict else '⚠️'),
                                             '干净 ✓' if not dirty else '%d 处未提交（协作中属正常 ✓ strict 下算未通过 ✗）' % len(dirty)))
    if dirty and a.strict:
        hard.append('仓库有未提交改动（strict ✓）')

    # ② 敏感参数不内置
    hits = scan(base, files, SECRET_PATTERNS)
    print('  %s ② 无硬编码敏感参数      %s' % ('✓' if not hits else '✗', '%d 处' % len(hits)))
    for f, ln, lab, s in hits[:8]:
        print('       %s:%d  %s  %s' % (f, ln, lab, s))
        hard.append('%s:%d %s' % (f, ln, lab))

    # ③ 隐私不泄露
    ph = scan(base, files, PRIVACY_PATTERNS)
    print('  %s ③ 无隐私泄露            %s' % ('✓' if not ph else '✗', '%d 处' % len(ph)))
    for f, ln, lab, s in ph[:8]:
        print('       %s:%d  %s  %s' % (f, ln, lab, s))
        hard.append('%s:%d %s' % (f, ln, lab))

    # ④ 打包隔离（产物不进 git ✓）—— ⚠️ 自纠：`.spec` 是**构建配置** ✓ 应当入库 ✓（实测它并不含本机路径 ✓）
    #    ⇒ ⛔ 只报真产物 ✗（`dist/` `build/` `release_build/` `*.exe` `*.zip` ✓）
    tracked_release = [f for f in files
                       if f.startswith(('release_build/', 'dist/', 'build/'))
                       or re.search(r'\.(exe|zip|msi|7z|tar\.gz)$', f)]
    print('  %s ④ 打包产物未入库        %s' % ('✓' if not tracked_release else '✗', '%d 个' % len(tracked_release)))
    if tracked_release:
        soft.append('打包产物被跟踪：%s' % tracked_release[:3])

    # ⑤ 文档齐备
    need = ['README.md', 'CHANGELOG.md']
    miss = [n for n in need if not os.path.isfile(os.path.join(base, n))]
    print('  %s ⑤ 文档齐备              %s' % ('✓' if not miss else '⚠️', '缺 %s' % miss if miss else 'README/CHANGELOG ✓'))
    if miss:
        soft.append('缺文档：%s' % miss)
    lic = [f for f in files if os.path.basename(f).upper().startswith('LICENSE')]
    print('    %s LICENSE                %s' % ('✓' if lic else '⚠️', lic[0] if lic else '未找到（若计划开源则需补 ✓）'))

    # ⑥ 临时垃圾未入库
    junk = [f for f in files if re.search(r'(_tmp|\.tmp$|\.log$|__pycache__|\.pyc$)', f)]
    print('  %s ⑥ 无临时垃圾入库        %s' % ('✓' if not junk else '⚠️', '%d 个' % len(junk)))
    if junk:
        soft.append('临时文件被跟踪：%s' % junk[:3])

    # ⑦ 契约在位
    ct = [f for f in files if 'API契约' in f or '契约' in f]
    print('  %s ⑦ 契约文件在位          %s' % ('✓' if ct else '⚠️', ct[0] if ct else '未找到'))

    print('\n=== 结论 ===')
    if hard:
        print('✗ 硬缺陷 %d 条（必须处理后再发布 ✗）：' % len(hard))
        for h in hard:
            print('   ✗ %s' % h)
        return 2
    if soft:
        print('⚠️ 需人工确认 %d 条（不一定阻断 ✓）：' % len(soft))
        for s in soft:
            print('   ⚠️ %s' % s)
        return 1
    print('⭐ 全绿 ✓ 可进入发布流程 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main())
