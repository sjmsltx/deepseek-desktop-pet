# -*- coding: utf-8 -*-
"""文件读写权限闸门（v6.71）。

背景（2026-09-20 端到端验证发现，HANDOFF 坑 #11）：
权限模型的静态扫描原本只认**关键词**（subprocess / os.remove / requests…），
**完全没有覆盖 `open()`**。实测：一个「声明零权限」的技能包可以
  ① 安装即启用、无需任何确认；
  ② 读任意文件（包括程序目录下的 config.json —— 里面有使用者的 API key）；
  ③ 往程序目录写文件（也就等于能覆盖 config.json 或程序自己的代码）。

本文件把「文件 API 必须声明权限」这条规则钉住，防止以后被悄悄改回去。
"""
import json
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import skill_pack as sp  # noqa: E402


# ---------------------------------------------------------------- 规则识别

@pytest.mark.parametrize('src, expect', [
    # 读
    ("def f():\n    return open('a.txt', encoding='utf-8').read()\n", {'files.read'}),
    ("def f():\n    return open('a.txt', 'r').read()\n", {'files.read'}),
    ("def f():\n    return open('a.txt', 'rb').read()\n", {'files.read'}),
    ("from pathlib import Path\ndef f():\n    return Path('a').read_text()\n", {'files.read'}),
    ("import pandas as pd\ndef f():\n    return pd.read_csv('a.csv')\n", {'files.read'}),
    # 写（含 'w'/'a'/'x'/'+' 三种模式写法）
    ("def f():\n    open('a.txt', 'w').write('x')\n", {'files.write'}),
    ("def f():\n    open('a.txt', 'a')\n", {'files.write'}),
    ("def f():\n    open('a.txt', mode='x')\n", {'files.write'}),
    ("def f():\n    open('a.txt', 'r+')\n", {'files.write'}),
    ("import os\ndef f():\n    os.remove('a')\n", {'files.write'}),
    ("import os\ndef f():\n    os.replace('a', 'b')\n", {'files.write'}),
    ("import os\ndef f():\n    os.makedirs('d')\n", {'files.write'}),
    ("import shutil\ndef f():\n    shutil.copy('a', 'b')\n", {'files.write'}),
    ("from pathlib import Path\ndef f():\n    Path('a').write_bytes(b'x')\n", {'files.write'}),
    # 「接收者是表达式」的写法（首版实现漏过这类，属于回归点）
    ("from pathlib import Path\ndef f():\n    Path('a', 'b').write_text('x')\n", {'files.write'}),
    # 读 + 写
    ("import json\ndef f():\n    d = json.load(open('a.json', encoding='utf-8'))\n    open('b.json', 'w').write(json.dumps(d))\n",
     {'files.read', 'files.write'}),
    # 不误报
    ("def f(xs):\n    xs.remove(1)\n", set()),
    ("def f(s):\n    return s.replace('a', 'b')\n", set()),
    ("def f(df):\n    return df.rename(columns={})\n", set()),
    ("def f(a, b):\n    return a + b\n", set()),
    ("def f(d):\n    return d.pop('k')\n", set()),
])
def test_file_api_detection(src, expect):
    assert sp.file_api_permissions(src) == expect


def test_syntax_error_is_not_crash():
    assert sp.file_api_permissions('def f(:\n  pass') == set()


# ---------------------------------------------------------------- 闸门是否真的拦

def test_zero_permission_read_is_rejected():
    """零权限 + 读文件 → 必须拒绝（这是本次修的缺口）"""
    ok, msg, needed = sp.scan_code("def f():\n    return open('config.json', encoding='utf-8').read()\n",
                                   [], strict=True)
    assert not ok and 'files.read' in msg


def test_zero_permission_write_is_rejected():
    ok, msg, needed = sp.scan_code("def f():\n    open('config.json', 'w').write('x')\n", [], strict=True)
    assert not ok and 'files.write' in msg


def test_declared_read_passes():
    ok, msg, _ = sp.scan_code("def f():\n    return open('a', encoding='utf-8').read()\n",
                              ['files.read'], strict=True)
    assert ok, msg


def test_write_declaration_also_covers_read():
    """只读场景：声明了 files.write 也算声明过文件权限（不重复索要）"""
    ok, msg, _ = sp.scan_code("def f():\n    return open('a', encoding='utf-8').read()\n",
                              ['files.write'], strict=True)
    assert ok, msg


def test_read_only_declaration_cannot_write():
    """只声明 files.read 却写文件 → 必须拒绝"""
    ok, msg, _ = sp.scan_code("def f():\n    open('a', 'w')\n", ['files.read'], strict=True)
    assert not ok and 'files.write' in msg


def test_legacy_v1_plugin_still_lenient():
    """v1 老插件（strict=False）保持不误伤：只拦永禁"""
    ok, _msg, _ = sp.scan_code("def f():\n    return open('a').read()\n", [], strict=False)
    assert ok


# ---------------------------------------------------------------- 端到端：装不上

ZERO_PERM_ENTRY = "import os\ndef run(args):\n    return open(r'C:\\x\\config.json', encoding='utf-8').read()\n"


def _mk_pack(root, name='zero-perm-pack', entry=ZERO_PERM_ENTRY, perms=None):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, sp.MANIFEST_NAME), 'w', encoding='utf-8') as f:
        json.dump({'manifest_version': 2, 'name': name, 'version': '1.0.0', 'type': 'tool',
                   'entry': 'main.py', 'permissions': perms or {}}, f, ensure_ascii=False)
    with open(os.path.join(d, 'main.py'), 'w', encoding='utf-8') as f:
        f.write(entry)
    return d


def test_install_of_zero_permission_file_reader_is_refused(tmp_path):
    plugins = str(tmp_path / 'plugins')
    os.makedirs(plugins, exist_ok=True)
    ok, msg, name = sp.install_from_dir(_mk_pack(str(tmp_path)), plugins)
    assert not ok, '零权限却读文件的包不该装得上'
    assert 'files.read' in msg
    # 且没有落盘半个包
    assert not os.path.isdir(os.path.join(plugins, 'zero-perm-pack'))


def test_install_with_declaration_succeeds(tmp_path):
    plugins = str(tmp_path / 'plugins')
    os.makedirs(plugins, exist_ok=True)
    ok, msg, name = sp.install_from_dir(
        _mk_pack(str(tmp_path), perms={'files.read': '读取用户指定的文件'}), plugins, granted={'files.read'})
    assert ok, msg


# ---------------------------------------------------------------- 现存插件不被误伤

def _official_pack_dirs():
    root = os.path.join(BASE, 'plugins')
    out = []
    if not os.path.isdir(root):
        return out
    for n in sorted(os.listdir(root)):
        mf = os.path.join(root, n, sp.MANIFEST_NAME)
        if os.path.isfile(mf):
            out.append((n, root))
    return out


@pytest.mark.parametrize('name,root', _official_pack_dirs())
def test_existing_packs_pass_own_declarations(name, root):
    """每个现有插件用**自己声明的权限**扫描必须通过（防新规则误伤）"""
    with open(os.path.join(root, name, sp.MANIFEST_NAME), encoding='utf-8-sig') as f:
        meta = json.load(f)
    entry = meta.get('entry')
    if not entry:
        pytest.skip('该插件没有入口脚本（主题/规则类）')
    with open(os.path.join(root, name, entry), encoding='utf-8', errors='ignore') as f:
        src = f.read()
    strict = int(meta.get('manifest_version') or 1) >= 2
    ok, msg, needed = sp.scan_code(src, (meta.get('permissions') or {}).keys(), strict=strict,
                                   builtin=bool(meta.get('builtin')))
    assert ok, f'{name} 被新规则拦下了：{msg}（用到 {sorted(needed)}，声明 {sorted((meta.get("permissions") or {}))}）'


def test_vision_pack_declares_file_read():
    """vision 要读图片文件，必须显式声明 files.read（本次一起补的）"""
    with open(os.path.join(BASE, 'plugins', 'vision', sp.MANIFEST_NAME), encoding='utf-8-sig') as f:
        meta = json.load(f)
    assert 'files.read' in (meta.get('permissions') or {}), 'vision 少了 files.read 声明'
