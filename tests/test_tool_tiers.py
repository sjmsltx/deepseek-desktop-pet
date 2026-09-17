# -*- coding: utf-8 -*-
"""v6.53 新增：工具梯级暴露 + 冻结版日志目录 回归测试

覆盖：
  - tools_registry.tools_for_mode：默认只给 core，进阶模式给全部，动态工具不受影响
  - 上下文负担：默认模式的 schema 体积应明显小于全量
  - desktop_pet / settings_ui 的接入点（源码护栏）
  - pet_log 冻结环境日志目录
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tools_registry as tr  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_core_subset_of_all():
    all_names = {t['function']['name'] for t in tr.AI_TOOLS}
    assert set(tr.CORE_TOOLS) <= all_names, 'CORE_TOOLS 有拼错的工具名：%s' % (set(tr.CORE_TOOLS) - all_names)
    assert 5 <= len(tr.CORE_TOOLS) <= 20, 'core 工具数量应保持精简，当前 %d' % len(tr.CORE_TOOLS)


def test_mode_switch():
    core = tr.tools_for_mode(False)
    full = tr.tools_for_mode(True)
    assert len(core) == len(tr.CORE_TOOLS), '默认模式应只给 core：%d' % len(core)
    assert len(full) == len(tr.AI_TOOLS) == 29, '进阶模式应给全部：%d' % len(full)
    assert {t['function']['name'] for t in core} == set(tr.CORE_TOOLS)


def test_context_saving():
    """默认模式仍需明显省上下文（门槛从 55%% 调到 30%%：v6.58 把能力类工具补回了 core）"""
    core = json.dumps(tr.tools_for_mode(False), ensure_ascii=False)
    full = json.dumps(tr.tools_for_mode(True), ensure_ascii=False)
    saved = 1 - len(core) / len(full)
    assert saved >= 0.30, '默认模式节省比例不足 30%%（实际 %.0f%%）' % (saved * 100)


def test_capability_tools_in_core():
    """v6.58：外观/自改/插件/文件类工具必须在默认集合里。

    背景：v6.53 把它们收进进阶模式，导致使用者让桌宠“装个主题并切换”时，AI 手上没有
    read_file / install_plugin / set_theme，只能回“工具没装上”。
    """
    core = {t['function']['name'] for t in tr.tools_for_mode(False)}
    for must in ('read_file', 'write_file', 'search_code', 'edit_own_code',
                 'install_plugin', 'uninstall_plugin', 'list_plugins', 'set_theme', 'skill_run'):
        assert must in core, '能力类工具被误收进进阶模式：%s' % must


def test_companion_tools_present():
    """陪伴核心工具必须在默认集合里（否则陪伴体验会退化）"""
    core = {t['function']['name'] for t in tr.tools_for_mode(False)}
    for must in ('memorize', 'offer_choices', 'schedule_followup', 'set_reminder', 'manage_todo'):
        assert must in core, '陪伴核心工具被误收起：%s' % must


def test_source_guards():
    pet = open(os.path.join(ROOT, 'desktop_pet.py'), encoding='utf-8-sig').read()
    ui = open(os.path.join(ROOT, 'settings_ui.py'), encoding='utf-8-sig').read()
    assert 'tools_for_mode(getattr(self, \'advanced_tools\', False))' in pet, '请求未按模式取工具'
    assert 'self.mcp.tool_schemas() + self.plugin_mgr.tool_schemas()' in pet, '动态工具被误过滤'
    assert 'advanced_tools' in pet and 'def _set_advanced_tools' in pet, '缺少开关落盘方法'
    assert 'ck_adv' in ui and '_toggle_advanced_tools' in ui, '设置窗口缺少开关'


def test_frozen_log_dir():
    from pet_log import _default_log_dir
    d = _default_log_dir()
    assert d.endswith('logs'), '日志目录异常：%s' % d
    # 非冻结时跟随模块目录；冻结分支用 sys.executable（此处只验证分支存在且可调用）
    assert callable(_default_log_dir)


if __name__ == '__main__':
    test_core_subset_of_all()
    test_mode_switch()
    test_context_saving()
    test_capability_tools_in_core()
    test_companion_tools_present()
    test_source_guards()
    test_frozen_log_dir()
    print('✅ 工具梯级 7 项断言通过')
