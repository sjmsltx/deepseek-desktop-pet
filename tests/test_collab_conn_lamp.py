# -*- coding: utf-8 -*-
"""⭐ D6-5 护栏：协作台「服务连接」小灯（🟢 在跑 / 🔴 未连上（含原因）/ ⚪ 未探测）

为什么需要（缺陷原形 ✗）：
    服务没在跑时，页面**能打开、一切为空、用户不知为何** ✗
    —— 这就是 Owner 本次体感的直接原因 ✓（服务不在跑 ＋ 页面是旧标签页 ✓）

本护栏钉住的**契约**（写行为，不写死实现细节 ✓）：
    ① 页面必须有常驻连接灯元素，且**默认态＝未探测** ✓（⛔ 不许一上来就假装"在跑" ✗）
    ② 三态齐备：🟢 在跑 ／ 🔴 未连上 ／ ⚪ 未探测 ✓
    ③ 数据源只能用**已冻结的只读端点** `/api/health` ✓（⛔ 不许为灯新增端点 ✗ 守契约 C1）
    ④ 🔴 态**必须带原因** ✓（⛔ 静默＝缺陷本身 ✗）—— 不许把 reason 写成空串/固定占位
    ⑤ 探测必须**有超时** ✓ ＋ **防重入** ✓（否则服务卡住时会堆积请求 ✗，与"DSH 占主线程"同族）

有牙证明（本文件自测 ✓）：对 5 种"把护栏拿掉"的篡改逐个断言**必须判红** ✓
用法:
    python tests/test_collab_conn_lamp.py --report     # 人工看清单
"""
from __future__ import annotations

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
HTML = os.path.join(REPO, 'collab', 'index.html')

# ⭐ 端点白名单：灯的探测**只允许**用这些（都是已冻结的只读端点 ✓）
ALLOWED_HEALTH = '/api/health'


def read_html(path: str = HTML) -> str:
    with io.open(path, encoding='utf-8') as fh:
        return fh.read()


def check(html: str) -> list:
    """返回问题清单（空列表＝全绿 ✓）。"""
    bad = []

    # ① 元素存在 ＋ 默认态＝未探测
    m = re.search(r'<span[^>]*id="conn"[^>]*>', html)
    if not m:
        bad.append('缺连接灯元素 #conn ✗')
    else:
        tag = m.group(0)
        if 'data-conn="probing"' not in tag:
            bad.append('连接灯默认态不是 probing（未探测）✗ —— ⛔ 不许一上来就假装"在跑" ✗')
        if 'data-reason=' not in tag:
            bad.append('连接灯缺 data-reason 初值 ✗（无法区分"没探过"与"探测结果为空" ✗）')

    # ② 三态齐备
    for icon, name in (('🟢', '服务在跑'), ('🔴', '未连上'), ('⚪', '未探测')):
        if icon not in html or name not in html:
            bad.append('缺状态 %s %s ✗' % (icon, name))

    # ③ 数据源＝已冻结的只读端点；⛔ 不许新增端点
    if ALLOWED_HEALTH not in html:
        bad.append('未使用 %s 作数据源 ✗' % ALLOWED_HEALTH)
    lamp = _lamp_region(html)
    for u in set(re.findall(r"['\"](/api/[A-Za-z0-9_\-/\.]*)['\"]", lamp)):
        if u != ALLOWED_HEALTH:
            bad.append('灯的实现里出现了白名单外端点 %s ✗（⛔ 不得为灯新增端点 ✗）' % u)

    # ④ 🔴 必须带原因：setConn('down', <非空表达式>)
    down_calls = re.findall(r"setConn\(\s*'down'\s*,\s*([^;]{0,120})\)", lamp)
    if not down_calls:
        bad.append("没有 setConn('down', …) 调用 ✗ —— 连不上时无处落原因 ✗")
    for arg in down_calls:
        if re.fullmatch(r"\s*(''|\"\"|'\s*')\s*", arg or ''):
            bad.append("setConn('down', 空串) ✗ —— 这正是「静默」缺陷本身 ✗")
        if re.search(r"'[^']*未连上[^']*'", arg or '') and 'why' not in (arg or ''):
            bad.append('🔴 的原因被写成固定文案（无变量）✗ —— 用户仍看不到真因 ✗')
    # 捕获分支里必须**派生**出原因（超时 / HTTP 码 / fetch 失败原因）
    if not re.search(r"AbortError", lamp):
        bad.append('未区分"探测超时"✗ —— 超时与"服务没跑"必须可辨别 ✓')
    if not re.search(r"e\.message", lamp):
        bad.append('未把 fetch 失败原因带出来 ✗')

    # ⑤ 超时 ＋ 防重入
    if not re.search(r'AbortController', lamp):
        bad.append('探测无超时机制 ✗（服务卡住 → 灯永远停在旧态 ✗）')
    if not re.search(r'_busy', lamp):
        bad.append('探测无防重入 ✗（服务卡住时会堆积请求 ✗）')

    return bad


def _lamp_region(html: str) -> str:
    """截取**探测函数体**（`probeConn` … 下一个同级 function）——只查灯自己的实现 ✓

    ⚠️ 自纠（2026-10-04）：第一版从 `CONN_TEXT` 截到 `setInterval` ✗ → 把整段界面代码都圈进来
    → 满屏"白名单外端点"误报 ✗（**跛脚护栏** ✗）→ 改成只截 `probeConn` 函数体 ✓
    """
    i = html.find('function probeConn(')
    if i < 0:
        return ''
    j = html.find('\n  function ', i + 10)
    return html[i:j if j > i else i + 2000]


# ───────────────────────── 有牙证明（自测）─────────────────────────

def _mutations(html: str) -> list:
    out = []
    out.append(('拿掉默认未探测态 → 改写成"假装在跑"',
                html.replace('data-conn="probing"', 'data-conn="ok"')))
    out.append(('把"未连上"文案删掉',
                html.replace('🔴 未连上', '').replace('未连上', '')))
    out.append(('把 🔴 的原因换成空串（静默化）',
                html.replace("setConn('down', why)", "setConn('down', '')")))
    out.append(('拿掉探测超时（AbortController）',
                html.replace('AbortController', '/*x*/').replace('ctl.abort()', '')))
    out.append(('换成白名单外的端点',
                html.replace("fetch('/api/health'", "fetch('/api/health2'")))
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
            print('   ⚠️ 篡改 "%s" 未生效（字符串没匹配上）✗ —— 测试自身需修' % name)
            fails += 1
            continue
        got = check(mut)
        if got:
            print('   ✓ 有牙：%s → 判红 %d 条' % (name, len(got)))
        else:
            print('   ✗ 无牙：%s → 竟然全绿 ✗' % name)
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


def test_conn_lamp_契约满足():
    bad = check(read_html())
    assert not bad, 'D6-5 连接灯护栏判红：\n  - ' + '\n  - '.join(bad)


def test_conn_lamp_有牙证明():
    html = read_html()
    for name, mut in _mutations(html):
        assert mut != html, '篡改未生效（测试自身需修）：%s' % name
        assert check(mut), '无牙：篡改后仍全绿 → %s' % name


if __name__ == '__main__':
    sys.exit(main())
