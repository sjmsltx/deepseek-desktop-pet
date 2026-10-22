# -*- coding: utf-8 -*-
"""⭐ C4 护栏：术语一致（D5-4）

缺陷原形 ✗：⭐ 界面文案用 **V1/V2/V3**（群聊流／投递轨道／后台总线 ✓），
而内部与契约写作 **L1/L2/L3**（`data-view`／`data-panel` ✓）—— ⭐ **两套术语并存** ✗
＋ ⭐ **不止一个"刷新"**（分不清刷的是哪块 ✓）。

本护栏钉住的契约：
    ① ⭐ 界面必须有**术语对照**（V ↔ L 说清"是同一件事 ✓"）✗ 不能说半截 ✓
    ② ⭐ 每个"刷新"类按钮必须**带范围词**（刷新什么 ✓）—— ⛔ 不许两个都叫"刷新" ✗
    ③ ⭐ 对照必须**可被机器验证**（判据不靠口感 ✓）
"""
from __future__ import annotations

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
HTML = os.path.join(REPO, 'collab', 'index.html')


def read_html(path: str = HTML) -> str:
    with io.open(path, encoding='utf-8') as fh:
        return fh.read()


def check(html: str) -> list:
    bad = []

    # ① 术语对照行
    m = re.search(r'<div[^>]*id="term-map"[^>]*>(.*?)</div>', html, re.S)
    if not m:
        bad.append('缺术语对照行（#term-map）✗ —— ⛔ 两套术语并存且没人说清 ✗')
    else:
        txt = m.group(1)
        for k in ('V1', 'V2', 'V3', 'L1', 'L2', 'L3'):
            if k not in txt:
                bad.append('术语对照缺 %s ✗（V 与 L 必须都写 ✓）' % k)
        if '术语对照' not in txt and '同一件事' not in txt:
            bad.append('术语对照未说"是同一件事"✗ —— 只列两套等于没解释 ✓')

    # ② 刷新类按钮必须各有范围
    labels = re.findall(r'<button[^>]*id="(?:btn-refresh|mx-refresh|conn-retry)"[^>]*>([^<]*)<', html)
    if len(labels) < 2:
        bad.append('找不到两个"刷新类"按钮（#btn-refresh／#mx-refresh）✗')
    cleaned = [re.sub(r'[⟳\s]', '', l) for l in labels]
    if len(set(cleaned)) != len(cleaned):
        bad.append('两个刷新按钮**文案相同** ✗（分不清刷哪块 ✓）：%r' % labels)
    for l in cleaned:
        if len(l) <= 3:
            bad.append('刷新按钮"%s"**未带范围词** ✗（如"刷新投递"／"重新读取资产" ✓）' % l)

    return bad


def _mutations(html: str) -> list:
    out = []
    out.append(('删掉术语对照行', html.replace('id="term-map"', 'id="term-map-x"')))
    out.append(('把两个刷新按钮改成同名',
                html.replace('⟩刷新投递（V1/V2/V3）', '⟩刷新').replace('>⟳ 重新读取资产<', '>⟳ 刷新<')))
    out.append(('对照行里抽掉 L 半边', html.replace('<b>L1</b>', '<b>?1</b>')))
    return out


def selftest() -> int:
    html = read_html()
    fails = 0
    base = check(html)
    print('基线：%s' % ('全绿 ✓' if not base else '有 %d 条问题 ✗' % len(base)))
    for line in base:
        print('   ✗ %s' % line)
    if base:
        fails += 1
    for name, mut in _mutations(html):
        if mut == html:
            print('   ⚠️ 篡改 "%s" 未生效 ✗ —— 测试自身需修' % name)
            fails += 1
            continue
        got = check(mut)
        print(('   ✓ 有牙：%s → 判红 %d 条' % (name, len(got))) if got
              else ('   ✗ 无牙：%s → 竟然全绿 ✗' % name))
        if not got:
            fails += 1
    print('\n自测结果：%s' % ('通过 ✓' if not fails else '不通过 ✗（%d 项）' % fails))
    return 1 if fails else 0


def main() -> int:
    if '--selftest' in sys.argv:
        return selftest()
    html = read_html()
    bad = check(html)
    if '--report' in sys.argv or not bad:
        print('检查文件：%s' % HTML)
        print('问题 %d 条' % len(bad))
        for line in bad:
            print('  ✗ %s' % line)
    return 1 if bad else 0


def test_terms_契约满足():
    bad = check(read_html())
    assert not bad, 'C4 术语护栏判红：\n  - ' + '\n  - '.join(bad)


def test_terms_有牙证明():
    html = read_html()
    for name, mut in _mutations(html):
        assert mut != html, '篡改未生效（测试自身需修）：%s' % name
        assert check(mut), '无牙：篡改后仍全绿 → %s' % name


if __name__ == '__main__':
    sys.exit(main())
