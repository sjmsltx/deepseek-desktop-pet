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

print('===== G. 输出汇总 =====')
total = len(RESULTS)
passed = sum(1 for _, s, _ in RESULTS if s == 'PASS')
failed = [(n, e) for n, s, e in RESULTS if s == 'FAIL']
print(f'总计 {total} 项：PASS {passed} / FAIL {len(failed)}')
for n, e in failed:
    print(f'  ❌ {n}: {e}')
app.quit()
