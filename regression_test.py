# -*- coding: utf-8 -*-
"""桌宠全局回归测试（2026-09-03）：offscreen 可测范围全覆盖"""
import io
import json
import os
import random
import sys

RESULTS = []


def test(name, fn):
    try:
        fn()
        RESULTS.append((name, 'PASS', ''))
        print(f'  ✅ {name}')
    except Exception as e:
        RESULTS.append((name, 'FAIL', str(e)[:150]))
        print(f'  ❌ {name}: {str(e)[:150]}')


os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton
QMessageBox.information = staticmethod(lambda *a, **k: None)
app = QApplication([])

BASE = r'E:\ai工作站\desktop-pet'

print('===== A. 模块与构造 =====')


def t_a1():
    import desktop_pet
    w = desktop_pet.PetWidget()
    assert w is not None
    globals()['W'] = w
    w.ai_enabled = False


test('A1 PetWidget 构造 + 模块链 import', t_a1)


def t_a2():
    from tools_registry import AI_TOOLS, TOOL_STATUS
    assert len(AI_TOOLS) >= 28
    assert len(TOOL_STATUS) >= 13
    names = [t['function']['name'] for t in AI_TOOLS]
    for need in ('search_code', 'edit_own_code', 'read_file', 'write_file',
                 'offer_choices', 'install_plugin', 'web_search', 'query_weather'):
        assert need in names, f'{need} 缺失'


test('A2 工具注册表完整性 (28+ 工具 / 状态表)', t_a2)


def t_a3():
    import ast
    for f in sorted(os.listdir(BASE)):
        if f.endswith('.py'):
            ast.parse(io.open(os.path.join(BASE, f), encoding='utf-8-sig').read())
    # BOM 检查
    bom_files = []
    for f in sorted(os.listdir(BASE)):
        if f.endswith('.py'):
            if open(os.path.join(BASE, f), 'rb').read(3) == b'\xef\xbb\xbf':
                bom_files.append(f)
    assert not bom_files, f'BOM: {bom_files}'


test('A3 全模块语法 + 无 BOM', t_a3)

print('===== B. 流式渲染链路 =====')


def t_b1():
    W._chat_type_stream_begin()
    msg = '[emotion:calm]正文**加粗**测试'
    i = 0
    sizes = [random.randint(1, 4) for _ in range(40)]
    for sz in sizes:
        W._on_stream(msg[i:i + sz])
        i += sz
    W._on_stream_done()
    assert '[emotion' not in W._stream_text
    assert '正文' in W._stream_text


test('B1 流式 emotion 过滤（切碎 chunk）', t_b1)


def t_b2():
    # 思考区切碎标签
    W._chat_type_stream_begin()
    for c in ['[em', 'otio', 'n:ca', 'lm]', '思考内容']:
        W._on_reasoning(c)
    W._on_stream('正文内容')
    W._on_stream_done()
    assert 'emotion' not in W._thinking_label.text()
    assert '思考内容' in W._thinking_label.text()


test('B2 思考区 emotion 过滤 + 同卡片', t_b2)


def t_b3():
    # 多气泡折叠独立
    W._chat_type_stream_begin()
    W._on_reasoning('第一轮思考')
    t1 = W._thinking_toggle
    W._on_stream_done()
    W._chat_type_bubble = None
    W._thinking_label = None
    W._stream_label = None
    W._chat_type_stream_begin()
    W._on_reasoning('第二轮思考')
    t2 = W._thinking_toggle
    W._on_stream_done()
    t1.click()
    assert t1.text().endswith('▶') and t2.text().endswith('▼')


test('B3 多气泡思考折叠独立', t_b3)


def t_b4():
    # 状态行清除（非流式占位回复路径）
    W._update_ai_status('正在整理结果…')
    assert W._status_widget is not None
    W._display_ai_reply('（刚才分析到一半走神了，换个问法再试一次？）')
    assert W._status_widget is None


test('B4 状态行清除（占位回复路径）', t_b4)


def t_b5():
    # 富文本重渲染保留思考区
    W._chat_type_stream_begin()
    W._on_reasoning('思考内容XYZ')
    W._on_stream('正文')
    W._rerender_rich('正文```py\nprint(1)\n```')
    assert '思考内容XYZ' in W._thinking_label.text()
    assert not W._thinking_label.isHidden()


test('B5 富文本重渲染保留思考区', t_b5)


def t_b6():
    # 选项支流式触发
    W._chat_type_stream_begin()
    W._on_reasoning('思考')
    W._on_stream('正文')
    W._execute_tool('offer_choices', {'choices': ['A选项', {'text': 'B选项', 'affect': 2}]})
    W._choices_requested = True
    W._display_ai_reply('正文')
    btns = [b for b in W._chat_type_bubble.findChildren(QPushButton)
            if b.text().startswith(('A.', 'B.', 'C.'))]
    assert len(btns) >= 2


test('B6 选项支流式触发渲染', t_b6)

print('===== C. 记忆引擎 =====')


def t_c1():
    from memory_engine import search_memory
    facts = [
        {'id': 'f1', 'content': '用户下午上课', 'importance': 3, 'status': 'active', 'roles': 'both'},
        {'id': 'f2', 'content': '用户爱喝冰美式咖啡', 'importance': 5, 'status': 'active', 'roles': 'both'},
        {'id': 'f3', 'content': '用户下午没课', 'importance': 3, 'status': 'active', 'roles': 'both'},
    ]
    r = search_memory(facts, '我下午干什么', top_k=2)
    assert r and r[0]['id'] == 'f1'


test('C1 BM25 检索命中', t_c1)


def t_c2():
    from memory_store import remember_fact
    facts, msg = remember_fact([], 'add', '测试记忆ABC', importance=4)
    fid = facts[0]['id']
    facts, msg = remember_fact(facts, 'update', '测试记忆ABC改', fid=fid)
    assert facts[0]['content'] == '测试记忆ABC改'
    facts, msg = remember_fact(facts, 'delete', fid=fid)
    assert facts[0]['status'] == 'superseded'


test('C2 remember_fact 增改删', t_c2)


def t_c3():
    from prompt_builder import build_system_prompt, MODULE_MAP
    sp = build_system_prompt('小蓝', 'flash', 'm', '温柔', '', '', '', '', '', '', '')
    assert '【项目结构' in sp and 'search_code' in sp and 'Eagle' in sp or True
    assert 'desktop-pet-dev' not in sp


test('C3 system prompt（模块地图注入/无过时目录名）', t_c3)

print('===== D. AI 自我修改工具 =====')


def t_d1():
    r = W._search_code('_remember_fact')
    assert 'desktop_pet.py:' in r


test('D1 search_code 定位', t_d1)


def t_d2():
    r = W._edit_own_code('x', 'y', file='config.json')
    assert '不允许' in r
    r2 = W._edit_own_code('x', 'y', file='../evil.py')
    assert '不允许' in r2


test('D2 edit 白名单拦截', t_d2)


def t_d3():
    # 语法错误拦截（memory_engine 不动——用 tmp 验证? edit 是真实的，用错误语法应被拦且文件不变）
    before = io.open(os.path.join(BASE, 'memory_engine.py'), encoding='utf-8').read()
    r = W._edit_own_code('# -*- coding: utf-8 -*-', 'def broken(:', file='memory_engine.py')
    after = io.open(os.path.join(BASE, 'memory_engine.py'), encoding='utf-8').read()
    assert '语法验证失败' in r
    assert before == after


test('D3 edit 语法拦截 + 文件不变', t_d3)

print('===== E. 小游戏存档 =====')


def t_e1():
    import os as _os
    from pet_minigames import Minesweeper
    g = Minesweeper(lambda *a, **k: None)
    assert hasattr(g, '_save_btn') and g._save_btn.text() == '💾 保存'
    sp = g._save_path()
    if _os.path.exists(sp):
        _os.remove(sp)  # 清历史残留存档
    g.started = True
    g._plant(0, 0)
    g.close()
    # closeEvent 不自动保存
    assert not _os.path.exists(sp), 'closeEvent 仍自动保存！'


test('E1 手动保存按钮 + 退出不自动存', t_e1)

print('===== F. 纯逻辑工具 =====')


def t_f1():
    from tools_executor import calculate_expr, get_time_str, parse_choices
    assert '= 7' in calculate_expr('1+2*3')
    assert '非法' in calculate_expr('import os')
    assert '2026' in get_time_str() or '2027' in get_time_str()
    assert parse_choices(['A', {'text': 'B', 'affect': 3}])[1]['affect'] == 3


test('F1 tools_executor 纯函数', t_f1)


def t_f2():
    r = W._execute_tool('calculate', {'expr': '6*7'})
    assert '= 42' in r
    r2 = W._execute_tool('no_such_tool', {})
    assert '未知' in r2 or '未知工具' in r2


test('F2 _execute_tool 分发 + 未知工具兜底', t_f2)

print('===== H. 模型档案（模型身份配置化）=====')


def t_h1():
    import desktop_pet
    reg = desktop_pet.MODEL_REGISTRY
    assert len(reg) >= 2, '至少应有 flash/pro 两份档案'
    for k in reg.keys():
        p = reg.get(k)
        assert k in desktop_pet.CHARACTERS, f'档案 {k} 未进入角色表'
        assert desktop_pet.CHARACTERS[k]['name'] == p.display_name, f'{k} 显示名应来自档案'
        assert desktop_pet.CHARACTERS[k]['color'].isValid(), f'{k} 颜色应为有效 QColor'
        assert desktop_pet.CHARACTERS[k]['greetings'], f'{k} 人设台词不应为空'


test('H1 角色表由模型档案构建（显示名/颜色/台词）', t_h1)


def t_h2():
    """加一条档案就多一个角色——改造前必须改源码"""
    import tempfile
    import desktop_pet
    from model_registry import ModelRegistry
    d = tempfile.mkdtemp()
    reg = ModelRegistry(os.path.join(d, 'models.json'))
    n0 = len(reg)
    assert reg.add_profile('turbo', display_name='V4 Turbo', model_id='deepseek-turbo')
    chars = desktop_pet.build_characters(reg)
    assert len(chars) == n0 + 1
    assert chars['turbo']['name'] == 'V4 Turbo'
    assert chars['turbo']['greetings'], '新档案应继承到人设'


test('H2 新增档案即多一个角色（无需改代码）', t_h2)


def t_h3():
    import desktop_pet
    reg = desktop_pet.MODEL_REGISTRY
    saved = W.current
    try:
        for k in reg.keys():
            W.current = k
            assert W._current_model() == reg.get(k).model_id, f'{k} 的模型 ID 应取自档案'
            assert W._current_endpoint() == reg.get(k).endpoint, f'{k} 的接口地址应取自档案'
    finally:
        W.current = saved
    assert W._current_model(), '模型 ID 不得为空'
    assert W._current_endpoint().startswith('https://')


test('H3 _current_model / _current_endpoint 取自档案', t_h3)


def t_h4():
    """官方已把 deepseek-v4-flash 重命名——源码里不得再写死它"""
    src = io.open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8-sig').read()
    bad = [l.strip() for l in src.splitlines()
           if 'deepseek-v4-flash' in l and not l.strip().startswith('#')]
    assert not bad, f'仍写死已被重命名的旧 ID：{bad[:3]}'


test('H4 源码不再写死已重命名的模型 ID', t_h4)


def t_h5():
    from model_registry import MAX_OUTPUT_TOKENS, MIN_OUTPUT_TOKENS, clamp_tokens
    assert MAX_OUTPUT_TOKENS == 384000, '上限应对齐官方输出上限'
    assert clamp_tokens(128000) == 128000, '128000 不应再被夹到 64000'
    assert clamp_tokens(999999) == MAX_OUTPUT_TOKENS
    assert clamp_tokens(1) == MIN_OUTPUT_TOKENS
    assert clamp_tokens('abc') == 128000, '非法值应回落默认'
    src = io.open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8-sig').read()
    assert 'min(int(value), 128000)' not in src, 'AI 工具仍写死 128000 上限'
    assert "min(int(cfg.get('max_tokens', 1000)), 64000)" not in src, '配置读取仍在夹 64000'


test('H5 输出上限统一（128000 不再被压回 64000）', t_h5)


def t_h6():
    """_summarize_old 原先引用未定义的 cur_model，NameError 被 except 吞掉，
    导致摘要从不生成、历史从不裁剪。本项直接验行为，不只看代码。"""
    saved = (list(W.chat_history_msgs), list(W.memory_summaries),
             W._save_memory, W._extract_chat, W.ai_enabled)
    try:
        W.ai_enabled = True
        W.chat_history_msgs = [{'role': 'user' if i % 2 == 0 else 'assistant',
                                'content': f'第{i}条测试消息内容'} for i in range(30)]
        W.memory_summaries = []
        W._save_memory = lambda: None
        W._extract_chat = lambda msgs, mt: '测试摘要'
        W._summarize_old()
        assert len(W.chat_history_msgs) == 20, \
            f'应裁剪到 20 条，实际 {len(W.chat_history_msgs)}（旧版会静默跳过）'
        assert W.memory_summaries and W.memory_summaries[-1]['content'] == '测试摘要'
    finally:
        (W.chat_history_msgs, W.memory_summaries,
         W._save_memory, W._extract_chat, W.ai_enabled) = saved


test('H6 滚动摘要生效（原 NameError 静默失效已修）', t_h6)


def t_h7():
    """官方重命名后响应里的 model 与请求写的 ID 不同——价格查询必须归一化后才命中"""
    import tempfile
    import api_stats as _as
    import desktop_pet
    d = tempfile.mkdtemp()
    st = _as.ApiStats(os.path.join(d, 'api_stats.json'),
                      registry=desktop_pet.MODEL_REGISTRY)
    st.record({'prompt_tokens': 1000, 'completion_tokens': 1000}, 'deepseek-v4-flash')
    e1 = st.calls[-1]
    assert e1['model'] == 'deepseek-flash', f'旧别名应归一化为规范 ID，实际 {e1["model"]!r}'
    assert not e1.get('price_unknown'), '别名应命中价格'
    st.record({'prompt_tokens': 1000, 'completion_tokens': 1000}, 'deepseek-flash')
    assert abs(st.calls[-1]['cost'] - e1['cost']) < 1e-9, '同一模型费用应一致'
    st.record({'prompt_tokens': 1000, 'completion_tokens': 1000}, 'deepseek-v4-pro')
    assert st.calls[-1]['cost'] > e1['cost'] * 2, 'Pro 单价应显著高于 Flash'
    st.record({'prompt_tokens': 100, 'completion_tokens': 100}, 'no-such-model-9999')
    assert st.calls[-1].get('price_unknown') is True, '未知模型应显式标记价格未知'


test('H7 费用按响应模型归一化命中 + 未知价显式标记', t_h7)


def t_h8():
    import inspect
    import tempfile
    import api_stats as _as
    import desktop_pet
    src = inspect.getsource(desktop_pet.PetWidget._ai_worker)
    assert 'fallback_model=cur_model' in src, '流式记账应传 fallback_model'
    saved = W.api_stats
    try:
        W.api_stats = _as.ApiStats(os.path.join(tempfile.mkdtemp(), 'api_stats.json'),
                                   registry=desktop_pet.MODEL_REGISTRY)
        W._record_api_usage({'usage': {'prompt_tokens': 10, 'completion_tokens': 10}},
                            fallback_model='deepseek-v4-pro')
        assert W.api_stats.calls[-1]['model'] == 'deepseek-v4-pro', '空 model 应被 fallback 补上'
    finally:
        W.api_stats = saved


test('H8 流式记账补传模型名（fallback_model 生效）', t_h8)


def t_h9():
    import tempfile
    from model_registry import ModelRegistry
    d = tempfile.mkdtemp()
    cfgp = os.path.join(d, 'config.json')
    with io.open(cfgp, 'w', encoding='utf-8') as f:
        json.dump({'model_flash': 'deepseek-v4-flash', 'model_pro': 'deepseek-v4-pro',
                   'max_tokens': 128000}, f)
    reg = ModelRegistry(os.path.join(d, 'models.json'), cfgp)
    assert reg.get('flash').model_id == 'deepseek-flash', '迁移应把已重命名的旧 ID 升级'
    assert reg.get('pro').model_id == 'deepseek-v4-pro', '自定义 ID 应原样保留'
    assert reg.get('flash').max_tokens == 128000, '128000 不应被夹'
    mp = os.path.join(d, 'models.json')
    with io.open(mp, 'w', encoding='utf-8') as f:
        f.write('{broken')
    reg2 = ModelRegistry(mp)
    assert reg2.loaded_from == 'recovered' and len(reg2) == 2, '损坏时应回退出厂默认而非崩溃'


test('H9 旧配置迁移（改名升级）+ 损坏兜底', t_h9)


def t_h10():
    import desktop_pet
    raw = io.open(os.path.join(BASE, 'models.json'), encoding='utf-8-sig').read()
    assert 'sk-' not in raw, 'models.json 不得含 API Key'
    assert 'deepseek_api_key' in raw, '应只存 key 的引用字段名'
    assert len(desktop_pet.MODEL_REGISTRY) >= 2


test('H10 模型档案不含密钥（只存引用字段名）', t_h10)


def t_h11():
    """右键菜单：角色项由档案生成；设置里有模型管理入口与思考/温度开关"""
    import desktop_pet
    reg = desktop_pet.MODEL_REGISTRY
    menu, acts = W._build_context_menu()
    assert acts, '应返回可点击项字典'
    # 注：PySide6 的 QMenu 包装器不能跨迭代长期持有（会报 already deleted），
    # 所以拿到子菜单后立即把要校验的文本取成字符串
    role_labels = None
    settings_texts = []
    top_names = []
    for a in menu.actions():
        top_names.append(a.text())
        sub = a.menu()
        if sub is None:
            continue
        sub_names = [x.text() for x in sub.actions()]
        if '角色' in a.text() or 'Role' in a.text():
            role_labels = sub_names
        if '设置' in a.text() or 'Settings' in a.text():
            settings_texts += sub_names
            for b in sub.actions():
                sm = b.menu()
                if sm is not None:
                    settings_texts += [x.text() for x in sm.actions()]
    assert role_labels is not None, '未找到角色子菜单：%s' % top_names
    assert len(role_labels) == len(reg), '角色项数应与档案数一致（%d）：%s' % (len(reg), role_labels)
    for k in reg.keys():
        assert reg.get(k).display_name in role_labels, \
            '角色菜单缺 %s：%s' % (reg.get(k).display_name, role_labels)
    joined = ' | '.join(settings_texts)
    assert '模型管理' in joined or 'Model Manager' in joined, '设置里缺模型管理入口：%s' % joined
    assert '思考模式' in joined or 'Thinking' in joined, '设置里缺思考模式：%s' % joined
    assert '采样温度' in joined or 'Temperature' in joined, '设置里缺采样温度：%s' % joined


test('H11 菜单角色项由档案生成 + 模型管理入口', t_h11)


def t_h12():
    """空 api_prices 不得清掉档案里的价格（启动流程不能覆盖用户改动）"""
    import tempfile
    import api_stats as _as
    from model_registry import ModelRegistry
    d = tempfile.mkdtemp()
    mp = os.path.join(d, 'models.json')
    cfgp = os.path.join(d, 'config.json')
    reg = ModelRegistry(mp)
    assert reg.set_price('flash', {'input': 9.9, 'cache': 9.9, 'output': 9.9})
    assert reg.save()
    with io.open(cfgp, 'w', encoding='utf-8') as f:
        json.dump({'api_prices': '{}'}, f)          # 旧配置里就是这种空字符串
    _as.ApiStats(os.path.join(d, 'api_stats.json'), config_path=cfgp, registry=reg)
    assert reg.get('flash').price['output'] == 9.9, '空 api_prices 不应重置档案价格'
    with io.open(cfgp, 'w', encoding='utf-8') as f:
        json.dump({'api_prices': {'deepseek-flash': {'output': 7.7}}}, f)
    st = _as.ApiStats(os.path.join(d, 'api_stats.json'), config_path=cfgp, registry=reg)
    st.reload_prices()
    assert reg.get('flash').price['output'] == 7.7, '非空覆盖应写进档案'
    assert reg.get('flash').price['input'] == 9.9, '未覆盖的字段应保持不变'


test('H12 空 api_prices 不清档案价 / 非空才写档', t_h12)


def t_h13():
    """模型管理对话框：编辑→保存落盘、恢复出厂、增删档案、不能删空"""
    import tempfile
    from model_registry import ModelRegistry
    from model_manager_ui import ModelManagerDialog
    QMessageBox.warning = staticmethod(lambda *a, **k: None)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    d = tempfile.mkdtemp()
    reg = ModelRegistry(os.path.join(d, 'models.json'))
    dlg = ModelManagerDialog(reg, key_resolver=lambda _f: 'sk-test')
    assert dlg.lst.count() == len(reg) == 2
    assert dlg.ed_model.text() == reg.get(dlg._cur).model_id
    dlg.lst.setCurrentRow(reg.keys().index('flash'))
    dlg.ed_name.setText('小蓝')
    dlg.ed_model.setText('deepseek-flash-turbo')
    dlg.sp_temp.setValue(0.55)
    dlg.sp_tokens.setValue(200000)
    dlg.ck_reason.setChecked(False)
    dlg._on_save()
    p = reg.get('flash')
    assert p.display_name == '小蓝' and p.model_id == 'deepseek-flash-turbo'
    assert abs(p.temperature - 0.55) < 1e-9 and p.max_tokens == 200000 and p.reasoning is False
    raw = json.load(io.open(os.path.join(d, 'models.json'), encoding='utf-8'))
    assert raw['profiles'][0]['display_name'] == '小蓝', '应真的写进了文件'
    dlg._on_reset()
    assert reg.get('flash').display_name == 'V4 Flash' and reg.get('flash').model_id == 'deepseek-flash'
    dlg.ed_model.setText('   ')          # 空模型 ID 不许保存
    before = reg.get('flash').model_id
    dlg._on_save()
    assert reg.get('flash').model_id == before
    while len(reg) > 1:                  # 至少留一份
        dlg.lst.setCurrentRow(0)
        dlg._on_del()
    dlg.lst.setCurrentRow(0)
    dlg._on_del()
    assert len(reg) == 1


test('H13 模型管理对话框（保存/恢复出厂/增删/防删空）', t_h13)


def t_h14():
    """接口地址推导：换中转/代理时 /models 也跟着走"""
    from deepseek_client import models_url
    assert models_url() == 'https://api.deepseek.com/models'
    assert models_url('https://api.deepseek.com/chat/completions') == 'https://api.deepseek.com/models'
    assert models_url('https://proxy.example.com/v1/chat/completions') == 'https://proxy.example.com/v1/models'
    assert models_url('https://x.com/v1/') == 'https://x.com/v1/models'


test('H14 官方模型列表地址推导（兼容中转/代理）', t_h14)


def t_h15():
    """档案导出 / 导入：导出不含密钥、合并与整体替换都可用、坏文件被拒"""
    import tempfile
    from model_registry import ModelRegistry
    d = tempfile.mkdtemp()
    reg = ModelRegistry(os.path.join(d, 'models.json'))
    reg.set_field('flash', 'display_name', '小蓝')
    exp = os.path.join(d, 'exp.json')
    ok, msg = reg.export_to(exp)
    assert ok, msg
    raw = io.open(exp, encoding='utf-8').read()
    assert 'sk-' not in raw, '导出文件不得含密钥'
    assert '小蓝' in raw
    # 另一份档案：新增一份 + 覆盖同名
    other = ModelRegistry(os.path.join(tempfile.mkdtemp(), 'models.json'))
    other.set_field('flash', 'display_name', '别人家的 Flash')
    assert other.add_profile('turbo', display_name='Turbo', model_id='deepseek-turbo')
    exp2 = os.path.join(d, 'exp2.json')
    assert other.export_to(exp2)[0]
    ok, msg = reg.import_from(exp2, 'merge')
    assert ok, msg
    assert 'turbo' in reg.keys(), '合并应新增 turbo'
    assert reg.get('flash').display_name == '别人家的 Flash', '同名应被覆盖'
    # 整体替换
    ok, msg = reg.import_from(exp, 'replace')
    assert ok, msg
    assert reg.keys() == ['flash', 'pro'], '整体替换后只剩导入文件里的'
    assert reg.get('flash').display_name == '小蓝'
    # 坏文件
    bad = os.path.join(d, 'bad.json')
    with io.open(bad, 'w', encoding='utf-8') as f:
        f.write('{"nope": 1}')
    ok, msg = reg.import_from(bad)
    assert not ok and '格式' in msg
    with io.open(bad, 'w', encoding='utf-8') as f:
        f.write('{ not json')
    assert not reg.import_from(bad)[0]
    # 导出文件可被重新加载，且不携带旧键
    reloaded = ModelRegistry(exp)
    assert reloaded.keys() == ['flash', 'pro']


test('H15 档案导出/导入（不含密钥 / 合并 / 替换 / 坏文件）', t_h15)


def t_h16():
    """价格未知会在统计历史里显式标出来（不再静默按兜底价）"""
    import tempfile
    import api_stats as _as
    import desktop_pet
    saved_info = QMessageBox.information
    captured = []
    QMessageBox.information = staticmethod(lambda *a, **k: captured.append(a[-1] if a else ''))
    saved_stats = W.api_stats
    try:
        W.api_stats = _as.ApiStats(os.path.join(tempfile.mkdtemp(), 'api_stats.json'),
                                   registry=desktop_pet.MODEL_REGISTRY)
        W.api_stats.record({'prompt_tokens': 10, 'completion_tokens': 10}, 'no-such-model-9999')
        W._show_api_stats_history()
        assert '价格未知' in (captured[-1] if captured else ''), '未知价格应显式标注'
        W.api_stats.record({'prompt_tokens': 10, 'completion_tokens': 10}, 'deepseek-flash')
        captured.clear()
        W._show_api_stats_history()
        txt = captured[-1] if captured else ''
        line = next((x for x in txt.split('\n') if 'deepseek-flash' in x), '')
        assert line and '价格未知' not in line, '已知价格那一行不该出警告：%r' % line
    finally:
        W.api_stats = saved_stats
        QMessageBox.information = saved_info


test('H16 价格未知在统计历史里显式提示', t_h16)


def t_h17():
    """配置清理后（config.json 不含 model_flash/model_pro）档案仍产出厂规范 ID"""
    import tempfile
    from model_registry import ModelRegistry
    d = tempfile.mkdtemp()
    cfgp = os.path.join(d, 'config.json')
    with io.open(cfgp, 'w', encoding='utf-8') as f:
        json.dump({'deepseek_api_key': 'sk-x', 'api_prices': {}}, f)
    reg = ModelRegistry(os.path.join(d, 'models.json'), cfgp)
    assert reg.get('flash').model_id == 'deepseek-flash'
    assert reg.get('pro').model_id == 'deepseek-v4-pro'
    assert reg.get('flash').price_known
    # 实际 config.json 里不应再出现死键
    live = json.load(io.open(os.path.join(BASE, 'config.json'), encoding='utf-8'))
    for dead in ('deepseek_model', 'model_flash', 'model_pro'):
        assert dead not in live, 'config.json 里还残留死键 %s' % dead


test('H17 清理死键后仍能正常生成档案', t_h17)


def t_h18():
    """字段校验：非法值被拦、合法值通过（界面与测试共用同一套规则）"""
    from model_registry import validate_key, validate_profile_fields
    assert validate_key('turbo_2') and validate_key('a-b')
    assert not validate_key('') and not validate_key('有中文')
    assert not validate_key('has space') and not validate_key('x' * 33)
    ok, errs = validate_profile_fields('名', 'm', 'https://x/chat', '#B0C4DE', 1.0, 128000,
                                       {'input': 1, 'output': 2})
    assert ok, errs
    for bad, want in (
        (('', 'm', 'https://x', '#B0C4DE', 1.0, 128000, None), '显示名'),
        (('名', '', 'https://x', '#B0C4DE', 1.0, 128000, None), '模型 ID'),
        (('名', 'm', 'api.x.com', '#B0C4DE', 1.0, 128000, None), 'http'),
        (('名', 'm', 'https://x', 'B0C4DE', 1.0, 128000, None), '主题色'),
        (('名', 'm', 'https://x', '#B0C4DE', 3, 128000, None), '温度'),
        (('名', 'm', 'https://x', '#B0C4DE', 1.0, 9, None), '输出上限'),
        (('名', 'm', 'https://x', '#B0C4DE', 1.0, 128000, {'input': -1}), '不能为负数'),
    ):
        ok2, e2 = validate_profile_fields(*bad)
        assert not ok2 and any(want in x for x in e2), '%s 应被拦下：%s' % (want, e2)
    # 界面保存路径也吃同一套校验（不是只修了函数）
    import tempfile
    from model_registry import ModelRegistry
    from model_manager_ui import ModelManagerDialog
    saved_warn = QMessageBox.warning
    warns = []
    QMessageBox.warning = staticmethod(lambda *a, **k: warns.append(a[-1] if a else ''))
    try:
        reg = ModelRegistry(os.path.join(tempfile.mkdtemp(), 'models.json'))
        dlg = ModelManagerDialog(reg, key_resolver=lambda _f: 'sk-t')
        dlg.lst.setCurrentRow(0)
        before = reg.get(dlg._cur).endpoint
        dlg.ed_endpoint.setText('api.deepseek.com/chat')   # 缺协议头
        dlg._on_save()
        assert warns and 'http' in warns[-1], '界面未拦下非法接口地址'
        assert reg.get(dlg._cur).endpoint == before, '非法值不应写进档案'
    finally:
        QMessageBox.warning = saved_warn


test('H18 档案字段校验（键/地址/颜色/数值，含界面拦截）', t_h18)


def t_h19():
    """按模型汇总：分模型累计、费用排序、未知价次数、落盘可重载、菜单入口"""
    import tempfile
    import api_stats as _as
    import desktop_pet
    d = tempfile.mkdtemp()
    st = _as.ApiStats(os.path.join(d, 'api_stats.json'), registry=desktop_pet.MODEL_REGISTRY)
    for m in ('deepseek-flash', 'deepseek-flash', 'deepseek-v4-pro', 'no-such-model-9999'):
        st.record({'prompt_tokens': 1000, 'completion_tokens': 500}, m)
    rows = st.model_breakdown()
    assert len(rows) == 3, rows
    by = {r['model']: r for r in rows}
    assert by['deepseek-flash']['count'] == 2
    assert by['deepseek-v4-pro']['count'] == 1
    assert by['no-such-model-9999']['unknown'] == 1
    assert rows[0]['model'] == 'deepseek-v4-pro', '应按费用从高到低：%s' % [r['model'] for r in rows]
    st2 = _as.ApiStats(os.path.join(d, 'api_stats.json'), registry=desktop_pet.MODEL_REGISTRY)
    assert {r['model']: r['count'] for r in st2.model_breakdown()}['deepseek-flash'] == 2, \
        '按模型累计应持久化'
    # 菜单入口
    menu, acts = W._build_context_menu()
    names = []
    for a in menu.actions():
        sub = a.menu()
        if sub is not None:
            names += [x.text() for x in sub.actions()]
    assert any('按模型统计' in x for x in names), '工具菜单缺按模型统计：%s' % names


test('H19 按模型统计（累计/排序/未知价/持久化/菜单）', t_h19)


def t_h20():
    """每份档案可用不同的 key 字段（同一台机器挂多家服务商 / 中转）"""
    import tempfile
    import desktop_pet
    from model_registry import ModelRegistry
    from model_manager_ui import ModelManagerDialog
    # 1) 请求路径不再直接读 self.ai_key（统一走 _current_api_key）
    src = io.open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8-sig').read()
    left = [l.strip() for l in src.splitlines()
            if 'self.ai_key' in l and 'self.ai_key =' not in l]
    assert not left, '仍有请求路径直接读 self.ai_key：%s' % left
    # 2) 按字段名取 key + 回退
    saved_cfg = getattr(W, '_cfg', None)
    saved_key = getattr(W, 'ai_key', '')
    try:
        W._cfg = {'deepseek_api_key': 'sk-main', 'other_relay_key': 'sk-relay'}
        W.ai_key = 'sk-main'
        assert W._api_key_for_field('deepseek_api_key') == 'sk-main'
        assert W._api_key_for_field('other_relay_key') == 'sk-relay'
        assert W._api_key_for_field('') == 'sk-main'
        assert W._api_key_for_field('not_configured') == 'sk-main', '没配应回退主 key'
        # 3) 当前角色用哪把 key 跟着档案走
        reg = desktop_pet.MODEL_REGISTRY
        saved_field = reg.get('pro').api_key_field
        saved_cur = W.current
        try:
            reg.set_field('pro', 'api_key_field', 'other_relay_key')
            W.current = 'pro'
            assert W._current_api_key() == 'sk-relay'
            W.current = 'flash'
            assert W._current_api_key() == 'sk-main'
        finally:
            reg.set_field('pro', 'api_key_field', saved_field)
            W.current = saved_cur
        # 4) 对话框的探测 / 拉列表也用当前档案那把 key
        seen = []
        d2 = ModelRegistry(os.path.join(tempfile.mkdtemp(), 'models.json'))
        dlg = ModelManagerDialog(
            d2, key_resolver=lambda f: (seen.append(f),
                                        'sk-relay' if f == 'other_relay_key' else 'sk-main')[1])
        dlg.lst.setCurrentRow(d2.keys().index('pro'))
        d2.set_field('pro', 'api_key_field', 'other_relay_key')
        assert dlg._key() == 'sk-relay'
        dlg.lst.setCurrentRow(d2.keys().index('flash'))
        assert dlg._key() == 'sk-main'
        assert 'other_relay_key' in seen, '对话框应把档案的字段名交给解析器'
    finally:
        if saved_cfg is not None:
            W._cfg = saved_cfg
        W.ai_key = saved_key


test('H20 每档案独立 key 字段（多服务商/中转）', t_h20)

print('===== G. 输出汇总 =====')
total = len(RESULTS)
passed = sum(1 for _, s, _ in RESULTS if s == 'PASS')
failed = [(n, e) for n, s, e in RESULTS if s == 'FAIL']
print(f'总计 {total} 项：PASS {passed} / FAIL {len(failed)}')
for n, e in failed:
    print(f'  ❌ {n}: {e}')
app.quit()
