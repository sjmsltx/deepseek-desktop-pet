# -*- coding: utf-8 -*-
"""v6.58 主题生效链路回归测试

背景（使用者实测）：让桌宠"装个蓝白主题并切换"，它装了插件、也写了 config，但**界面毫无变化**，
重启后仍是默认色。定位到三个真 bug：

  1. **GUI 刷新投递错了**：`_tool_set_theme` 用 `QTimer.singleShot(0, self._apply_theme)` 从工作线程
     "回主线程"，但 QTimer 需要目标线程有事件循环 —— AI 工具跑在工作线程里，那里没有事件循环，
     定时器**永不触发** → 主题数据改了、config 写了，界面从来没刷新过。
     （同类问题还在 `_write_config_tool` 切语言/显示模式、`say_plain`/`_append_chat` 上。）
  2. **启动不恢复**：`_init_state_and_config` 读了 advanced_tools 等一堆键，**唯独没读 `theme`** →
     重启后保存的主题名没人应用，面板回到 DEFAULT_THEME。
  3. **旧消息不换色**：气泡颜色是创建时写死进 QLabel 的，切主题后历史消息仍是旧配色。

本测试把这三条锁住。运行：python -m pytest tests/test_theme_persist.py -q
"""
import json
import os
import sys
import tempfile
import threading

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

BLUE = '#F2F7FF'


def _make_theme_plugin(root, name='theme_t1'):
    """在临时目录造一个 theme 插件（内联 theme 对象写法），返回插件目录"""
    pdir = os.path.join(root, name)
    os.makedirs(pdir, exist_ok=True)
    meta = {
        'name': name, 'version': '1.0.0', 'type': 'theme', 'enabled': True,
        'description': '测试主题',
        'theme': {'panel_bg': BLUE, 'text': '#1B3A5C', 'ai_bubble': '#F7FAFF',
                  'user_bubble': '#D6E8FF', 'bubble_text': '#1B3A5C', 'name_ai': '#4A90D9'},
    }
    with open(os.path.join(pdir, 'plugin.json'), 'w', encoding='utf-8') as fh:
        json.dump(meta, fh, ensure_ascii=False)
    return root


def _widget():
    """离屏构造 PetWidget（构造后禁用会写真实 config 的保存动作）"""
    from PySide6.QtWidgets import QApplication
    import desktop_pet
    app = QApplication.instance() or QApplication(sys.argv)
    w = desktop_pet.PetWidget()
    w._save_cfg_value = lambda *a, **k: True   # 不污染用户 config.json
    w._save_cfg = lambda *a, **k: True
    return app, w


# ---------------- ① 插件管理器能给出主题变量 ----------------

def test_theme_plugin_vars():
    from plugin_manager import PluginManager
    root = tempfile.mkdtemp(prefix='pet_theme_pl_')
    _make_theme_plugin(root)
    pm = PluginManager(root)
    assert 'theme_t1' in pm.theme_names(), '插件目录里的 theme 插件未被识别'
    v = pm.theme_vars('theme_t1')
    assert v.get('panel_bg') == BLUE, 'theme_vars 没有返回内联 theme 对象的值'
    assert pm.theme_vars('default') == {}, 'default 应无覆盖变量'


# ---------------- ② 工作线程里切主题必须真的刷新界面（核心回归） ----------------

def test_theme_applied_from_worker_thread():
    from plugin_manager import PluginManager
    app, w = _widget()
    w.plugin_mgr = PluginManager(_make_theme_plugin(tempfile.mkdtemp(prefix='pet_theme_w_')))
    done = {}

    def _worker():
        # AI 工具就是这样被调用的：在工作线程里
        done['msg'] = w._tool_set_theme({'name': 'theme_t1'})

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=10)
    for _ in range(20):            # 让队列信号送达主线程
        app.processEvents()
    assert w.current_theme == 'theme_t1', '主题名没切过去'
    assert w.theme.get('panel_bg') == BLUE, '主题数据没生效'
    assert BLUE in w.chat_panel.styleSheet(), \
        '❌ 面板样式没刷新（工作线程里 QTimer.singleShot 永不触发的老 bug 复现）'


# ---------------- ③ 启动恢复保存的主题 ----------------

def test_restore_saved_theme_on_startup():
    from plugin_manager import PluginManager
    app, w = _widget()
    w.plugin_mgr = PluginManager(_make_theme_plugin(tempfile.mkdtemp(prefix='pet_theme_r_')))
    w._saved_theme = 'theme_t1'
    w._restore_saved_theme()
    app.processEvents()
    assert w.current_theme == 'theme_t1', '启动没有恢复 config 里保存的主题'
    assert BLUE in w.chat_panel.styleSheet(), '恢复主题后面板样式没应用'


def test_restore_unknown_theme_is_safe():
    from plugin_manager import PluginManager
    app, w = _widget()
    w.plugin_mgr = PluginManager(_make_theme_plugin(tempfile.mkdtemp(prefix='pet_theme_u_')))
    before = w.current_theme
    w._saved_theme = 'not_exist_theme'
    w._restore_saved_theme()          # 不应抛异常
    assert w.current_theme == before, '不存在的主题不应改变当前主题'
    assert w.theme.get('panel_bg'), '主题字典不应为空'


# ---------------- ④ 旧消息气泡跟随新主题 ----------------

def test_runtime_switch_rethemes_existing_messages():
    from plugin_manager import PluginManager
    app, w = _widget()
    w.plugin_mgr = PluginManager(_make_theme_plugin(tempfile.mkdtemp(prefix='pet_theme_m_')))
    lbl = w._bubble_text_label('测试消息', is_user=False)
    assert w.theme.get('ai_bubble') in lbl.styleSheet(), '初始气泡色未取主题'
    w._tool_set_theme({'name': 'theme_t1'})
    app.processEvents()
    assert '#F7FAFF' in lbl.styleSheet(), '切主题后历史消息气泡没有换色'


# ---------------- ⑤ 源码护栏：别再退回 QTimer 投递 ----------------

def test_no_qtimer_hop_in_tool_handlers():
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    assert 'ui_call_signal' in src and '_run_on_ui' in src, '缺少跨线程投递通道'

    def _code_lines(s):
        """剥掉注释行，只看真代码（注释里提到 QTimer 不算）"""
        return [ln.strip() for ln in s.splitlines() if not ln.strip().startswith('#')]

    for fn in ('_tool_set_theme', '_write_config_tool'):
        i = src.index('def %s(' % fn)
        body = '\n'.join(_code_lines(src[i:i + 1600]))
        assert 'QTimer.singleShot' not in body, \
            '%s 里又出现了 QTimer.singleShot（工作线程不会触发，必须用 _run_on_ui）' % fn
    # 启动恢复也必须接在 _init_finish 上
    j = src.index('def _init_finish(')
    assert '_restore_saved_theme()' in '\n'.join(_code_lines(src[j:j + 2500])), \
        '_init_finish 没调用 _restore_saved_theme'
    # 配置里保存的主题必须在启动时被读取（方法较长，按到下一个方法定义为止取体）
    k = src.index('def _load_ai_config(')
    nxt = src.index('\n    def ', k + 10)
    assert "cfg.get('theme')" in src[k:nxt], '_load_ai_config 没读 cfg 里的 theme'
    assert 'self._load_ai_config()' in src, '_load_ai_config 没被启动流程调用'
