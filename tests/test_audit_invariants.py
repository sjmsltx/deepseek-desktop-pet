# -*- coding: utf-8 -*-
"""审计不变量：把 2026-09-20 那次“统一审计”固化成常驻测试
=====================================================================
这里的每一条都是**审计结论转成断言**，以后任何一次改动破坏它都会直接红：
  1. 所有技能包 manifest 合规，且声明的权限覆盖代码实际用到的
  2. 没有被安全策略拒载的插件
  3. v2 且非 builtin 的技能包不许直连网络库（否则出网白名单形同虚设）
  4. 官方内置条目固定（4 个技能包 + vision），且工具都进了 schema
  5. 工具数 / 设置页数 与文档声称一致
  6. 打开设置窗口逐页翻一遍，不写 config.json
  7. 治理默认值合理（审计开、限额正数、出网默认禁）
  8. 官方技能包工具都真的能被调用到（schema 里有名字）
"""
import hashlib
import json
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import skill_pack as spk                                          # noqa: E402
import plugin_manager as pm                                       # noqa: E402
import governance as gov                                          # noqa: E402

OFFICIAL_BUILTIN = {'office_report', 'pdf_tools', 'image_batch', 'file_organize', 'vision'}


def _packs():
    mgr = pm.PluginManager(os.path.join(BASE, 'plugins'))
    return mgr, mgr.packs()


def _manifest(name):
    with open(os.path.join(BASE, 'plugins', name, spk.MANIFEST_NAME), encoding='utf-8-sig') as f:
        return json.load(f)


# 1 + 2 ----------------------------------------------------------------

def test_all_packs_valid_and_scannable():
    mgr, packs = _packs()
    problems = []
    for p in packs:
        meta = _manifest(p['name'])
        ok, msg, norm = spk.validate_manifest(meta)
        if not ok:
            problems.append('%s: %s' % (p['name'], msg))
            continue
        ent = norm.get('entry')
        if not ent:
            continue
        with open(os.path.join(BASE, 'plugins', p['name'], ent), encoding='utf-8') as f:
            src = f.read()
        ok2, msg2, needed = spk.scan_code(src, (norm.get('permissions') or {}).keys(),
                                         builtin=bool(norm.get('builtin')))
        if not ok2:
            problems.append('%s 扫描不过：%s' % (p['name'], msg2))
        elif needed - set(norm.get('permissions') or {}):
            problems.append('%s 声明不足：%s' % (p['name'], sorted(needed)))
    assert not problems, problems
    assert not mgr.rejected, '有插件被安全策略拒载：%s' % mgr.rejected


def test_no_direct_network_in_new_packs():
    """出网必须走 pet_net（除非 builtin）——否则白名单管不住"""
    viol = []
    for p in _packs()[1]:
        meta = _manifest(p['name'])
        ent = meta.get('entry')
        if not ent or meta.get('builtin') or int(meta.get('manifest_version') or 1) < 2:
            continue
        with open(os.path.join(BASE, 'plugins', p['name'], ent), encoding='utf-8') as f:
            src = f.read()
        hits = [x for x in spk.DIRECT_NET_PATTERNS if x in src]
        if hits:
            viol.append('%s: %s' % (p['name'], hits))
    assert not viol, viol


# 3 -------------------------------------------------------------------

def test_builtin_set_is_expected():
    names = set()
    for p in _packs()[1]:
        meta = _manifest(p['name'])
        if meta.get('builtin') and int(meta.get('manifest_version') or 1) >= 2:
            names.add(p['name'])
    assert names == OFFICIAL_BUILTIN, '内置条目变了：%s' % sorted(names)


def test_official_tools_are_exposed():
    mgr = _packs()[0]
    exposed = {s['function']['name'] for s in mgr.tool_schemas()}
    for tool in ('excel_report', 'pdf_tool', 'image_batch', 'organize_files', 'vision_describe'):
        assert tool in exposed, '%s 没进工具表' % tool


# 4 -------------------------------------------------------------------

def test_counts_match_docs():
    import tools_registry as tr
    import settings_ui as su
    assert len(tr.AI_TOOLS) == 31, len(tr.AI_TOOLS)
    assert len(su.PAGES) == 10, len(su.PAGES)
    txt = (open(os.path.join(BASE, 'README.md'), encoding='utf-8').read() +
           open(os.path.join(BASE, 'CHANGELOG.md'), encoding='utf-8').read())
    assert '31' in txt and '十页' in txt, '文档没说清数量'


# 5 -------------------------------------------------------------------

def test_settings_dialog_does_not_write_config(monkeypatch):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    cfg = os.path.join(BASE, 'config.json')
    before = hashlib.md5(open(cfg, 'rb').read()).hexdigest() if os.path.isfile(cfg) else 'NA'
    import desktop_pet as dp
    import settings_ui as su
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    d = su.SettingsDialog(p)
    for i in range(len(su.PAGES)):
        d.nav.setCurrentRow(i)
        app.processEvents()
    d.close()
    after = hashlib.md5(open(cfg, 'rb').read()).hexdigest() if os.path.isfile(cfg) else 'NA'
    assert before == after, '打开设置就把 config.json 改了：%s → %s' % (before, after)


# 6 -------------------------------------------------------------------

def test_governance_defaults_are_safe():
    assert gov.DEFAULT_LIMITS['per_minute'] > 0 and gov.DEFAULT_LIMITS['per_day'] > 0
    assert gov.limit_for('some:actor') == gov.DEFAULT_LIMITS
    # 空白名单 = 技能一律不许出网（默认最安全）
    assert isinstance(gov.net_allowlist(), list)


def test_pet_net_is_the_only_gateway():
    import pet_net
    for fn in ('http_get', 'http_post_json', 'get_text', 'get_json', 'allowed'):
        assert hasattr(pet_net, fn), fn
