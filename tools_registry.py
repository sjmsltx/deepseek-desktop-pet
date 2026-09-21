# -*- coding: utf-8 -*-
"""
tools_registry.py — AI 工具注册表（P3 模块化拆分）
==================================================
从 desktop_pet.py 拆出的 AI_TOOLS 定义（function calling schema 纯数据）。
工具执行逻辑仍在主文件 _execute_tool（handler 深度耦合 UI/self 状态）。
"""

AI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "打开电脑上的应用程序或文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "应用名，如：记事本、计算器、画图、cmd、powershell、pycharm、vscode、浏览器、资源管理器，或直接输入程序名/路径/盘符（如 D:\\ 或用户主目录），或用用户自定义别名"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_time",
            "description": "获取当前日期和时间",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "生成文件并写入内容（报告/笔记/代码/表格等）。文件统一保存到桌宠目录的 输出/ 子目录（自动创建），文件名自动防路径穿越。Python 文件（.py）会自动做语法校验，语法错误会拒绝保存并要求重新生成。仅在用户明确要求'生成/保存/输出一份文件'时才使用（用户说'写个文件/保存到文件/导出'等）；用户只是提问、讨论、分析问题时禁止主动创建文件，直接回答即可，拿不准时先问用户是否需要保存为文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "文件名（如 调研报告.md / 数据.csv / 脚本.py）"},
                    "content": {"type": "string", "description": "要写入的完整内容"}
                },
                "required": ["filename", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "在桌宠项目源码中搜索关键词（所有 .py 模块），返回 文件:行号:代码行 列表。改代码前先定位：不知道功能在哪个文件、想找函数/变量的实现位置时用本工具，避免猜路径读错文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "搜索关键词（函数名/变量名/类名/中文注释片段等）"}
                },
                "required": ["keyword"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_own_code",
            "description": "直接修改桌宠自己的源代码（支持任意模块，默认 desktop_pet.py）。流程：先用 search_code 定位关键词所在文件与行号 → read_file 带 start_line/end_line 读目标行（输出带行号）→ 本工具传 file（模块文件名，如 affection_engine.py）+ start_line/end_line + new_text 精确替换。自动带 git 保护（改前记录基线 hash，改后语法验证，失败不落盘 + backup 备份）。修改后提示用户重启生效。注意：UI 颜色/样式不要改源码——用主题系统（set_theme 切换或 install_plugin 装 theme 插件）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "description": "要修改的模块文件名（如 desktop_pet.py / memory_engine.py / affection_engine.py），默认 desktop_pet.py"},
                    "old_text": {"type": "string", "description": "要替换的原文（匹配模式用；按行模式可省略）"},
                    "new_text": {"type": "string", "description": "替换后的新代码（按行模式=整行新内容，含缩进；匹配模式=替换文本）"},
                    "start_line": {"type": "integer", "description": "按行编辑：起始行号（从 1 开始）"},
                    "end_line": {"type": "integer", "description": "按行编辑：结束行号（含，省略=只替换 start_line 一行）"}
                },
                "required": ["new_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取桌宠自己的文件（源代码/配置/README，限项目目录内）。用于自查代码、确认配置、分析问题。支持 start_line/end_line 读取指定行范围（输出带行号，方便精确编辑）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对项目目录的文件路径，如 desktop_pet.py / config.json / README.md"},
                    "start_line": {"type": "integer", "description": "起始行号（可选）"},
                    "end_line": {"type": "integer", "description": "结束行号（可选，省略=读到末尾）"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_config",
            "description": "修改桌宠配置（白名单字段，立即生效）。可改：personality(性格)/reply_style(回复风格:short,normal,detailed)/max_tokens(回复长度)/city(城市)/language(zh,en)/active_chat(主动关心true,false)/display_mode(static,live2d)/live2d_model(模型名)/sedentary_minutes(久坐分钟)/api_prices(API价格表，JSON对象，每百万token单价，格式如 {\"deepseek-flash\":{\"input\":1,\"cache\":0.02,\"output\":2}}，用于API费用统计)。改UI外观、立绘、性格、以及用户提到deepseek/API价格调整/费用统计不准时（先web_search查最新官方价，再用api_prices更新）使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "配置字段名"},
                    "value": {"type": "string", "description": "配置值"}
                },
                "required": ["key", "value"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "install_plugin",
            "description": "安装插件（桌宠扩展能力：加AI工具/加行为规则/加右键菜单/换主题/加技能）。当用户说'装个XX插件'、'加个XX功能'、'自定义桌宠能力'时使用。用法：生成插件元数据 meta（type=tool表示给AI加工具，tools数组里每个工具含name/description/parameters；type=rules表示加行为规则，rules填规则文件路径+用rules_content给内容；type=menu表示加右键菜单项；type=theme表示换皮肤，theme字段填颜色变量对象如{\"panel_bg\":\"#FFFFFF\",\"text\":\"#333\"}；type=skill表示多步技能，steps数组列步骤），工具类插件还需提供 entry_content（plugin.py代码，工具处理函数=同名函数，入参args dict，返回字符串）。自动做安全校验并热加载生效，无需重启。注意：不要为了加功能去直接改桌面宠物源代码，用插件系统。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "插件名（字母/数字/下划线/连字符，≤32字符）"},
                    "meta": {"type": "object", "description": "plugin.json 内容：type/description/entry/tools等"},
                    "entry_content": {"type": "string", "description": "plugin.py 代码（tool/menu类插件需要，可选）"},
                    "rules_content": {"type": "string", "description": "rules 类插件的规则内容（type=rules 时必填，会写入 rules 字段指向的文件）"}
                },
                "required": ["name", "meta"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "uninstall_plugin",
            "description": "卸载已安装的插件。参数：name=插件名（用 list_plugins 可查）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "插件名"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_plugins",
            "description": "查看已安装插件列表与状态。用户问'装了什么插件/插件状态'时使用。",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_theme",
            "description": "切换桌宠聊天面板主题（换皮肤）。可用主题：default（默认深蓝黑）+ 已安装的 theme 插件名（可用 list_plugins 查）。当用户说'换个主题/换个皮肤/换配色/护眼模式'时使用；若用户要的主题不存在，可用 install_plugin 装一个 theme 插件（type=theme，theme字段指向颜色变量json）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "主题名：default 或 theme 插件名"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "skill_run",
            "description": "执行复合技能（多步流程）。当用户要求'一键周报/一键整理/跑一遍XX流程'且该技能已安装时使用：返回执行步骤清单，你按步骤依次执行（每步用对应工具完成）。可用技能用 list_plugins 查看（type=skill）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "技能名"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "联网搜索最新信息（新闻、行情、时事、事实核查、2024年之后的事件等）。当用户的问题需要当前/最新知识，或你的训练知识可能过时（知识截止 2024 年 8 月）时，使用此工具获取实时信息。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词，尽量具体（如：美国当前通胀率 2025）"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "计算数学表达式",
            "parameters": {
                "type": "object",
                "properties": {
                    "expr": {"type": "string", "description": "数学表达式，如 2+3*4"}
                },
                "required": ["expr"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": "设置定时提醒。相对时间直接换算秒数；如需绝对时间（如 下午3点）请先调用 get_time 获取当前时间，再计算正确的秒数",
            "parameters": {
                "type": "object",
                "properties": {
                    "seconds": {"type": "integer", "description": "多少秒后提醒（1-86400）"},
                    "text": {"type": "string", "description": "提醒内容"}
                },
                "required": ["seconds", "text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "lock_screen",
            "description": "锁定电脑屏幕",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "offer_choices",
            "description": "在对话关键时刻给主人提供 2-3 个选项（galgame 式选择支）。仅在合适场景使用：二选一/三选一的抉择、约不约、去不去、选哪个、让主人做决定时。调用后回复正文应简短（一两句），把选择权交给选项。每个选项可以是字符串，或对象 {text: 选项文字, affect: 好感度增量}（affect 用 1-3 的整数，表示选这个选项主人会多开心）",
            "parameters": {
                "type": "object",
                "properties": {
                    "choices": {"type": "array", "items": {}, "description": "2-3 个选项，每个不超过 10 字，口语化；字符串或 {text, affect} 对象"}
                },
                "required": ["choices"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_weather",
            "description": "查询城市天气。仅当用户明确要求查天气/温度/降雨/空气质量/适不适合出门时才调用；用户问美食/景点/地理等与天气无关的问题时不要调用",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市名，如 重庆"}
                },
                "required": ["city"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_powershell",
            "description": "在 Windows PowerShell 中执行命令并返回输出。适合：查询系统/服务/文件/网络(ping/ipconfig)/磁盘状态等。禁止删除、关机、格式化、写文件等危险操作（工具层会自动拦截并拒绝）",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "PowerShell 命令，如 Get-Process | Sort-Object WS -Descending | Select-Object -First 5"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_info",
            "description": "获取电脑系统信息：CPU 型号/占用、内存总量/剩余、磁盘、系统版本、开机时间",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_processes",
            "description": "列出当前最占内存的前 N 个进程（默认 10 个）",
            "parameters": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer", "description": "进程数量，默认 10"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "kill_process",
            "description": "结束指定名称的进程（如 notepad、chrome）。系统关键进程会被保护拒绝",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "进程名，如 notepad 或 notepad.exe"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "control_volume",
            "description": "精确控制系统音量：set=设置到指定百分比（如 调到60%）；up/down=相对调大调小；mute/unmute=静音/取消静音",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["set", "up", "down", "mute", "unmute"], "description": "操作类型：set 精确设置百分比，up/down 相对调节，mute/unmute 静音"},
                    "percent": {"type": "integer", "description": "目标音量百分比 0-100，仅 action=set 时必填"},
                    "steps": {"type": "integer", "description": "相对调节步数（每步 1%），action=up/down 时使用，默认 5"}
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "搜索电脑上的文件（按文件名关键词），默认在用户目录下搜索",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "文件名关键词，如 期末报告"},
                    "path": {"type": "string", "description": "搜索起始目录，可选，默认用户主目录"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_clipboard",
            "description": "读取剪贴板文本内容。适合：用户复制了文字/数据，需要整理、分析、转表格时",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_clipboard",
            "description": "把文本写入剪贴板（用户可直接粘贴）。适合：生成代码/文字后让用户复制",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "要写入剪贴板的文本"}
                },
                "required": ["text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "manage_todo",
            "description": "待办清单管理：add=添加待办（text），list=列出全部，done=标记完成（id 或 text），remove=删除（id 或 text）。用户说\"记住要做XX\"\"提醒我交作业\"等适合 add",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["add", "list", "done", "remove"], "description": "操作类型"},
                    "text": {"type": "string", "description": "待办内容（add 必填；done/remove 可用文本匹配）"},
                    "id": {"type": "string", "description": "待办 ID（done/remove 用）"}
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_followup",
            "description": "安排回访：对话结束后过一段时间主动找用户关心一下。适合用户提到重要事件（去吃饭/考试/开会/睡觉/办事/心情不好）时安排。seconds=多少秒后回访(600-21600)，reason=要关心的主题",
            "parameters": {
                "type": "object",
                "properties": {
                    "seconds": {"type": "integer", "description": "多少秒后回访（600-21600，即10分钟到6小时）"},
                    "reason": {"type": "string", "description": "回访要关心的主题，如 用户去吃饭了"}
                },
                "required": ["seconds", "reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "memorize",
            "description": "长期记忆：记住用户的重要信息（偏好/习惯/个人事实/任务目标/重要结论）。add=新增记忆，update=更新已有记忆（需 id），delete=遗忘某条记忆（需 id 或 content）。只记录持久有价值的信息，不要记一次性的闲聊。重要度 importance 1-5（5=最重要）。role：both=两个角色共享（默认，用户偏好等通用信息），flash=仅Flash角色，pro=仅Pro角色（角色专属信息如角色名字/人设用对应的 role）",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["add", "update", "delete"], "description": "add 新增 / update 更新 / delete 遗忘"},
                    "content": {"type": "string", "description": "记忆内容（add/update 时必填）"},
                    "importance": {"type": "integer", "description": "重要度 1-5，默认 3"},
                    "id": {"type": "string", "description": "记忆 ID（update/delete 时用，可通过对话让用户提供或从上下文推断）"},
                    "role": {"type": "string", "enum": ["both", "flash", "pro"], "description": "记忆归属角色：both=共享默认，flash=仅Flash，pro=仅Pro"}
                },
                "required": ["action"]
            }
        }
    },
    # v6.66：办公文档（WPS / Microsoft Office COM）—— 补上“日常任务”能力
    {
        "type": "function",
        "function": {
            "name": "office_doc",
            "description": "办公文档（本机 WPS/Office + 真生成文档）：action=info 探测接口；write_sheet 写 xlsx；read_sheet 读表格；make_report 生成带样式报表；export_pdf 导出 PDF；write_doc 生成 Word（标题+段落+表格）；write_slides 生成 PPT（封面+要点页）。用户要“做表格/生成报表/统计成 Excel/导出 PDF/写文档/做 PPT”时用；文件统一落在程序目录的 输出/ 下",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["info", "write_sheet", "read_sheet", "make_report", "export_pdf", "write_doc", "write_slides"], "description": "操作类型"},
                    "path": {"type": "string", "description": "目标文件名（.xlsx/.docx/.pptx；export_pdf 时填源文件）"},
                    "rows": {"type": "string", "description": "二维数据 JSON，如 [[\"日期\",\"金额\"],[\"09-19\",1.5]]"},
                    "headers": {"type": "string", "description": "表头 JSON（make_report / write_doc）"},
                    "title": {"type": "string", "description": "标题（make_report / write_doc / write_slides）"},
                    "subtitle": {"type": "string", "description": "副标题（write_doc / write_slides，可选）"},
                    "paragraphs": {"type": "string", "description": "正文段落 JSON 数组（write_doc），元素可为字符串或 {\"style\":\"Heading 1\"|\"List Bullet\",\"text\":\"…\"}"},
                    "slides": {"type": "string", "description": "幻灯片 JSON 数组（write_slides）：[{\"title\":\"页标题\",\"bullets\":[\"要点1\",\"要点2\"],\"notes\":\"备注\"}]"},
                    "footer": {"type": "string", "description": "页脚备注（make_report，可选）"},
                    "sheet": {"type": "string", "description": "工作表名（默认 Sheet1）"},
                    "start": {"type": "string", "description": "起始单元格（默认 A1）"},
                    "cell_range": {"type": "string", "description": "读取范围如 A1:D20"},
                    "out": {"type": "string", "description": "导出的 PDF 文件名（export_pdf）"}
                },
                "required": ["action"]
            }
        }
    },
    # v6.67：技能包管理（Batch 3-1）—— 放在进阶工具里（不是日常高频，省上下文）
    {
        "type": "function",
        "function": {
            "name": "skill_pack",
            "description": "技能包管理：action=list 列出已装技能包（含来源/版本/权限）；info 看某个包的权限卡片；install 从本地目录或 zip 安装（做清单校验 + 安全扫描）；grant 确认权限；enable/disable 启用禁用；uninstall 卸载（进停放区可找回）。用户说“装个技能/扩展能力”“看装了哪些技能”“禁用/卸载某个技能”时用。技能包代码若要用子进程、联网、删文件这类能力，必须在 manifest 里声明对应权限并由用户确认后才生效。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "info", "install", "grant", "enable", "disable", "uninstall"], "description": "操作类型"},
                    "name": {"type": "string", "description": "技能包名（info/grant/enable/disable/uninstall 用）"},
                    "path": {"type": "string", "description": "install 时的本地技能包目录或 .zip 路径"},
                    "permissions": {"type": "string", "description": "grant 时确认的权限类别，多个用逗号分隔，如 office.com,files.write"}
                },
                "required": ["action"]
            }
        }
    },
    # v6.76：朗读摘要（AI 主动声明“这段该怎么念”，只影响朗读不进正文）
    {
        "type": "function",
        "function": {
            "name": "set_voice_summary",
            "description": "当本次回复很长（多段/列表/代码/表格）时，用这个工具给 1~2 句「朗读版摘要」，让语音朗读只念要点而不是整篇。短回复不需要调。只影响朗读，不会出现在正文里。",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "要念出来的 1~2 句摘要（口语化，不带 markdown 标记）"}
                },
                "required": ["text"]
            }
        }
    },
]


# 工具执行时的状态提示（工具名 → (中文, English)）——拆自 _ai_worker 的 status_map
TOOL_STATUS = {
    'open_app': ('正在打开应用', 'Opening app'),
    'query_weather': ('正在查询天气', 'Checking weather'),
    'run_powershell': ('正在执行命令', 'Running command'),
    'get_system_info': ('正在读取系统信息', 'Reading system info'),
    'list_processes': ('正在读取进程列表', 'Listing processes'),
    'kill_process': ('正在结束进程', 'Ending process'),
    'search_files': ('正在搜索文件', 'Searching files'),
    'calculate': ('正在计算', 'Calculating'),
    'get_time': ('正在获取时间', 'Getting time'),
    'memorize': ('正在记住', 'Remembering'),
    'set_reminder': ('正在设置提醒', 'Setting reminder'),
    'lock_screen': ('正在锁定屏幕', 'Locking screen'),
    'control_volume': ('正在调整音量', 'Adjusting volume'),
}


# ---------- 工具梯级（v6.53 引入，v6.58 校准）----------
# 背景：29 个工具的 schema 每请求约 11.1K 字符（≈5.5K token），工具说明会挤占人设，
# 也会诱发“什么事都想去调工具”。方案：默认只暴露 core + 「进阶工具模式」开关（设置窗口可切）。
#
# v6.58 校正：v6.53 把「外观 / 自改 / 插件 / 文件」也收进了进阶模式，结果使用者让桌宠
# “装个蓝白主题并切换”时，AI 手上没有 read_file / install_plugin / set_theme，
# 只能回一句“工具没装上”——省 token 不能省掉用户能明确感知的能力。
# 原则：core = 陪伴高频 + 用户能直接要求的能力；进阶 = 偏系统/偏危险（PowerShell/进程/注册表等）。
CORE_TOOLS = (
    # 陪伴 / 日常（v6.53 原 core）
    'get_time', 'query_weather', 'set_reminder', 'manage_todo',
    'memorize', 'offer_choices', 'schedule_followup', 'web_search',
    # v6.58：外观 / 自改 / 插件 / 文件（用户能明确感知的能力，默认必须可用）
    'read_file', 'write_file', 'search_code', 'edit_own_code',
    'install_plugin', 'uninstall_plugin', 'list_plugins', 'set_theme',
    'skill_run',
    # v6.66：办公文档（日常任务：表格 / 报表 / PDF）
    'office_doc',
    # v6.76：朗读摘要（长回复时告诉桌宠“该念什么”）
    'set_voice_summary',
)


def tools_for_mode(advanced=False):
    """advanced=False → 仅 core 工具 schema；True → 全部工具。

    注意：MCP 与插件提供的动态工具不在此过滤范围（由调用方另行追加）。"""
    if advanced:
        return list(AI_TOOLS)
    return [t for t in AI_TOOLS if t.get('function', {}).get('name') in CORE_TOOLS]


# ---------- v6.62：strict 严格模式（工具参数强校验）----------
# 官方要求：strict 需走 /beta 端点，且 schema 只能用白名单关键字（不支持 minLength/
# maxLength/minItems/maxItems/pattern 等），对象必须 additionalProperties=false，
# 且“所有字段都进 required”。实测（2026-09-19）：/beta 与正式端点都接受 strict，
# 且 strict 与非 strict 工具可以混在同一个请求里。
STRICT_UNSUPPORTED_KEYS = ('minLength', 'maxLength', 'minItems', 'maxItems',
                           'pattern', 'format', 'default', 'examples', '$schema')


def _normalize_schema(schema):
    """递归剔除 strict 不支持的关键字，并给每个 object 加上 additionalProperties=false"""
    if not isinstance(schema, dict):
        return schema
    out = {}
    for k, v in schema.items():
        if k in STRICT_UNSUPPORTED_KEYS:
            continue
        if k == 'properties' and isinstance(v, dict):
            out[k] = {pk: _normalize_schema(pv) for pk, pv in v.items()}
        elif k == 'items' and isinstance(v, (dict, list)):
            out[k] = ([_normalize_schema(i) for i in v] if isinstance(v, list)
                      else _normalize_schema(v))
        else:
            out[k] = v
    if out.get('type') == 'object' and 'additionalProperties' not in out:
        out['additionalProperties'] = False
    return out


def _has_anonymous_subschema(schema):
    """是否存在“没声明 type/anyOf/$ref”的子 schema（v6.62 实测踩到的坑）

    offer_choices 的参数里写了 `"items": {}`（“字符串或对象都行”），strict 模式下
    官方直接 400：Invalid tool parameters schema : one of `type`, `anyOf`, `$ref`
    field is required。这类工具不适合 strict，宁可不开，也不去改它的语义。
    """
    if not isinstance(schema, dict):
        return False
    if not any(k in schema for k in ('type', 'anyOf', '$ref')):
        return True
    for k, v in schema.items():
        if k == 'properties' and isinstance(v, dict):
            if any(_has_anonymous_subschema(sv) for sv in v.values()):
                return True
        elif k == 'items':
            if isinstance(v, dict) and _has_anonymous_subschema(v):
                return True
            if isinstance(v, list) and any(_has_anonymous_subschema(i) for i in v):
                return True
        elif k in ('anyOf', 'oneOf', 'allOf') and isinstance(v, list):
            if any(_has_anonymous_subschema(i) for i in v):
                return True
    return False


def can_be_strict(tool):
    """该工具能否安全开启 strict：对象参数、required 已覆盖全部属性、且无空子 schema

    为什么只收这一子集：strict 要求“所有字段必填”，对有可选参数的工具强行
    required 列全会改变语义（如 edit_own_code / memorize），反而更危险。
    """
    try:
        f = tool.get('function') or {}
        pm = f.get('parameters') or {}
        if pm.get('type') != 'object':
            return False
        props = set((pm.get('properties') or {}).keys())
        if props != set(pm.get('required') or []):
            return False
        return not _has_anonymous_subschema(pm)
    except Exception:
        return False


def mark_strict(tool):
    """返回该工具的 strict 版本（规范化 schema + strict=true）"""
    f = dict(tool.get('function') or {})
    f['parameters'] = _normalize_schema(f.get('parameters') or {'type': 'object'})
    f['strict'] = True
    out = dict(tool)
    out['function'] = f
    return out


def strict_tools(tools):
    """把“能安全严格”的工具转成 strict，其余保持原样。

    返回 (tools, strict_names)。用户名可能要问“哪些工具变严了”，所以把名字一并给出。
    """
    out, names = [], []
    for t in (tools or []):
        try:
            if t.get('type') == 'function' and can_be_strict(t):
                out.append(mark_strict(t))
                names.append((t.get('function') or {}).get('name', ''))
            else:
                out.append(t)
        except Exception:
            out.append(t)
    return out, names
