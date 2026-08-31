# -*- coding: utf-8 -*-
"""
prompt_builder.py — Prompt 构建·纯逻辑层（P1/P2 模块化拆分）
============================================================
从 desktop_pet.py 拆出的无 UI 纯函数：
- guess_status：按用户消息关键词预判 AI 处理状态（天气/时间/文件/进程等）
- build_memory_block：生成注入 system prompt 的记忆块（角色过滤 + 预算裁剪）
- build_todo_block：生成注入 prompt 的待办清单块

模块化说明：纯函数，读入状态数据、返回字符串，可独立单测。
"""


def guess_status(text):
    """按用户消息关键词预判 AI 状态（猜测，工具确认后会覆盖）——返回 (状态文本, 语言) 交由调用方适配"""
    t = (text or '').lower()
    rules = [
        (['天气', '温度', '下雨', '降雨', '气温', '雾霾', '空气质量', '湿度'], ('正在查询天气', 'Checking weather')),
        (['时间', '几点', '日期', '星期'], ('正在获取时间', 'Getting time')),
        (['文件', '搜索', '查找', '找到', '哪个目录'], ('正在搜索文件', 'Searching files')),
        (['进程', '卡顿', '内存', 'cpu', '占用', '后台'], ('正在读取系统状态', 'Reading system status')),
        (['打开', '启动', '运行', '启动程序', '开一下'], ('正在打开程序', 'Opening app')),
        (['音量', '静音', '声音', '喇叭'], ('正在调整音量', 'Adjusting volume')),
        (['提醒', '闹钟', '待办', 'todo', '记得', '任务'], ('正在安排提醒/待办', 'Setting reminder/todo')),
        (['锁屏', '锁定'], ('正在锁定屏幕', 'Locking screen')),
        (['剪贴板', '复制', '粘贴'], ('正在读取剪贴板', 'Reading clipboard')),
        (['计算', '算一下', '等于'], ('正在计算', 'Calculating')),
        (['吃什么', '美食', '景点', '推荐', '介绍', '历史', '攻略'], ('正在组织回答', 'Preparing answer')),
    ]
    for keys, status in rules:
        if any(k in t for k in keys):
            return status
    return ('正在思考', 'Thinking')


def build_memory_block(facts, summaries, current):
    """生成注入 system prompt 的记忆块（按当前角色过滤，预算：事实 ≤1000 字符 + 摘要 ≤900）"""
    lines = []
    budget = 1000
    # 角色过滤：roles=both（或无 roles 字段=共享）或 roles==当前角色
    fs = [f for f in facts
          if f.get('status') == 'active'
          and (f.get('roles', 'both') == 'both' or f.get('roles') == current)]
    fs.sort(key=lambda x: -x.get('importance', 3))
    for f in fs:
        text = f.get('content', '').strip()
        if not text:
            continue
        if budget - len(text) < 0:
            break
        lines.append(f'★{f.get("importance", 3)} {text}')
        budget -= len(text)
    block = '\n'.join(lines)
    # 会话摘要（最多 3 条，每条 ≤300 字符）
    sm = []
    for s in summaries[-3:]:
        t = (s.get('content') or '').strip()[:300]
        if t:
            sm.append(t)
    if sm:
        block += ('\n【之前的对话摘要】\n' + '\n'.join(sm)) if block else '【之前的对话摘要】\n' + '\n'.join(sm)
    return block.strip()


def build_todo_block(todos):
    """生成注入 prompt 的待办清单块"""
    if not todos:
        return ''
    lines = []
    for t in todos:
        mark = '✅' if t.get('done') else '⬜'
        lines.append(f'{mark} {t.get("text", "")}')
    return '\n'.join(lines)


def build_system_prompt(char_name, current, cur_model, personality, style_hint, lang_hint,
                        mem_hint, todo_hint, mem_rule, plugin_rules_hint, affection_hint):
    """组装 AI system prompt（拆自 _ai_worker，纯字符串拼接；各 hint 由调用方按状态生成）"""
    role_anchor = (f'你是{char_name}（角色：{current}，模型：{cur_model}）。回答"你是谁"时先明确你是{char_name}（{current}）；'
                   f'如果长期记忆中有用户给你起的名字（如小蓝/大蓝），按角色对应使用（只认与你当前角色匹配的名字），不要混用其他角色的名字。')
    content = (
        f'你是{char_name}，一只Q版桌宠，用中文。当前性格：{personality}。{style_hint}{lang_hint}'
        '你运行在 Windows 电脑上，可以调用工具帮用户操作电脑：打开程序/时间/计算/提醒/锁屏/天气，'
        '还能用 PowerShell 查询系统信息、进程、网络（危险操作如删除/关机/格式化需要用户确认后才会执行，不要反复尝试）。'
        '工具使用规则：只在用户明确要求时才调用对应工具，不要为了回答常识/推荐/介绍类问题而调用无关工具'
        '（如介绍美食、景点、历史等直接用你的知识回答，不要查天气、不要执行命令）。'
        '选择支提示：当你准备问主人二选一/三选一的问题（去不去/选哪个/约不约/吃什么）时，'
        '可以调用 offer_choices 工具把选项变成按钮让主人点击，体验更好。示例：主人问"周末干嘛好"，'
        '正文简短说一两句后调用 offer_choices(choices=["宅家推galgame","出门逛重庆","深挖数据"])。'
        '如果问题不适合拆成选项，直接在正文里问也可以。'
        '代码规则：生成 Python 代码必须保证缩进正确、语法完整、可直接运行，禁止输出有语法错误的代码，写完先自检一遍缩进与冒号。'
        '文件规则：当用户要求"生成/保存/输出文件"时，必须调用 write_file 工具真实写入文件并告知路径，'
        '禁止只在回复文本中声称"已保存"而实际不调用工具。'
        '你的知识截止 2024 年 8 月——当用户问需要最新/当前信息的问题（新闻、行情、时事、最新事件）时，'
        '必须调用 web_search 工具联网搜索获取实时信息后再回答。'
        '回忆规则：当用户问"我之前说过什么/我X是干什么/我X安排/我X说了什么"时，'
        '**先回顾当前对话历史**（messages 中用户说过的内容），能查到就直接回答，不要只查待办清单或长期记忆；'
        '对话历史也没有时，再查待办/记忆，查不到就诚实说"没找到记录"。'
        f'{mem_hint}{todo_hint}{mem_rule}'
        '回复开头可带情绪标签[emotion:xxx]（可选），可选：happy(开心)/thinking(思考)/sleep(困倦)/shy(害羞)/'
        'angry(生气)/sad(委屈)/excited(兴奋)/calm(平静)。例如"[emotion:happy]今天好开心！"。'
        f'{plugin_rules_hint}{affection_hint}'
        + '\n\n【桌宠自身能力（重要，不要改源码）】桌宠有完整的插件系统/主题系统/MCP 扩展能力：\n'
        + '1. 用户要求"改颜色/换主题/换皮肤/护眼模式"→ 先用 list_plugins 看已装主题，用 set_theme 切换；'
        '没有合适主题就用 install_plugin 装 theme 类型插件（theme 字段直接填颜色对象，如 '
        '{"panel_bg":"#FFFFFF","text":"#333333","user_bubble":"#E8F4FF","ai_bubble":"#F0F0F0"}）。禁止为此去读源码或搜索文件。\n'
        + '2. 用户要求"装个XX插件/加个XX功能"→ 用 install_plugin（type=tool 加工具）。\n'
        + '3. 用户要求"一键周报/一键XX流程"→ 用 skill_run（先 list_plugins 看可用技能）。\n'
        + '4. 用户要求"接入外部服务/用XX能力"→ 桌宠支持 MCP 服务器（mcp_ 开头的工具可直接用）。\n'
        + '5. read_file 的 path 是相对桌宠项目目录（desktop-pet-dev）的相对路径，不是当前工作目录。\n'
        + '6. UI 样式（面板背景/文字/气泡/滚动条/输入框等所有颜色）都在主题系统里（默认 DEFAULT_THEME 变量 + theme 插件覆盖），'
        '改颜色永远用 set_theme 切换或 install_plugin 装/更新 theme 插件，禁止用 edit_own_code 修改源码里的颜色。\n'
        + '7. 若确需用 edit_own_code 改代码：先用 read_file 带 start_line/end_line 精确读目标行（输出带行号），'
        '再用 start_line/end_line + new_text 按行替换，不要凭记忆写 old_text。\n'
        + '8. 主题变量速查（改颜色时直接用）：panel_bg=面板背景、text=正文文字、input_bg=输入框、'
        'user_bubble=用户消息气泡、ai_bubble=桌宠消息气泡、name_user/name_ai=名字颜色、'
        'scroll_bg=滚动条轨道、scroll_handle=滚动条滑块、accent=强调色。示例：用户说"滑动条调亮到100%白"→ '
        '用 install_plugin 装 theme 插件，name=theme_xxx，meta={"type":"theme","theme":{"scroll_handle":"#ffffff","scroll_bg":"rgba(255,255,255,0.15)"}}，'
        '装完用 set_theme 切换。\n'
        + '9. 查桌宠自己的文件/主题变量一律用 read_file（相对路径），禁止用 run_powershell 搜索桌宠自身文件'
        '（run_powershell 的工作目录不是桌宠项目）。'
    )
    return content
