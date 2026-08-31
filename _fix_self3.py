# -*- coding: utf-8 -*-
"""step3: edit_own_code 多文件支持（file 参数 + 白名单 + 备份/验证扩展）"""
import io

# ========== 1. tools_registry.py：edit_own_code schema 更新 ==========
TR = r'E:\ai工作站\desktop-pet\tools_registry.py'
src = io.open(TR, 'r', encoding='utf-8').read()

old = '''    {
        "type": "function",
        "function": {
            "name": "edit_own_code",
            "description": "直接修改桌宠自己的源代码（desktop_pet.py）。优先用【按行编辑】：先用 read_file 带 start_line/end_line 读目标行（输出带行号），再传 start_line/end_line + new_text 精确替换该行（可靠，推荐）；也可用 old_text/new_text 精确匹配。自动带 git 保护（改前提交基线，改后语法验证，失败不落盘）。修改后提示用户重启生效。注意：UI 颜色/样式不要改源码——用主题系统（set_theme 切换或 install_plugin 装 theme 插件）。只改 desktop_pet.py，其他文件用其他方式。",
            "parameters": {
                "type": "object",
                "properties": {
                    "old_text": {"type": "string", "description": "要替换的原文（匹配模式用；按行模式可省略）"},
                    "new_text": {"type": "string", "description": "替换后的新代码（按行模式=整行新内容，含缩进；匹配模式=替换文本）"},
                    "start_line": {"type": "integer", "description": "按行编辑：起始行号（从 1 开始）"},
                    "end_line": {"type": "integer", "description": "按行编辑：结束行号（含，省略=只替换 start_line 一行）"}
                },
                "required": ["new_text"]
            }
        }
    },'''
new = '''    {
        "type": "function",
        "function": {
            "name": "edit_own_code",
            "description": "直接修改桌宠自己的源代码（支持任意模块，默认 desktop_pet.py）。流程：先用 search_code 定位关键词所在文件与行号 → read_file 带 start_line/end_line 读目标行（输出带行号）→ 本工具传 file（模块文件名，如 affection_engine.py）+ start_line/end_line + new_text 精确替换。自动带 git 保护（改前提交基线，改后语法验证，失败不落盘 + backup 备份）。修改后提示用户重启生效。注意：UI 颜色/样式不要改源码——用主题系统（set_theme 切换或 install_plugin 装 theme 插件）。",
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
    },'''
assert old in src, 'edit_own_code schema 未找到'
src = src.replace(old, new, 1)
io.open(TR, 'w', encoding='utf-8').write(src)
print('✅ tools_registry edit_own_code schema 更新')

# ========== 2. desktop_pet.py：handler 多文件 + 调用处 ==========
DP = r'E:\ai工作站\desktop-pet\desktop_pet.py'
src = io.open(DP, 'r', encoding='utf-8').read()

# 2.1 handler 签名 + path 白名单
old2 = '''    def _edit_own_code(self, old_text, new_text, start_line=None, end_line=None):
        """AI 修改自己的代码——git 基线保护 + 语法验证 + 失败不落盘。
        v6.25 支持两种模式：①按行号替换（start_line/end_line + new_text，推荐，精确可靠）；②old_text 精确匹配"""
        path = os.path.join(BASE_DIR, 'desktop_pet.py')
        old_text = old_text or ''
        new_text = new_text or ''
        if not old_text.strip() and start_line is None:
            return '（需要提供 old_text 或 start_line）'
        try:'''
new2 = '''    def _edit_own_code(self, old_text, new_text, start_line=None, end_line=None, file='desktop_pet.py'):
        """AI 修改自己的代码——git 基线保护 + 语法验证 + 失败不落盘。
        v6.41 支持任意模块（file 参数，白名单 .py）；v6.25 两种编辑模式：①按行号替换（start_line/end_line + new_text，推荐）；②old_text 精确匹配"""
        fname = (file or 'desktop_pet.py').strip()
        if not fname.endswith('.py') or fname.startswith('_') or '/' in fname or '\\\\' in fname:
            return f'（不允许修改的文件：{fname}，只能改项目内的 .py 模块）'
        path = os.path.join(BASE_DIR, fname)
        if not os.path.isfile(path):
            return f'（文件不存在：{fname}，可用 read_file 传目录查看项目文件列表）'
        old_text = old_text or ''
        new_text = new_text or ''
        if not old_text.strip() and start_line is None:
            return '（需要提供 old_text 或 start_line）'
        try:'''
assert old2 in src, 'handler 签名未找到'
src = src.replace(old2, new2, 1)

# 2.2 备份目标文件（替换 backup 段）
old3 = '''                bdir = os.path.join(BASE_DIR, 'backup')
                os.makedirs(bdir, exist_ok=True)
                import shutil
                shutil.copy2(path, os.path.join(bdir, f'desktop_pet_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.py'))'''
new3 = '''                bdir = os.path.join(BASE_DIR, 'backup')
                os.makedirs(bdir, exist_ok=True)
                import shutil
                shutil.copy2(path, os.path.join(bdir, f'{fname.replace(".py", "")}_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.py'))'''
assert old3 in src, 'backup 段未找到'
src = src.replace(old3, new3, 1)

# 2.3 调用处传 file
old4 = '''                return self._edit_own_code(args.get('old_text', ''), args.get('new_text', ''),
                                           args.get('start_line'), args.get('end_line'))'''
new4 = '''                return self._edit_own_code(args.get('old_text', ''), args.get('new_text', ''),
                                           args.get('start_line'), args.get('end_line'),
                                           args.get('file', 'desktop_pet.py'))'''
assert old4 in src, '调用处未找到'
src = src.replace(old4, new4, 1)

io.open(DP, 'w', encoding='utf-8').write(src)
print('✅ desktop_pet edit_own_code 多文件')

import ast
ast.parse(src)
print('✅ 语法通过')
