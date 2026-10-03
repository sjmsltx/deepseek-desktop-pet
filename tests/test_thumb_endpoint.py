# -*- coding: utf-8 -*-
"""E12 护栏：只读缩略图端点（含对方探针判据 ✓ 与零落盘反例 ✓）"""
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'collab'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import relay_server  # noqa: E402


def _mk(tmp_path):
    from PIL import Image, ImageDraw
    base = str(tmp_path)
    os.makedirs(os.path.join(base, 'collab', 'pending'), exist_ok=True)
    d = os.path.join(base, 'assets_3.0', 'alpha')
    os.makedirs(d, exist_ok=True)
    im = Image.new('RGB', (600, 600), (255, 255, 255))
    ImageDraw.Draw(im).rectangle([100, 100, 500, 500], fill=(200, 60, 60))
    im.save(os.path.join(d, 'alpha_happy_alpha.png'))
    return base


# ── 1. ⭐ 路径解析：白名单根之下 ✓ 非法形状一律 None ✗ ────────────────
def test_thumb_path_whitelist(tmp_path):
    base = _mk(tmp_path)
    assert relay_server.thumb_path(base, 'alpha', 'happy', 'alpha')
    assert relay_server.thumb_path(base, 'alpha', 'happy', 'white') is None  # 该图不存在 ✓
    for bad in (('..', 'happy'), ('a/b', 'happy'), ('alpha', '../x'),
                ('alpha', 'a\\b'), ('', 'happy'), ('x' * 65, 'happy')):
        assert relay_server.thumb_path(base, bad[0], bad[1], 'alpha') is None, bad
    assert relay_server.thumb_path(base, 'alpha', 'happy', 'evil') is None


# ── 2. ⭐ 缩略图在**内存**里生成 ✓ 且能读 ✓ ─────────────────────────
def test_thumb_bytes_in_memory(tmp_path):
    base = _mk(tmp_path)
    p = relay_server.thumb_path(base, 'alpha', 'happy', 'alpha')
    data = relay_server.thumb_bytes(p, 128)
    assert data and data[:8] == b'\x89PNG\r\n\x1a\n', '⭐ 必须是合法 PNG ✓'
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    assert im.width == 128, '⭐ 应按 w 缩放 ✓ 实测 %s' % im.width


# ── 3. ⭐⭐ 零落盘反例：调完端点后目录**不得**新增任何文件 ─────────────
def test_endpoint_writes_nothing(tmp_path):
    base = _mk(tmp_path)
    before = []
    for r, _, fs in os.walk(base):
        before += [os.path.join(r, f) for f in fs]
    p = relay_server.thumb_path(base, 'alpha', 'happy', 'alpha')
    relay_server.thumb_bytes(p, 256)
    after = []
    for r, _, fs in os.walk(base):
        after += [os.path.join(r, f) for f in fs]
    assert sorted(before) == sorted(after), '⛔ 不得落任何缓存文件 ✗（守 C1 ✓）'


# ── 4. ⭐ 契约文本：双钉（无参必须 400 的探针口径必须写明 ✓）──────────
def test_contract_e12_in_place():
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     'docs', '3.0-M1-API契约-冻结v1.md')
    m = io.open(p, encoding='utf-8').read()
    assert 'E12' in m and '/api/thumb' in m
    assert 'state' in m and '必填' in m
    assert '无参' in m and '400' in m, '⭐ 探针判据（无参→400）必须写明 ✗'
    assert '不落' in m or '内存' in m, '⭐ 零落盘口径必须写明 ✗'


# ── 5. ⭐ 源码级：常量与路由在位 ✓ ──────────────────────────────────
def test_route_and_consts():
    s = io.open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             'collab', 'relay_server.py'), encoding='utf-8').read()
    assert 'MAX_THUMB_W = 512' in s and 'MIN_THUMB_W = 64' in s
    assert "'/api/thumb'" in s
    seg = s[s.index('def do_GET'):]
    assert "'/api/thumb'" in seg, '⭐ 必须在 do_GET（只读面 ✓）✗ 不得进 do_POST ✗'
