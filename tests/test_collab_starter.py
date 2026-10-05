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

# ⭐ 端点白名单：起手区的"提交"只允许复用既有**写**端点（⛔ 不新增 ✗）
#   ⭐ 2026-10-04 扩：直加契约 E15.3／E16 的两个**只读**端点（`/api/queue`／`/api/history` ✓）
#   ⭐ 2026-10-05 扩：⭐ 直加契约 `PC-…-165`（C2 读路径）的**只读** `/api/config` ✓（⛔ 仍不新增写端点 ✗）
#      —— ⭐ 它们**不是新端点** ✓（E15.3／E16 已定案 ✓）且**纯读** ✓（调用前后日志条数不变 ✓）
ALLOWED = {'/api/interrupt', '/api/step', '/api/queue', '/api/history', '/api/config'}


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

    # ① 起手区三件套（⭐ E15.4：提交＝**两个明确动作** ✗ 不是单一“发起” ✗）
    for eid, name in (('starter', '起手区容器'), ('starter-input', '主输入框'),
                      ('starter-queue', '⏳ 排队按钮'), ('starter-interrupt', '⚡ 插话按钮')):
        if 'id="%s"' % eid not in html:
            bad.append('缺%s（#%s）✗' % (name, eid))
    if 'id="starter-send"' in html:
        bad.append('⛔ 仍存在单一“发起”按钮（#starter-send）✗ —— E15.4 明确“不许合成一个含糊按钮” ✗')

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

    # ⑧ ⭐ A3+：通道初始化必须**在界面上被明示**（可移植性 P2）
    if 'init_channel.py' not in html:
        bad.append('界面未明示“第 0 步·初始化通道”（`init_channel.py` ✗）' +
                   ' —— ⛔ 未初始化时产出会互相覆盖 ✗ 而用户根本不知道 ✓')

    # ⑨ ⭐ 契约 E13.3：动作面**默认关** ⇒ ⛔ 403 不得当普通错误 ✗（须置灰 ＋ 写原因 ＋ 给指引 ✓）
    if 'markActionsOff' not in reg:
        bad.append('未处理“动作面未开”（E13.3）✗ —— ⛔ 不许让用户“点了才发现” ✗')
    if not re.search(r'403', reg):
        bad.append('未识别 403（动作端点未开启）✗ —— 会把“需 --enable-actions”当成普通报错 ✗')

    # ⑩ ⭐ B6/D6-4：Plan（只读讨论）/ Act（可执行）两态
    if 'id="starter-pm-act"' not in html or 'id="starter-pm-plan"' not in html:
        bad.append('缺 Plan/Act 两态控件（D6-4）✗')
    else:
        m3 = re.search(r'<span[^>]*id="starter-pm-plan"[^>]*>', html)
        if not (m3 and re.search(r'class="on"', m3.group(0))):
            bad.append('⭐ 默认态不是 Plan（只读讨论）✗ —— 默认就可执行＝危险默认 ✗')
        m4 = re.search(r'<span[^>]*id="starter-pm-act"[^>]*>', html)
        if m4 and re.search(r'class="on"', m4.group(0)):
            bad.append('Act 被写成默认态 ✗（默认必须 Plan ✓）')
    if '现在会改文件' not in html:
        bad.append('切换 Act **未显式提示“现在会改文件”** ✗（D6-4 要求 ✓）')
    # ⭐ Plan 不得推进：`step` 必须在 Act 分支下
    if not re.search(r"pmMode\(\)\s*!==\s*'act'", reg):
        bad.append('⛔ Plan 态未拦截 `step` ✗ —— 那就成了“只读讨论也会改文件” ✗')

    # ⑪ ⭐ E13.3 完全体：必须据 `/api/health.actions` **事先**置灰 ✓（⛔ 只靠 403 事后补救不够 ✗）
    #    ⚠️ 该逻辑在**连接灯那段**（probeConn ✓）⇒ 要在**全文**里找 ✓，⛔ 不在 `reg`（起手区）里 ✗
    if not re.search(r"j\.actions\s*===\s*false", html):
        bad.append('未据 `/api/health.actions` **事先**置灰 ✗（E13.3 完全体要求 ✓）—— '
                   '⛔ 只靠 403 事后补救＝仍是“调了才发现” ✗')

    # ⑫ ⭐ E15.4（真排队）：两个明确动作 ＋ **一律显式传 mode** ＋ 不得写“排队执行中” ＋ 明写不可撤回
    if not re.search(r"mode:\s*mode", html):
        bad.append('⭐ 未**显式传 `mode`** ✗（E15.1 定案：界面必须显式传 ✓ ⛔ 不依赖端点默认值 ✗）')
    if "'queue'" not in html or "'interrupt'" not in html:
        bad.append('缺 mode 的两个取值（queue／interrupt）✗')
    if '排队执行中' in html:
        bad.append('⛔ 出现了禁写字样（“排队执行中”类）✗ —— 未启用 E15 时只是**打断进暂停** ✗')
    if '已暂停' not in html:
        bad.append('未写明“已暂停，待处理 N 条”✗（E15.4.3 ✓）')
    if '不可撤回' not in html:
        bad.append('未明写“v1 不可撤回”✗（E15.2 ✓ ⛔ 不假装 ✗）')

    # ⑬ ⭐ E16.2（运行历史）：必须明标“步骤由消息序列派生” ＋ 端点未就绪要明示 ＋ 原始错误位
    if '消息序列派生' not in html:
        bad.append('历史未明标“由消息序列派生（近似）”✗（E16.2 ✓ ⛔ 不冒充精确步骤 ✗）')
    if '未就绪' not in html:
        bad.append('端点未就绪时未明示 ✗（⛔ 不空白 ✗）')
    if '原始错误' not in html:
        bad.append('历史无“原始错误”展示位 ✗（E16.2 ✓）')

    # ⑭ ⭐ 安全层评估（`WX-…-40` §一.2 B）：窄写不受只读开关管 —— 界面**必须明示** ✗
    #    ⚠️ 自纠：首版只查“不受”二字 ✗ ⇒ 文件里**别处**也有“不受” ⇒ 篡改后仍绿 ✗（跛脚 ✗）
    #    ⇒ 改为查**整句**（与界面文案一致 ✓）
    if '窄写' not in html or '/api/pending' not in html or '不受' not in html:
        bad.append('未明示“窄写（`/api/pending`）**不受**只读开关管”✗ —— '
                   '⚠️ 用户会误判“服务只读所以点啥都安全”✗（安全层评估 §一.2-B ✓）')
    if not re.search(r'它<b>不受</b>', html):
        bad.append('“窄写**不受**只读开关管”的整句被改掉/弱化 ✗（安全层评估 §一.2-B ✓）')

    # ⑮ ⭐ C2/D5-2（⚙ 配置面 · 读路径契约 `PC-…-165` ✓）：只读端点 ＋ 敏感恒不显 ＋ 不可写必须明示
    #    ⚠️ 自纠：⭐ 首版只查字面词（“已配置”／“当前不可写”）✗ ⇒ 文件别处也有这两个词 ⇒ **无牙** ✗
    #    ⇒ ⭐ 改为查**表达式本身**（⭐ 牙齿与判据同设计 ✓ 判例 J26 同族 ✓）
    if '/api/config' not in html:
        bad.append('⚙ 配置面未接只读端点 `/api/config` ✗（契约 §2.1 ✓）')
    else:
        if not re.search(r"v === null \|\| v === undefined\)\s*\{\s*shown = '••••", html):
            bad.append('⭐ 敏感键未走“**不回值**”✗（⛔ 硬约束②：值一个字符都不回 ✗；⭐ 对方实发形状 `items[]` ✓）')
        if not re.search(r'wr\.length\s*\?', html):
            bad.append('⭐ `writable` 为空时未**明示不可写** ✗（⛔ 契约硬约束③：不静默置灰 ✗）')

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
    out.append(('拿掉通道初始化指引', html.replace('init_channel.py', 'init_channel_x.py')))
    # ⚠️ 自纠：篡改名**不得含原名做前缀** ✗（如 `markActionsOff`→`markActionsOffX` 仍含原名 ⇒ 护栏"看不到变化" ✗）
    out.append(('拿掉 E13.3 动作面未开处理', html.replace('markActionsOff', 'noActionsOffGuard')))
    out.append(('默认态改成 Act', html.replace('class="on" data-pm="plan"', 'data-pm="plan"')))
    out.append(('拿掉“会改文件”提示', html.replace('现在会改文件', '随便改改')))
    out.append(('Plan 也推进（拿掉 Act 拦截）', html.replace("pmMode() !== 'act'", "pmMode() !== 'actX'")))
    out.append(('拿掉 actions 事前置灰', html.replace('j.actions === false', 'j.actionsX === false')))
    out.append(('把两个动作并回单一发起键', html.replace('id="starter-queue"', 'id="starter-send"')))
    out.append(('不显式传 mode', html.replace('mode: mode', 'mode: undefined')))
    out.append(('拿掉“配置不可写”分支', html.replace("wr.length ? ('（可写 ' + wr.length + ' 项 ✓）')", "''", 1)))
    out.append(('敏感键改成回显值', html.replace("shown = '••••（不回值 ✓）'", "shown = String(v)", 1)))
    out.append(('历史抽掉“派生”标注', html.replace('消息序列派生', '步骤'))) 
    out.append(('拿掉“窄写不受只读开关管”明示', html.replace('它<b>不受</b>', '它<b>受</b>', 1)))
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
