# -*- coding: utf-8 -*-
"""UI 黄金基线（2026-09-13，桌宠收尾批 1）

作用：把「UI 层可机器验证的部分」采成结构化指纹，供后续搬迁（气泡渲染、状态机、
主题 token 化）做搬迁前后对照。**不再依赖肉眼兜底**。

用法：
    python tests/golden_ui.py capture        # 采集并写入 tests/golden/ui_baseline.json
    python tests/golden_ui.py capture --out X.json
    python tests/golden_ui.py check          # 与基线比对，不一致则退出码 1
    python tests/golden_ui.py check --base X.json

采集口径（全部确定性，不含时间戳/会话 id 等易变值）：
    1. markdown    —— chat_render 对样本语料的输出指纹（C2 搬迁的对照物）
    2. assets      —— 当前角色立绘目录清单 + 每个文件的 sha256（图不能悄悄被换）
    3. frame       —— 逐帧渲染结果的像素指纹：待机帧、偏移帧、各状态帧（C1 搬迁的对照物）
    4. state_machine —— set_state 之后 current 与取图结果（状态语义不能变）
    5. theme       —— 主题字典 + 样式表指纹与色值数量（C3 主题化的对照物）
    6. ui_probe    —— 流式/思考/状态行/选项按钮的初始结构

注意：
    · 基线是**机器/环境相关**的（Qt 版本、字体、立绘文件都会影响哈希）。
      换机器、升级 PySide6 或换立绘后，先确认渲染确实变了，再用 capture 重建基线并在
      提交信息里写明原因——不要为了让 check 变绿而盲目重建。
    · frame 区用像素哈希，对缩放/居中等渲染细节敏感，是搬迁时最有用的一道网。
"""
import hashlib
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

DEFAULT_BASE = os.path.join(ROOT, 'tests', 'golden', 'ui_baseline.json')

# ---------------- 样本语料 ----------------
MD_SAMPLES = [
    '普通一行中文，带标点。',
    '**加粗**、*斜体*、`行内代码`、[链接](https://example.com)',
    '多行：\n第一行\n第二行\n\n第三行（空行分段）',
    '```python\nprint("hi")\n```',
    '| 列A | 列B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |',
    '含表情 [happy] 与 (sleep) 标记的文本',
    '转义测试：<img src="file:///C:/secret.png"> 与 a<b & c>d',
    '无分隔符的疑似表格\nA   B\n1   2',
    '超长行：' + '长' * 220,
    '空字符串：',
    '',
    '混合代码块 + 表格\n\n```js\nconst a = 1;\n```\n\n| x | y |\n|---|---|\n| 1 | 2 |',
]

STATE_CANDIDATES = ['idle', 'sleep', 'happy', 'thinking', 'scared', 'shy', 'angry', 'sad']


def _sha_text(s):
    return hashlib.sha256(s.encode('utf-8')).hexdigest()[:32]


def _pixmap_hash(pm):
    """QPixmap 像素指纹（RGBA 原始字节）。"""
    from PySide6.QtGui import QImage
    if pm is None or pm.isNull():
        return None
    img = pm.toImage().convertToFormat(QImage.Format_RGBA8888)
    data = bytes(img.constBits())
    return '%dx%d:%s' % (img.width(), img.height(), hashlib.sha256(data).hexdigest()[:32])


def _hex_colors(text):
    import re
    return len(re.findall(r'#[0-9a-fA-F]{3,8}', text or ''))


def capture():
    from PySide6.QtWidgets import QApplication, QMessageBox
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    app = QApplication.instance() or QApplication([])

    import chat_render
    import desktop_pet as dp

    w = dp.PetWidget()
    w.ai_enabled = False

    snap = {}

    # 1. markdown 渲染指纹
    md = {}
    for i, s in enumerate(MD_SAMPLES):
        try:
            html = chat_render.md_to_html(s)
        except Exception as e:
            html = 'ERR:%s' % e
        md['sample_%02d' % i] = _sha_text(html)
    # 分块器也要锁住（气泡按块渲染）
    try:
        md['_blocks_split'] = [_sha_text(str(chat_render.split_md_blocks(x))) for x in MD_SAMPLES[:6]]
    except Exception as e:
        md['_blocks_split'] = 'ERR:%s' % e
    snap['markdown'] = md

    # 2. 立绘资产清单（文件名 + 内容哈希）
    adir = os.path.join(ROOT, 'assets', str(w.current))
    assets = {}
    if os.path.isdir(adir):
        for f in sorted(os.listdir(adir)):
            p = os.path.join(adir, f)
            if os.path.isfile(p):
                with open(p, 'rb') as fh:
                    assets[f] = '%d:%s' % (os.path.getsize(p), hashlib.sha256(fh.read()).hexdigest()[:32])
    snap['assets'] = {'char': str(w.current), 'count': len(assets), 'files': assets}

    # 3. 逐帧渲染指纹
    frames = {}
    w._render_frame()
    frames['idle'] = _pixmap_hash(w.pet_label.pixmap())
    for dx in (-20, 10):
        try:
            w._render_idle_offset(dx)
            frames['idle_dx%+d' % dx] = _pixmap_hash(w.pet_label.pixmap())
        except Exception as e:
            frames['idle_dx%+d' % dx] = 'ERR:%s' % e
    for st in STATE_CANDIDATES:
        try:
            pm = w._get_state_img(st)
            frames['state_%s' % st] = 'null' if pm is None else _pixmap_hash(pm)
        except Exception as e:
            frames['state_%s' % st] = 'ERR:%s' % e
    for key in ('eat', 'read', 'music', 'sport'):
        try:
            pm = w._get_scene_img(key)
            frames['scene_%s' % key] = 'null' if pm is None else _pixmap_hash(pm)
        except Exception as e:
            frames['scene_%s' % key] = 'ERR:%s' % e
    snap['frame'] = frames

    # 4. 状态机语义
    orig = getattr(w, 'state', None)
    sm = {}
    for st in STATE_CANDIDATES:
        try:
            w.set_state(st)
            got = getattr(w, 'state', None)
            img = w._get_state_img(st)
            sm[st] = {'state': got, 'img': 'null' if img is None else 'pixmap'}
        except Exception as e:
            sm[st] = {'state': 'ERR:%s' % e}
    try:
        w.state = orig
    except Exception:
        pass
    snap['state_machine'] = sm

    # 5. 主题
    theme = {}
    try:
        s = w.snapshot()
        theme['current_theme'] = s.get('current_theme')
        theme['theme_keys'] = sorted((s.get('theme') or {}).keys())
        theme['theme_hash'] = _sha_text(json.dumps(s.get('theme') or {}, sort_keys=True, ensure_ascii=False))
    except Exception as e:
        theme['error'] = str(e)
    try:
        ss = w.styleSheet() or ''
        theme['stylesheet_len'] = len(ss)
        theme['stylesheet_hash'] = _sha_text(ss)
        theme['stylesheet_colors'] = _hex_colors(ss)
    except Exception as e:
        theme['stylesheet_error'] = str(e)
    snap['theme'] = theme

    # 6. UI 探针结构
    try:
        probe = w.ui_probe()
        snap['ui_probe'] = {k: (type(v).__name__ if not isinstance(v, (str, int, float, bool, type(None))) else v)
                            for k, v in sorted(probe.items())}
    except Exception as e:
        snap['ui_probe'] = {'error': str(e)}

    # 7. 几何常量
    snap['geometry'] = {'pet_size': getattr(w, 'pet_size', None),
                        'window_size': [w.width(), w.height()]}

    try:
        w.close()
    except Exception:
        pass
    return snap


def diff_sections(base, cur):
    diffs = []
    for sec in sorted(set(base) | set(cur)):
        b, c = base.get(sec), cur.get(sec)
        if b == c:
            continue
        if isinstance(b, dict) and isinstance(c, dict):
            for k in sorted(set(b) | set(c)):
                if b.get(k) != c.get(k):
                    diffs.append('%s.%s\n      base=%s\n      cur =%s' % (sec, k, str(b.get(k))[:160], str(c.get(k))[:160]))
        else:
            diffs.append('%s\n      base=%s\n      cur =%s' % (sec, str(b)[:160], str(c)[:160]))
    return diffs


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'check'
    out = DEFAULT_BASE
    if '--out' in sys.argv:
        out = sys.argv[sys.argv.index('--out') + 1]
    if '--base' in sys.argv:
        out = sys.argv[sys.argv.index('--base') + 1]

    cur = capture()
    if mode == 'capture':
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with io.open(out, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(cur, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write('\n')
        print('已写入基线：%s' % out)
        for sec in sorted(cur):
            v = cur[sec]
            n = len(v) if isinstance(v, (dict, list)) else 1
            print('   %-14s %d 项' % (sec, n))
        return 0

    if not os.path.exists(out):
        print('基线不存在：%s（先跑 capture）' % out)
        return 2
    base = json.load(io.open(out, encoding='utf-8'))
    diffs = diff_sections(base, cur)
    if not diffs:
        print('黄金对照：完全一致 ✅（%d 个分区）' % len(base))
        return 0
    print('黄金对照：发现 %d 处差异 ❌' % len(diffs))
    for d in diffs[:40]:
        print('   - %s' % d)
    return 1


if __name__ == '__main__':
    sys.exit(main())
