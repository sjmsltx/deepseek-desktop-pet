# -*- coding: utf-8 -*-
"""⭐ A2/D6-2 护栏：首屏起手区（＋ ⭐ A3/D6-1 首次向导）

缺陷原形 ✗：首屏**全是"看"**（页签／面板／矩阵／待办）→ **不知道从哪开始一件事** ✗；
            多模型／圆桌被当成**前置门槛** ✗；空面板**无指引** ✗。

本护栏钉住的**契约**（写行为，不写死实现细节 ✓）：
    ① 首屏必须有**起手区**：容器 ＋ 主输入框 ＋ 发起按钮 ✓（⛔ 缺一不可 ✗）
    ② ⭐ **默认「单点」**——**不选任何模型也能发起** ✓（＝多模型从门槛降为**可选项** ✓）
    ③ 圆桌若**还没上线**，控件必须**禁用 ＋ 写明原因** ✓（⛔ 不许"能点但没反应" ✗）
    ④ 三个面板的空态都必须有**「下一步做什么」** ✓（⛔ 不许一片空白 ✗）
    ⑤ 首次向导：**5 步齐备** ＋ **可跳过** ✓（⛔ 不许挡路 ✗）
    ⑥ 服务未连上 → 起手区**禁用** ＋ **写明原因** ＋ 给**重试探测** ✓（⛔ 不静默 ✗）
    ⑦ ⛔ **不新增端点** ✗：起手区只允许用**已有**端点（`/api/interrupt`、`/api/step`）✓

有牙证明（本文件自测 ✓）：6 种"把护栏拿掉"的篡改逐个断言**必须判红** ✓
用法:
    python tests/test_collab_starter.py --report
    python tests/test_collab_starter.py --selftest
"""
from __future__ import annotations

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
HTML = os.path.join(REPO, 'collab', 'index.html')

# ⭐ 端点白名单：起手区的"发起"只允许复用这两个既有端点（⛔ 不新增 ✗）
ALLOWED = {'/api/interrupt', '/api/step'}


def read_html(path: str = HTML) -> str:
    with io.open(path, encoding='utf-8') as fh:
        return fh.read()


def _starter_region(html: str) -> str:
    """截取起手区/向导的**实现段**（`var GUIDE_KEY` … 下一个同级 function）——只查这一段 ✓

    ⚠️ 自纠（2026-10-04）：第一版用标记 `A2/D6-2` 定位 ✗ → 命中的是**HTML 注释**（更早）✗
    → 把连接灯的 `/api/health` 也圈进来 → 白名单误报 ✗（**跛脚护栏** ✗）→ 改用唯一代码锚点 ✓
    """
    i = html.find('var GUIDE_KEY')
    if i < 0:
        return ''
    j = html.find('\n  function avatarText', i)
    return html[i:j if j > i else i + 20000]


def check(html: str) -> list:
    bad = []

    # ① 起手区三件套
    for eid, name in (('starter', '起手区容器'), ('starter-input', '主输入框'), ('starter-send', '发起按钮')):
        if 'id="%s"' % eid not in html:
            bad.append('缺%s（#%s）✗ —— 首屏就没有"开始一件事"的入口 ✗' % (name, eid))

    # ② 默认单点（核心契约：不选模型也能发起）
    m = re.search(r'<span[^>]*id="starter-mode-single"[^>]*>', html)
    if not m:
        bad.append('缺"单点（默认）"选项 ✗')
    elif not re.search(r'class="on"', m.group(0)) or 'data-mode="single"' not in m.group(0):
        bad.append('⭐ 默认参与范围不是「单点」✗ —— 这会把多模型变成前置门槛 ✗')

    # ③ 圆桌未上线 → 禁用 ＋ 写明原因
    m2 = re.search(r'<span[^>]*id="starter-mode-round"[^>]*>', html)
    if m2:
        tag = m2.group(0)
        if 'class="on"' in tag:
            bad.append('圆桌被写成默认态 ✗（默认必须单点 ✓）')
        if 'off' not in tag:
            bad.append('圆桌控件未标记为禁用/不可用 ✗ —— 会"能点但没反应" ✗')
        if not re.search(r'title="[^"]{4,}"', tag):
            bad.append('圆桌禁用**未写明原因** ✗（⛔ 不静默 ✗）')
    else:
        bad.append('缺圆桌选项占位 ✗（B 阶段要上线，先留位并写明 ✓）')

    # ④ 空面板指引 ×3（L1 / L2 / L3）
    n_how = len(re.findall(r'howEmpty\(', html))
    if n_how < 4:      # 1 处定义 + 3 处调用
        bad.append('空面板"下一步做什么"不足 3 处 ✗（实测调用 %d 处）—— 空白面板＝用户不知道下一步 ✗' % max(0, n_how - 1))

    # ⑤ 首次向导：5 步 ＋ 可跳过
    for t in ('起服务', '选模型', '选工作区', '写第一条任务', '看投递'):
        if t not in html:
            bad.append('向导缺步骤「%s」✗' % t)
    if 'id="guide-skip"' not in html:
        bad.append('向导无"跳过"✗（⛔ 不许挡路 ✗）')
    if not re.search(r'<div class="guide" id="guide" hidden>', html):
        bad.append('向导默认未隐藏 ✗（首次才显示 ✓）')

    # ⑥ 未连上 → 禁用 ＋ 原因 ＋ 重试
    reg = _starter_region(html)
    if 'id="conn-banner-why"' not in html:
        bad.append('未连上时**没有原因位** ✗（⛔ 不静默 ✗）')
    if 'id="conn-retry"' not in html:
        bad.append('未连上时无「重试探测」✗')
    if not re.search(r'setStarter\(\s*kind\s*===\s*\'ok\'\s*,', html):
        bad.append('连接态**没有驱动起手区禁用** ✗（未连上还敢让用户点发起 ✗）')

    # ⑦ 端点白名单
    for u in sorted(set(re.findall(r"['\"](/api/[A-Za-z0-9_\-/\.]*)['\"]", reg))):
        if u not in ALLOWED:
            bad.append('起手区出现白名单外端点 %s ✗（⛔ 不得为起手区新增端点 ✗）' % u)

    # ⑦ ⭐ hidden 必须真的生效（实测踩坑：`.banner{display:flex}` 优先级高于 `[hidden]` ✗）
    if '.banner[hidden]' not in html:
        bad.append('⛔ `.banner[hidden]` 未显式声明 ✗ —— `display:flex` 会盖掉 `hidden` → '
                   '服务明明在跑、“服务没在跑”横条却一直显示 ✗（已实测踩过 ✓）')

    return bad


def _mutations(html: str) -> list:
    out = []
    out.append(('删掉主输入框', html.replace('id="starter-input"', 'id="starter-input-x"', 1)))
    out.append(('把默认参与改成圆桌', html.replace('class="on" data-mode="single"', 'class="off" data-mode="single"', 1)))
    out.append(('删掉"未连上"原因位', html.replace('id="conn-banner-why"', 'id="conn-banner-why-x"', 1)))
    out.append(('删掉向导"跳过"', html.replace('id="guide-skip"', 'id="guide-skip-x"', 1)))
    out.append(('换成白名单外端点', html.replace("post('/api/interrupt'", "post('/api/startturn'", 1)))
    out.append(('拿掉一个空面板指引', html.replace('howEmpty(', 'howEmptyX(', 1)))
    out.append(('拿掉 hidden 生效规则', html.replace('.banner[hidden]', '.banner[hidden-x]', 1)))
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


def test_starter_契约满足():
    bad = check(read_html())
    assert not bad, 'A2/D6-2 起手区护栏判红：\n  - ' + '\n  - '.join(bad)


def test_starter_有牙证明():
    html = read_html()
    for name, mut in _mutations(html):
        assert mut != html, '篡改未生效（测试自身需修）：%s' % name
        assert check(mut), '无牙：篡改后仍全绿 → %s' % name


if __name__ == '__main__':
    sys.exit(main())
