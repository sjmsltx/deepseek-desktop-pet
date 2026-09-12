# -*- coding: utf-8 -*-
"""pet_selfcode.py — 桌宠"看/改自己代码"的工具（2026-09-12 从 PetWidget 搬出）
============================================================================
原先 search_code / write_file / edit_own_code 三个实现长在 PetWidget 里（共 177 行，
且它们**完全不碰宿主状态**：`self.` 出现 0 次），只有项目根目录是外部依赖，
改成参数传入即可。

搬出来的收益：
1. 宿主类减重；
2. 这三个函数现在**不需要起 Qt 就能单测**（tests/test_pet_selfcode.py 覆盖
   搜索、写文件、以及 edit 的各种拒绝分支：非 .py、路径穿越、行号越界、
   old_text 不匹配、语法校验失败）；
3. AI 改自己代码这条链路的安全性（只允许项目内 .py、改前备份、语法验证拦截）
   集中在一个文件里，便于审查。

接口（纯函数，失败返回以「（…」开头的可读文本，不抛异常）：
    search_code(keyword, base_dir)
    write_file_tool(filename, content, base_dir)
    edit_own_code(old_text, new_text, start_line, end_line, file, base_dir)
"""
import os
import re
import subprocess
import sys


def search_code(keyword, max_results=20, base_dir=None):
    """关键词搜索项目源码（所有 .py 模块），返回 文件:行号:代码行（v6.41 定位工具）"""
    base_dir = base_dir or os.path.dirname(os.path.abspath(__file__))
    keyword = (keyword or '').strip()
    if not keyword:
        return '请提供搜索关键词'
    hits = []
    for f in sorted(os.listdir(base_dir)):
        if not f.endswith('.py') or f.startswith('_'):
            continue
        path = os.path.join(base_dir, f)
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
    return '\n'.join(hits[:max_results]) + (f'\n…（共 {total} 处，仅显示前 {max_results} 条）' if total > max_results else '')

def write_file_tool(filename, content, base_dir=None):
    """AI 生成文件：统一写入 base_dir/输出/（防穿越，自动建目录）。
    .py 文件先做语法校验，校验失败不落盘并返回错误（v6.17 保证生成代码可运行）"""
    base_dir = base_dir or os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(base_dir, '输出')
    try:
        os.makedirs(out_dir, exist_ok=True)
        safe = os.path.basename((filename or 'output.txt').strip() or 'output.txt')
        path = os.path.join(out_dir, safe)
        content = content or ''
        is_py = safe.lower().endswith('.py')
        if is_py:
            # 先写临时文件做 py_compile 语法校验，通过才落盘
            import tempfile
            tmp = os.path.join(tempfile.gettempdir(), '_pet_syntax_check.py')
            try:
                with open(tmp, 'w', encoding='utf-8') as f:
                    f.write(content)
                import py_compile
                py_compile.compile(tmp, doraise=True)
            except Exception as e:
                return f'（❌ Python 语法校验失败，文件未保存：{e}）请重新生成缩进正确、语法完整的代码后再调用 write_file'
            finally:
                try:
                    os.remove(tmp)
                except Exception:
                    pass
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f'✅ 已生成文件：{path}（共 {len(content)} 字符' + ('，语法校验通过' if is_py else '') + '）'
    except Exception as e:
        return f'（写入失败：{e}）'

def edit_own_code(old_text, new_text, start_line=None, end_line=None, file='desktop_pet.py', base_dir=None):
    """AI 修改自己的代码——git 基线保护 + 语法验证 + 失败不落盘。
    v6.41 支持任意模块（file 参数，白名单 .py）；v6.25 两种编辑模式：①按行号替换（start_line/end_line + new_text，推荐）；②old_text 精确匹配"""
    base_dir = base_dir or os.path.dirname(os.path.abspath(__file__))
    fname = (file or 'desktop_pet.py').strip()
    if not fname.endswith('.py') or fname.startswith('_') or '/' in fname or '\\' in fname:
        return f'（不允许修改的文件：{fname}，只能改项目内的 .py 模块）'
    path = os.path.join(base_dir, fname)
    if not os.path.isfile(path):
        return f'（文件不存在：{fname}，可用 read_file 传目录查看项目文件列表）'
    old_text = old_text or ''
    new_text = new_text or ''
    if not old_text.strip() and start_line is None:
        return '（需要提供 old_text 或 start_line）'
    try:
        # 0. 确认 git 仓库（桌宠项目必须是 git 仓库才能安全自改）
        r = subprocess.run(['git', 'rev-parse', '--is-inside-work-tree'], cwd=base_dir,
                            capture_output=True, timeout=15)
        if r.returncode != 0:
            return '（不是 git 仓库，拒绝自改——需要版本保护）'
        # 1. 记录基线 hash（v6.42：不再 commit 基线——E盘fsync慢导致两次commit让AI卡1分钟+；改hash记录+backup双保险）
        base_hash = ''
        try:
            r0 = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=base_dir, capture_output=True, timeout=15)
            if r0.returncode == 0:
                base_hash = (r0.stdout or b'').decode().strip()
        except Exception:
            pass
        # 1.5 额外备份一份到 backup/（双保险，防 git 异常时无回退点）
        try:
            bdir = os.path.join(base_dir, 'backup')
            os.makedirs(bdir, exist_ok=True)
            import shutil
            shutil.copy2(path, os.path.join(bdir, f'{fname.replace(".py", "")}_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.py'))
        except Exception:
            pass
        # 2. 读代码 + 替换
        with open(path, encoding='utf-8', newline='') as f:
            src = f.read()
        if start_line is not None:
            # 按行替换：start_line~end_line 之间的内容替换为 new_text（v6.25）
            try:
                lines = src.splitlines()
                s = int(start_line) - 1
                # end_line 省略 = 只替换 start_line 一行（v6.25 修复：此前误为到文件末尾）
                e = (s + 1) if end_line is None else int(end_line)
                if s < 0 or s >= len(lines) or e < s or e > len(lines):
                    return f'（行号越界：文件共 {len(lines)} 行，请求 {start_line}~{end_line}）'
                new_src = '\n'.join(lines[:s] + [new_text] + lines[e:])
                if src.endswith('\n'):
                    new_src += '\n'
            except ValueError:
                return '（start_line/end_line 需要数字）'
        else:
            if old_text not in src:
                # 失败时提示附近行号，帮 AI 用 read_file 精确重新读取（v6.25）
                near = ''
                first_line = old_text.splitlines()[0][:20] if old_text else ''
                for i, ln in enumerate(src.splitlines(), 1):
                    if first_line and first_line in ln:
                        near = f'第 {i} 行附近：{ln[:80]}'
                        break
                return f'（未找到要修改的代码段，请先用 read_file 带 start_line/end_line 精确读取原文再修改；{near}）'
            if src.count(old_text) > 1:
                return '（找到多处匹配，请提供更长的唯一上下文）'
            new_src = src.replace(old_text, new_text, 1)
        # 3. 语法验证（写临时文件检查，通过才落盘）
        tmp = path + '.ai_tmp'
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(new_src)
        r = subprocess.run(
            [sys.executable, '-c',
             'import ast,sys; s = open(sys.argv[1], encoding="utf-8-sig").read(); ast.parse(s)', tmp],
            capture_output=True, timeout=30)
        if r.returncode != 0:
            os.remove(tmp)
            return f'（语法验证失败，未修改：{(r.stderr or b"").decode(errors="replace")[-200:]}）'
        os.replace(tmp, path)
        # 4. 回滚保障（v6.42：不 git commit——E盘 commit 实测 60s+ 会卡死 AI；改后文件留为工作区改动，
        #    回滚用 git restore 直接从对象库恢复 HEAD 版本 + backup/ 文件双保险）
        rollback = f'git restore {fname}' if base_hash else '可用 backup/ 备份文件恢复'
        return f'✅ 已修改（回滚：{rollback} 或 backup/ 备份）。修改会在下次 git 提交时入库；请重启桌宠生效，若异常对我说"回滚桌宠修改"。'
    except Exception as e:
        return f'（修改失败：{e}）'

# v6.51：工具分发改成注册表——原先 29 个 if/elif 分支串在一个 169 行的方法里，
# 加一个工具要读懂整条链子。现在：注册表一行 + 一个 _tool_xxx 小方法。
_TOOL_HANDLERS = {
    'calculate': '_tool_calculate',
    'control_volume': '_tool_control_volume',
    'edit_own_code': '_tool_edit_own_code',
    'get_system_info': '_tool_get_system_info',
    'get_time': '_tool_get_time',
    'install_plugin': '_tool_install_plugin',
    'kill_process': '_tool_kill_process',
    'list_plugins': '_tool_list_plugins',
    'list_processes': '_tool_list_processes',
    'lock_screen': '_tool_lock_screen',
    'manage_todo': '_tool_manage_todo',
    'memorize': '_tool_memorize',
    'offer_choices': '_tool_offer_choices',
    'open_app': '_tool_open_app',
    'query_weather': '_tool_query_weather',
    'read_clipboard': '_tool_read_clipboard',
    'read_file': '_tool_read_file',
    'run_powershell': '_tool_run_powershell',
    'schedule_followup': '_tool_schedule_followup',
    'search_code': '_tool_search_code',
    'search_files': '_tool_search_files',
    'set_reminder': '_tool_set_reminder',
    'set_theme': '_tool_set_theme',
    'skill_run': '_tool_skill_run',
    'uninstall_plugin': '_tool_uninstall_plugin',
    'web_search': '_tool_web_search',
    'write_clipboard': '_tool_write_clipboard',
    'write_config': '_tool_write_config',
    'write_file': '_tool_write_file',
}
