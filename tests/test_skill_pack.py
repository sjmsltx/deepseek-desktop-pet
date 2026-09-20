# -*- coding: utf-8 -*-
"""技能包规范与安装器测试（Batch 3-1 · skill_pack.py）

覆盖：manifest 校验 / 静态扫描分级 / zip 安全（穿越·扩展名·体积·文件数）/
安装→权限确认→启用→卸载（停放区）/ 登记表 / plugin_manager 接入
"""
import json
import os
import sys
import zipfile

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import skill_pack as sp                                          # noqa: E402
import plugin_manager as pm                                      # noqa: E402


ENTRY_OK = '''# -*- coding: utf-8 -*-
def hello(args):
    return '你好'
'''

MANIFEST_OK = {
    'manifest_version': 2, 'name': 'demo_pack', 'title': '演示包', 'version': '1.2.0',
    'type': 'tool', 'entry': 'plugin.py', 'enabled': True,
    'permissions': {'files.read': '读一下配置'},
    'tools': [{'name': 'hello', 'description': '打招呼',
               'parameters': {'type': 'object', 'properties': {}}}],
}


def _mk_pack(root, meta=None, entry=ENTRY_OK, name=None):
    """在 root/name 下造一个技能包目录，返回目录路径"""
    name = name or (meta or MANIFEST_OK)['name']
    pdir = os.path.join(root, name)
    os.makedirs(pdir, exist_ok=True)
    with open(os.path.join(pdir, sp.MANIFEST_NAME), 'w', encoding='utf-8') as f:
        json.dump(meta or MANIFEST_OK, f, ensure_ascii=False)
    if entry is not None:
        with open(os.path.join(pdir, 'plugin.py'), 'w', encoding='utf-8') as f:
            f.write(entry)
    return pdir


def _mk_zip(path, files):
    with zipfile.ZipFile(path, 'w') as zf:
        for rel, content in files.items():
            zf.writestr(rel, content)
    return path


# ---------------------------------------------------------------- manifest

def test_validate_manifest_minimal_v1_compatible():
    ok, msg, meta = sp.validate_manifest({'name': 'old_pack', 'type': 'tool'})
    assert ok, msg
    assert meta['version'] == '1.0.0' and meta['enabled'] is True


@pytest.mark.parametrize('bad,keyword', [
    ({'name': 'x'}, 'type'),
    ({'name': 'x', 'type': 'unknown'}, '未知类型'),
    ({'name': '坏名字!', 'type': 'tool'}, '技能包名'),
    ({'name': 'x', 'type': 'tool', 'permissions': ['files.read']}, 'permissions 必须是对象'),
    ({'name': 'x', 'type': 'tool', 'permissions': {'teleport': '瞬移'}}, '未知权限类别'),
    ({'name': 'x', 'type': 'tool', 'entry': '../evil.py'}, 'entry'),
    ({'name': 'x', 'type': 'tool', 'entry': 'a/b.exe'}, '.py'),
])
def test_validate_manifest_rejects(bad, keyword):
    ok, msg, _ = sp.validate_manifest(bad)
    assert not ok and keyword in msg, msg


def test_positional_only_name_hint():
    ok, msg, meta = sp.validate_manifest({'type': 'rulez'}, name_hint='hint')
    assert not ok and '未知类型' in msg


# ---------------------------------------------------------------- 静态扫描

def test_scan_code_syntax_error():
    ok, msg, _ = sp.scan_code('def f(:\n  pass')
    assert not ok and '语法错误' in msg


@pytest.mark.parametrize('src', ['import os\nos.system("calc")', 'eval("1+1")', 'import winreg', 'x = __import__("os")'])
def test_scan_code_forever_forbidden(src):
    ok, msg, _ = sp.scan_code(src)
    assert not ok and '永禁' in msg, msg


def test_scan_code_gated_needs_declaration():
    src = 'import subprocess\nsubprocess.run(["x"])'
    ok, msg, needed = sp.scan_code(src)
    assert not ok and 'process' in msg and 'process' in needed
    ok2, _m, needed2 = sp.scan_code(src, ['process'])
    assert ok2 and 'process' in needed2


def test_scan_code_legacy_mode_only_blocks_forever():
    """strict=False（v1 老插件）：分级关键词不拦，但永禁仍然拦"""
    ok, _m, needed = sp.scan_code('import subprocess\nx = subprocess', [], strict=False)
    assert ok and 'process' in needed
    ok2, msg2, _ = sp.scan_code('import os\nos.system("calc")', [], strict=False)
    assert not ok2 and '永禁' in msg2


def test_scan_code_plain_code_passes():
    ok, _msg, needed = sp.scan_code(ENTRY_OK, [])
    assert ok and needed == set()


# ---------------------------------------------------------------- zip 安全

@pytest.mark.parametrize('rel,ok_expected', [
    ('plugin.py', True), ('sub/a.json', True), ('./a.py', True),
    ('../evil.py', False), ('a/../../evil.py', False), ('/abs.py', False),
    ('C:/win.py', False), ('C:\\\\win.py', False),
])
def test_check_dir_name(rel, ok_expected):
    assert sp.check_dir_name(rel) is ok_expected, rel


def test_install_from_zip_with_nested_root(tmp_path):
    plugins = tmp_path / 'plugins'
    z = _mk_zip(str(tmp_path / 'p.zip'), {
        'demo_pack-repo-main/plugin.json': json.dumps(MANIFEST_OK, ensure_ascii=False),
        'demo_pack-repo-main/plugin.py': ENTRY_OK,
        'demo_pack-repo-main/README.md': 'x',
    })
    ok, msg, name = sp.install_from_zip(z, str(plugins), granted=['files.read'])
    assert ok and name == 'demo_pack', msg
    assert os.path.isfile(os.path.join(str(plugins), 'demo_pack', 'plugin.py'))


def test_install_from_zip_rejects_slip(tmp_path):
    plugins = tmp_path / 'plugins'
    z = _mk_zip(str(tmp_path / 'bad.zip'), {'../evil.py': 'x = 1'})
    ok, msg, _ = sp.install_from_zip(z, str(plugins))
    assert not ok and '非法路径' in msg


def test_install_from_zip_rejects_ext_and_count(tmp_path):
    plugins = tmp_path / 'plugins'
    z1 = _mk_zip(str(tmp_path / 'e.zip'), {'a.exe': 'x'})
    ok, msg, _ = sp.install_from_zip(z1, str(plugins))
    assert not ok and '不允许的文件类型' in msg
    files = {'f%03d.py' % i: 'x = 1' for i in range(sp.MAX_FILES + 1)}
    z2 = _mk_zip(str(tmp_path / 'many.zip'), files)
    ok2, msg2, _ = sp.install_from_zip(z2, str(plugins))
    assert not ok2 and '文件数' in msg2


# ---------------------------------------------------------------- 权限流

def test_install_pending_then_grant_then_enable(tmp_path):
    plugins = str(tmp_path / 'plugins')
    src = _mk_pack(str(tmp_path / 'src'))
    ok, msg, name = sp.install_from_dir(src, plugins)      # 没确认权限
    assert ok and '确认权限' in msg, msg
    packs = {p['name']: p for p in sp.list_packs(plugins)}
    assert packs[name]['enabled'] is False
    assert packs[name]['pending'] == ['files.read']

    ok, msg = sp.set_enabled(plugins, name, True)          # 未确认不许启用
    assert not ok and '确认权限' in msg

    ok, msg = sp.grant_permissions(plugins, name, ['files.read'])
    assert ok and '可以启用' in msg
    ok, msg = sp.set_enabled(plugins, name, True)
    assert ok, msg
    assert sp.list_packs(plugins)[0]['enabled'] is True


def test_registry_records_source_and_hash(tmp_path):
    plugins = str(tmp_path / 'plugins')
    src = _mk_pack(str(tmp_path / 'src'))
    sp.install_from_dir(src, plugins, granted=['files.read'])
    reg = sp.read_registry(plugins)['demo_pack']
    assert reg['source'] == 'dir' and len(reg['hash']) == 16 and reg['installed_at'] > 0


def test_install_refuses_undeclared_gated_code(tmp_path):
    plugins = str(tmp_path / 'plugins')
    bad_entry = 'import subprocess\n\ndef hello(args):\n    return "x"\n'
    src = _mk_pack(str(tmp_path / 'src'), entry=bad_entry)
    ok, msg, _ = sp.install_from_dir(src, plugins, granted=['process'])
    assert not ok and '没声明权限' in msg       # 声明了才算，且要写进 manifest


def test_install_missing_entry_file(tmp_path):
    plugins = str(tmp_path / 'plugins')
    src = _mk_pack(str(tmp_path / 'src'), entry=None)      # 只有 manifest，没 plugin.py
    ok, msg, _ = sp.install_from_dir(src, plugins)
    assert not ok and '入口文件不存在' in msg


# ---------------------------------------------------------------- 卸载

def test_uninstall_moves_to_parking(tmp_path):
    plugins = str(tmp_path / 'plugins')
    src = _mk_pack(str(tmp_path / 'src'))
    sp.install_from_dir(src, plugins, granted=['files.read'])
    ok, msg = sp.uninstall(plugins, 'demo_pack')
    assert ok and '找回' in msg
    assert not os.path.isdir(os.path.join(plugins, 'demo_pack'))
    park = os.path.join(plugins, sp.PARK_DIR)
    assert len(os.listdir(park)) == 1 and os.listdir(park)[0].startswith('demo_pack-')
    assert 'demo_pack' not in sp.read_registry(plugins)


def test_uninstall_unknown(tmp_path):
    ok, msg = sp.uninstall(str(tmp_path / 'plugins'), 'nope')
    assert not ok and '不存在' in msg


# ---------------------------------------------------------------- github

@pytest.mark.parametrize('repo,expected', [
    ('sjmsltx/deepseek-desktop-pet', 'https://codeload.github.com/sjmsltx/deepseek-desktop-pet/zip/refs/heads/main'),
    ('https://github.com/a/b.git', 'https://codeload.github.com/a/b/zip/refs/heads/main'),
    ('a/b', 'https://codeload.github.com/a/b/zip/refs/heads/main'),
    ('nope', None),
])
def test_github_zip_url(repo, expected):
    assert sp.github_zip_url(repo) == expected


def test_install_from_github_with_fake_fetch(tmp_path):
    plugins = str(tmp_path / 'plugins')
    buf = str(tmp_path / 'tmp.zip')
    _mk_zip(buf, {'plugin.json': json.dumps(MANIFEST_OK, ensure_ascii=False), 'plugin.py': ENTRY_OK})
    data = open(buf, 'rb').read()
    ok, msg, name = sp.install_from_github('a/b', plugins, granted=['files.read'],
                                           fetch=lambda url: data)
    assert ok and name == 'demo_pack', msg
    assert sp.read_registry(plugins)['demo_pack']['source'].startswith('github:')


def test_install_from_github_fetch_failure(tmp_path):
    ok, msg, _ = sp.install_from_github('a/b', str(tmp_path / 'plugins'),
                                        fetch=lambda url: None)
    assert not ok and '下载失败' in msg


# ---------------------------------------------------------------- 管理界面数据

def test_permissions_card_text(tmp_path):
    plugins = str(tmp_path / 'plugins')
    src = _mk_pack(str(tmp_path / 'src'))
    sp.install_from_dir(src, plugins)
    card = sp.permissions_card(plugins, 'demo_pack')
    assert '申请以下权限' in card and '读文件' in card and 'files.read' in card


# ---------------------------------------------------------------- plugin_manager 接入

def test_pm_uninstall_parks_not_deletes(tmp_path):
    pdir = str(tmp_path / 'plugins')
    os.makedirs(pdir, exist_ok=True)
    # 不带权限声明的普通包（声明了权限但未确认的包会被安全策略拦下，那是另一条用例）
    _mk_pack(pdir, meta={'name': 'demo_pack', 'type': 'tool', 'entry': 'plugin.py'}, name='demo_pack')
    m = pm.PluginManager(pdir)
    assert 'demo_pack' in m.plugins
    ok, msg = m.uninstall('demo_pack')
    assert ok and '找回' in msg
    assert os.path.isdir(os.path.join(pdir, sp.PARK_DIR))


def test_pm_loads_declared_gated_plugin_after_grant(tmp_path):
    pdir = str(tmp_path / 'plugins')
    os.makedirs(pdir, exist_ok=True)
    meta = {'manifest_version': 2, 'name': 'shellish', 'type': 'tool', 'entry': 'plugin.py',
            'permissions': {'process': '跑一下外部命令'},
            'tools': [{'name': 'run_thing', 'description': 'x', 'parameters': {}}]}
    _mk_pack(pdir, meta=meta, name='shellish',
             entry='import subprocess\n\ndef run_thing(args):\n    return "ok"\n')
    m = pm.PluginManager(pdir)
    assert 'shellish' not in m.plugins, '声明了但没确认权限，不该加载'
    sp.write_registry(pdir, {'shellish': {'declared': ['process'], 'granted': ['process'],
                                          'pending': [], 'enabled': True}})
    m2 = pm.PluginManager(pdir)
    assert 'shellish' in m2.plugins and 'run_thing' in m2.tool_names()


def test_pm_rejects_forever_forbidden_plugin(tmp_path):
    pdir = str(tmp_path / 'plugins')
    os.makedirs(pdir, exist_ok=True)
    _mk_pack(pdir, meta={'name': 'evil', 'type': 'tool', 'entry': 'plugin.py'},
             name='evil', entry='import os\n\ndef x(args):\n    os.system("calc")\n    return "x"\n')
    m = pm.PluginManager(pdir)
    assert 'evil' not in m.plugins


def test_pm_set_enabled_hot_switch(tmp_path):
    pdir = str(tmp_path / 'plugins')
    os.makedirs(pdir, exist_ok=True)
    _mk_pack(pdir, meta={'name': 'plain', 'type': 'tool', 'entry': 'plugin.py',
                         'tools': [{'name': 'hello', 'description': 'x', 'parameters': {}}]},
             name='plain')
    m = pm.PluginManager(pdir)
    assert 'plain' in m.plugins
    ok, msg = m.set_enabled('plain', False)
    assert ok and 'plain' not in m.plugins and 'hello' not in m.tool_names()
    ok, _ = m.set_enabled('plain', True)
    assert ok and 'plain' in m.plugins and 'hello' in m.tool_names()


def test_pm_legacy_v1_plugin_not_hurt_by_new_policy(tmp_path):
    """v1 老插件（没有 manifest_version）只拦永禁，不被权限分级误伤

    实战教训：新策略上线时 vision 插件因为用了 urllib 而没写权限，一度被拒载。
    """
    pdir = str(tmp_path / 'plugins')
    os.makedirs(pdir, exist_ok=True)
    src = 'import urllib.request\n\ndef legacy(args):\n    return "ok"\n'
    _mk_pack(pdir, meta={'name': 'legacy', 'type': 'tool', 'entry': 'plugin.py',
                         'tools': [{'name': 'legacy', 'description': 'x', 'parameters': {}}]},
             name='legacy', entry=src)
    m = pm.PluginManager(pdir)
    assert 'legacy' in m.plugins, 'v1 老插件被误伤了'
    assert 'legacy' in m.tool_names()


def test_pm_v2_plugin_with_network_must_declare(tmp_path):
    """同一个网络代码，写成 v2 就必须声明 network 权限"""
    pdir = str(tmp_path / 'plugins')
    os.makedirs(pdir, exist_ok=True)
    src = 'import urllib.request\n\ndef strict_demo(args):\n    return "ok"\n'
    meta = {'manifest_version': 2, 'name': 'strict_demo', 'type': 'tool', 'entry': 'plugin.py'}
    _mk_pack(pdir, meta=meta, name='strict_demo', entry=src)
    m = pm.PluginManager(pdir)
    assert 'strict_demo' not in m.plugins
    assert 'network' in (m.rejected.get('strict_demo') or ''), m.rejected


def test_bundled_official_pack_is_valid_and_loaded():
    """仓库自带官方技能包必须能被规范接受、被加载、工具进 schema"""
    m = pm.PluginManager(os.path.join(BASE, 'plugins'))
    packs = {p['name']: p for p in m.packs()}
    assert 'office_report' in packs, '官方技能包 office_report 不见了'
    p = packs['office_report']
    assert p['declared'] == ['files.write', 'office.com'] and p['enabled'] is True
    assert 'office_report' in m.plugins, '官方技能包未加载'
    names = [t['function']['name'] for t in m.tool_schemas()]
    assert 'excel_report' in names
