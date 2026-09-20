# -*- coding: utf-8 -*-
"""右侧信息栏（多页签 + 自定义增删）与设置页拆分护栏（v6.65）

锁住三件事：
1. 页签可加/可删/可重命名/可排序，**任务页签不可删**（队列的拖拽排序/双击取消需要界面）
2. 配置能持久化（页签列表 + 笔记文本 + 折叠状态），重建后还原
3. 设置窗口已按 8 类拆分，关键控件各归其页（不因搬家而"找不到"）

运行：python -m pytest tests/test_side_panel.py -q
"""
import json
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PySide6.QtWidgets import QApplication, QLabel                # noqa: E402

import side_panel as sp                                        # noqa: E402


def _app():
    return QApplication.instance() or QApplication(sys.argv)


def _panel(**kw):
    _app()
    kw.setdefault('tabs', None)
    return sp.SidePanel(None, **kw)


# ---------------------------------------------------------------- 配置洗白

def test_normalize_tabs():
    assert [t['kind'] for t in sp.normalize_tabs(None)] == ['tasks', 'status', 'todo']
    got = sp.normalize_tabs([{'kind': 'note', 'text': 'hi'}, {'kind': '乱写'}, {'kind': 'note'}])
    assert [t['kind'] for t in got] == ['note', 'note']
    assert got[0]['text'] == 'hi'
    assert got[0]['id'] != got[1]['id'], 'id 必须唯一（重复时自动加后缀）'
    long_text = sp.normalize_tabs([{'kind': 'note', 'text': 'x' * 9000}])[0]['text']
    assert len(long_text) <= 4000, '笔记文本要截断，别把 config 写爆'


# ---------------------------------------------------------------- 增删改

def test_default_tabs_and_task_list():
    p = _panel()
    assert p.tabbar.count() == 3
    assert p._tasks_list is not None, '默认含任务页签，任务列表应已创建'
    assert p.stack.count() == 3


def test_add_tabs_including_duplicate_notes():
    p = _panel()
    assert p.add_tab('note') is not None
    assert p.add_tab('note') is not None, '便签可以加多个'
    assert p.add_tab('system') is not None
    assert p.add_tab('tasks') is None, '任务页签只允许一个（已存在则拒绝）'
    assert p.tabbar.count() == 6
    assert p.add_tab('乱写') is None


def test_remove_tab_rules():
    p = _panel()
    p.add_tab('note')
    idx_note = p.tabbar.count() - 1
    assert p.remove_tab(idx_note) is True
    # 任务页签不可删
    assert p.remove_tab(0) is False
    assert any(t['kind'] == 'tasks' for t in p.dump_tabs())
    # 删光了非核心页签也没事（自动回到默认布局）
    p2 = _panel(tabs=[{'id': 'tasks', 'kind': 'tasks'}, {'id': 'n', 'kind': 'note'}])
    p2.remove_tab(1)
    assert p2.tabbar.count() >= 1 and p2.dump_tabs()


def test_rename_tab(monkeypatch):
    p = _panel()
    monkeypatch.setattr(sp.QInputDialog, 'getText', staticmethod(lambda *a, **k: ('我的清单', True)))
    p.add_tab('todo')
    idx = p.tabbar.count() - 1
    assert p.rename_tab(idx) == '我的清单'
    assert p.tabbar.tabText(idx) == '我的清单'
    assert p.dump_tabs()[idx]['title'] == '我的清单'
    monkeypatch.setattr(sp.QInputDialog, 'getText', staticmethod(lambda *a, **k: ('', False)))
    assert p.rename_tab(idx) is None, '取消不应改名'


def test_persist_callback_receives_tabs_and_collapsed():
    got = {}
    p = _panel(save_cb=lambda tabs, collapsed: got.update(tabs=tabs, collapsed=collapsed))
    p.add_tab('note')
    assert got.get('tabs') and any(t['kind'] == 'note' for t in got['tabs'])
    p.set_collapsed(True)
    assert got.get('collapsed') is True


def test_tab_click_switches_body():
    """点页签必须真的换内容区

    v6.66 fix：以前只换标题/底部说明，内容区永远停在任务页（没任务时就是一块空白）
    → 使用者看到“内容一片空”。
    """
    p = _panel()
    p.tabbar.setCurrentIndex(1)
    assert p.stack.currentIndex() == 1, '点页签后内容区没跟着切'
    p.tabbar.setCurrentIndex(0)
    assert p.stack.currentIndex() == 0


def test_dynamic_pages_filled_immediately():
    """展开 / 切页签 / 窗口刚显示时必须立刻填内容，不能停在占位符（使用者反馈：“显示一直是 …”）"""
    p = _panel()
    w = p.stack.widget(1)
    assert isinstance(w, QLabel)
    assert w.text() and not w.text().startswith('…'), '构造完就该有内容，不能停在占位符'
    p.set_collapsed(True)
    p.set_collapsed(False)
    assert '今日' in p.stack.widget(1).text(), '展开后必须立即刷新，不等 2 秒定时器'
    p.tabbar.setCurrentIndex(0)
    p.tabbar.setCurrentIndex(1)
    assert '今日' in p.stack.widget(1).text(), '切页签也应立即刷新'


def test_duplicate_tabs_blocked_except_note():
    """除便签外不允许同类型页签重复（“状态/花费/待办/系统”是同一份信息）"""
    p = _panel()
    n0 = p.tabbar.count()
    assert p.add_tab('status') is None and p.tabbar.count() == n0, '重复的“状态”不该加进去'
    assert '已经有了' in p.hint.text(), '要告诉使用者为什么加不上'
    assert p.add_tab('cost') is not None and p.tabbar.count() == n0 + 1, '没有的类型可以加'
    assert p.add_tab('note') is not None and p.add_tab('note') is not None, '便签可以开多个'


def test_normalize_tabs_dedupes_kinds():
    """加载时洗净重复页签（使用者已经把重复的“状态”存进配置了）"""
    raw = [{'id': 'tasks', 'kind': 'tasks'}, {'id': 'status', 'kind': 'status'},
           {'id': 'status45295', 'kind': 'status'}, {'id': 'n1', 'kind': 'note'},
           {'id': 'n2', 'kind': 'note'}]
    out = sp.normalize_tabs(raw)
    kinds = [t['kind'] for t in out]
    assert kinds == ['tasks', 'status', 'note', 'note'], kinds


def test_tab_icons_are_narrow_symbols():
    """页签图标必须是**细窄单色符号**

    v6.66 实障：彩色 emoji（📋/📊/📝 真实字体各 16px）+ 页签内边距 超过页签格宽（26px）
    → Qt 的 ElideRight 把它换成“…”（使用者看到的“页签显示成 …”）。
    这里锁住“不允许 emoji / 宽字形”溜回来。
    """
    assert set(sp.KIND_ICON) == {'tasks', 'status', 'cost', 'todo', 'note', 'system'}
    for kind, ch in sp.KIND_ICON.items():
        assert len(ch) == 1, (kind, ch)
        assert ord(ch) < 0x2E80, '%s 用了宽字符/emoji（%r），页签会被省略成 …' % (kind, ch)
        assert not (0x1F000 <= ord(ch) <= 0x1FAFF), 'color emoji 会超宽：%r' % ch


def test_collapse_hides_content_but_keeps_handle():
    p = _panel()
    wide = p.width()
    p.set_collapsed(True)
    assert p.collapsed is True
    assert not p.stack.isVisible() and not p.tabbar.isVisible()
    assert p.collapse_btn.text() == '▶'
    assert p.isVisible() is True, '折叠后仍要留一个把手（不能整条消失，否则没法展开）'
    assert p.width() == sp.COLLAPSED_W, \
        '折叠必须真的变窄（曾经只隐藏控件、还占着 186px，留下一块空面板盖住聊天）'
    p.set_collapsed(False)
    assert p.collapse_btn.text() == '◀' and p.width() == wide


def test_tab_labels_are_compact():
    """页签只放图标：186px 内放不下「📋 任务」，否则会被省略成「…」"""
    p = _panel()
    for i in range(p.tabbar.count()):
        assert len(p.tabbar.tabText(i)) <= 2, '页签文字太长：%r' % p.tabbar.tabText(i)
        assert p.tabbar.tabToolTip(i), '完整名字要放到工具提示里'
    p.add_tab('note')
    assert len(p.tabbar.tabText(p.tabbar.count() - 1)) <= 2


def test_empty_task_list_shows_hint():
    """任务为空时给一句说明，不留一大块空白"""
    p = _panel()
    p.refresh_tasks(None, [])
    assert p._tasks_list.count() == 1
    assert '暂无任务' in p._tasks_list.item(0).text()


# ---------------------------------------------------------------- 任务与动态数据

def test_refresh_tasks_renders_running_and_queue():
    p = _panel()
    p.refresh_tasks('正在做的事', [{'text': '排队一'}, {'text': '排队二'}])
    texts = [p._tasks_list.item(i).text() for i in range(p._tasks_list.count())]
    assert len(texts) == 3 and texts[0].startswith('⏳') and texts[1].startswith('⏸ 1.')


def test_dynamic_texts():
    p = _panel()
    data = {'today_count': 12, 'today_tokens': '3.5万', 'today_cost': '0.0321',
            'total_count': 680, 'total_cost': '2.7124', 'unknown': 2,
            'balance': '¥68.75', 'model': 'deepseek-flash', 'voice': 'edge:zh-CN-XiaoxiaoNeural',
            'peak': '空闲（北京 09-19 23:40）', 'affection': '26', 'last': 'deepseek-flash ¥0.0032',
            'hint': '有 2 次调用没配价格', 'todos': [{'text': '写方案', 'done': True},
                                                {'text': '跑测试', 'done': False}],
            'cpu': '24', 'mem': '8.2 / 15.7 GB（52%）', 'uptime': '1 小时 20 分',
            'version': 'Python 3.14.3'}
    st = p._text_for('status', data)
    assert '今日：12 次' in st and '¥68.75' in st and '空闲' in st
    cost = p._text_for('cost', data)
    assert '未计入：2 次' in cost and '2.7124' in cost
    todo = p._text_for('todo', data)
    assert '✅ 写方案' in todo and '⬜ 跑测试' in todo
    sysinfo = p._text_for('system', data)
    assert 'CPU：24 核' in sysinfo and '3.14.3' in sysinfo
    assert p._text_for('todo', {'todos': []}).startswith('当前没有待办事项')


def test_dynamic_refresh_only_touches_text_pages():
    seen = {'n': 0}

    def data_cb():
        seen['n'] += 1
        return {}
    p = _panel(data_cb=data_cb)
    p.show()
    seen['n'] = 0                    # 把构造/切页签带来的刷新清零，只看下面这一次
    p.refresh_dynamic()
    assert seen['n'] == 1
    seen['n'] = 0
    p.set_collapsed(True)
    p.refresh_dynamic()
    assert seen['n'] == 0, '折叠时不该白刷（定时器那条路）'
    p.set_collapsed(False)           # 展开时会立即补刷一次，这是设计要求
    assert seen['n'] == 1, '展开要立刻填内容'


# ---------------------------------------------------------------- 宿主接线

def test_pet_wiring_side_panel():
    _app()
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    assert p.side_panel.tabbar.count() >= 1
    assert p.chat_task_sidebar is p.side_panel, '旧名字要保留（别处仍在用）'
    assert p.task_list is p.side_panel._tasks_list
    p._task_queue = [{'text': '排队任务', 'ts': 0}]
    p._cur_task_text = '执行中'
    p._refresh_task_sidebar()
    assert p.task_list.count() == 2
    before = p.side_panel.collapsed      # 初始状态可能来自用户配置（别人可能已折叠过）
    p._toggle_task_sidebar()
    assert p.side_panel.collapsed is (not before), '点一下应当翻转折叠状态'
    p._toggle_task_sidebar()
    assert p.side_panel.collapsed is before, '再点一下应当回到原状态'
    data = p._side_panel_data()
    for key in ('today_count', 'today_cost', 'balance', 'model', 'voice', 'peak', 'cpu', 'mem'):
        assert key in data, '信息栏数据缺 %s' % key


def test_settings_split_into_pages():
    import settings_ui as su
    assert su.PAGES == ('通用', '对话', '外观', '模型', '语音', '用量与计费', '记忆与数据', '技能', 'MCP', '系统')
    _app()
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    d = su.SettingsDialog(p)
    n = len(su.PAGES)
    assert d.nav.count() == n and d.stack.count() == n
    pages = {su.PAGES[i]: d.stack.widget(i) for i in range(n)}

    def owns(page_name, widget):
        return pages[page_name].findChild(type(widget), widget.objectName()) is not None or \
            widget in pages[page_name].findChildren(type(widget))

    assert owns('模型', d.cb_char) and owns('模型', d.ck_reason) and owns('模型', d.cb_temp)
    assert owns('语音', d.cb_voice_name) and owns('语音', d.ed_voice_local) and owns('语音', d.ck_voice_night)
    assert owns('用量与计费', d.sp_bal)
    # 每页都不该再挤成一长条（拆分前是 26 行）
    rows = {name: pages[name].form.rowCount() for name in su.PAGES}
    assert max(rows.values()) <= 14, '单页行数仍过多：%s' % rows


def test_skills_page_lists_and_toggles(tmp_path, monkeypatch):
    """技能页：列出技能包 → 启用/禁用 → 权限卡片（不弹真对话框，不动仓库里的包）"""
    _app()
    import desktop_pet as dp
    import settings_ui as su
    import plugin_manager as pm
    import skill_pack as spk

    pdir = str(tmp_path / 'plugins')
    os.makedirs(os.path.join(pdir, 'demo'), exist_ok=True)
    with open(os.path.join(pdir, 'demo', spk.MANIFEST_NAME), 'w', encoding='utf-8') as f:
        json.dump({'manifest_version': 2, 'name': 'demo', 'title': '演示技能', 'type': 'tool',
                   'entry': 'plugin.py', 'permissions': {'files.read': '读一下文件'},
                   'tools': [{'name': 'demo_run', 'description': 'x', 'parameters': {}}]},
                  f, ensure_ascii=False)
    with open(os.path.join(pdir, 'demo', 'plugin.py'), 'w', encoding='utf-8') as f:
        f.write('def demo_run(args):\n    return "ok"\n')
    spk.write_registry(pdir, {'demo': {'declared': ['files.read'], 'granted': [],
                                       'pending': ['files.read'], 'enabled': False}})

    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p.plugin_mgr = pm.PluginManager(pdir)
    monkeypatch.setattr(su, 'QMessageBox', _FakeBox)
    monkeypatch.setattr(su, 'QFileDialog', _FakeFileDialog)

    d = su.SettingsDialog(p)
    assert '技能' in su.PAGES
    assert d.lst_skills.count() == 2, '技能包行 + 被拦提示行'
    row = d.lst_skills.item(0).text()
    assert '演示技能' in row and '待确认权限' in row, row

    d.lst_skills.setCurrentRow(0)
    d._skills_toggle()                     # 未确认权限 → 拒绝启用
    assert '确认权限' in _FakeBox.last['info'], _FakeBox.last
    d._skills_perms()                       # 看权限（弹出后询问；替身返回 No，所以不该授权）
    assert '申请以下权限' in _FakeBox.last['info']
    assert _FakeBox.questions, '应问一次要不要确认权限'

    registry = spk.read_registry(pdir)['demo']
    assert registry['pending'] == ['files.read'], '只是看权限不该自动授权'


def test_skills_page_shows_rejected(tmp_path, monkeypatch):
    """被安全策略拦下的包要在技能页以 ⚠ 行展示"""
    _app()
    import desktop_pet as dp
    import settings_ui as su
    import plugin_manager as pm
    import skill_pack as spk

    pdir = str(tmp_path / 'plugins')
    os.makedirs(os.path.join(pdir, 'bad'), exist_ok=True)
    with open(os.path.join(pdir, 'bad', spk.MANIFEST_NAME), 'w', encoding='utf-8') as f:
        json.dump({'manifest_version': 2, 'name': 'bad', 'type': 'tool', 'entry': 'plugin.py'}, f)
    with open(os.path.join(pdir, 'bad', 'plugin.py'), 'w', encoding='utf-8') as f:
        f.write('import urllib.request\n\ndef bad(args):\n    return "x"\n')
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p.plugin_mgr = pm.PluginManager(pdir)
    monkeypatch.setattr(su, 'QMessageBox', _FakeBox)
    d = su.SettingsDialog(p)
    texts = [d.lst_skills.item(i).text() for i in range(d.lst_skills.count())]
    assert len(texts) == 2, texts                   # 技能包行 + ⚠ 被拦行
    assert any(t.startswith('⚠') and 'network' in t for t in texts), texts


class _FakeBox:
    """替身：QMessageBox / QFileDialog，避免测试弹模态框"""
    last = {}
    questions = []
    Yes = 1
    No = 0

    @staticmethod
    def information(parent, title, text, *a, **k):
        _FakeBox.last = {'title': title, 'info': text}

    @staticmethod
    def question(parent, title, text, *a, **k):
        _FakeBox.questions.append(text)
        return _FakeBox.No


class _FakeFileDialog:
    @staticmethod
    def getExistingDirectory(*a, **k):
        return ''

    @staticmethod
    def getOpenFileName(*a, **k):
        return '', ''


if __name__ == '__main__':
    import pytest
    raise SystemExit(pytest.main([__file__, '-q']))
