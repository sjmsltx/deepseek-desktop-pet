# -*- coding: utf-8 -*-
"""step2: read_file 目录浏览 + search_code 工具（schema + handler + 分发）"""
import io

# ========== 1. tools_registry.py 加 search_code schema ==========
TR = r'E:\ai工作站\desktop-pet\tools_registry.py'
src = io.open(TR, 'r', encoding='utf-8').read()

old = '''    {
        "type": "function",
        "function": {
            "name": "edit_own_code",'''
assert old in src, 'edit_own_code schema 未找到'
new = '''    {
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
            "name": "edit_own_code",'''
src = src.replace(old, new, 1)
io.open(TR, 'w', encoding='utf-8').write(src)
print('✅ tools_registry search_code schema')

# ========== 2. desktop_pet.py：_search_code handler + 目录浏览 + 分发 ==========
DP = r'E:\ai工作站\desktop-pet\desktop_pet.py'
src = io.open(DP, 'r', encoding='utf-8').read()

# 2.1 read_file 目录浏览（替换「文件不存在」分支）
old2 = '''            if not os.path.isfile(full):
                return f'（文件不存在：{rel_path}）'
            # 敏感文件禁止读取（API key/隐私数据，防止泄露给 AI）'''
new2 = '''            if not os.path.isfile(full):
                # v6.41：目录 → 返回文件列表（AI 可浏览项目结构）
                if os.path.isdir(full):
                    _lines = []
                    for _f in sorted(os.listdir(full)):
                        _fp = os.path.join(full, _f)
                        if os.path.isfile(_fp):
                            try:
                                _n = sum(1 for _ in open(_fp, encoding='utf-8', errors='ignore'))
                            except Exception:
                                _n = 0
                            _lines.append(f'{_f} ({_n} 行)')
                        elif os.path.isdir(_fp):
                            _lines.append(f'{_f}/')
                    return '（目录内容）\\n' + '\\n'.join(_lines[:60]) if _lines else '（空目录）'
                return f'（文件不存在：{rel_path}）'
            # 敏感文件禁止读取（API key/隐私数据，防止泄露给 AI）'''
assert old2 in src, 'read_file 目录分支未找到'
src = src.replace(old2, new2, 1)

# 2.2 _execute_tool 加 search_code 分支（插在 read_file 分支前）
old3 = '''            elif name == 'read_file':
                return self._read_own_file(args.get('path', ''), args.get('start_line'), args.get('end_line'))'''
new3 = '''            elif name == 'search_code':
                return self._search_code(args.get('keyword', ''))
            elif name == 'read_file':
                return self._read_own_file(args.get('path', ''), args.get('start_line'), args.get('end_line'))'''
assert old3 in src, 'read_file 分支未找到'
src = src.replace(old3, new3, 1)

# 2.3 新增 _search_code 方法（插在 _read_own_file 前）
anchor = '''    def _read_own_file(self, rel_path, start_line=None, end_line=None):'''
assert anchor in src
new_method = '''    def _search_code(self, keyword, max_results=20):
        """关键词搜索项目源码（所有 .py 模块），返回 文件:行号:代码行（v6.41 定位工具）"""
        keyword = (keyword or '').strip()
        if not keyword:
            return '请提供搜索关键词'
        hits = []
        for f in sorted(os.listdir(BASE_DIR)):
            if not f.endswith('.py') or f.startswith('_'):
                continue
            path = os.path.join(BASE_DIR, f)
            try:
                with open(path, encoding='utf-8', errors='ignore') as fh:
                    for i, line in enumerate(fh, 1):
                        if keyword.lower() in line.lower():
                            hits.append(f'{f}:{i}: {line.strip()[:100]}')
                            if len(hits) >= max_results:
                                break
            except Exception:
                pass
            if len(hits) >= max_results:
                break
        if not hits:
            return f'未找到包含 "{keyword}" 的代码'
        total = len(hits)
        return '\\n'.join(hits[:max_results]) + (f'\\n…（共 {total} 处，仅显示前 {max_results} 条）' if total > max_results else '')

''' + anchor
src = src.replace(anchor, new_method, 1)

io.open(DP, 'w', encoding='utf-8').write(src)
print('✅ desktop_pet：目录浏览 + _search_code + 分发')

import ast
ast.parse(src)
print('✅ 语法通过')
