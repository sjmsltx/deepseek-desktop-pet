# -*- coding: utf-8 -*-
"""pet_selfcode.py — 桌宠"看/改自己代码"的工具（2026-09-12 从 PetWidget 搬出）
============================================================================
原先 search_code / write_file / edit_own_code 三个实现长在 PetWidget 里（共 177 行，
且 `self.` 出现 0 次、完全不碰宿主状态），只有项目根目录是外部依赖，
改成 base_dir 参数（默认 None 时回退到本模块所在目录，也就是项目根）。

搬出来的收益：
1. 宿主类减重；
2. 这三个函数现在不需要起 Qt 就能单测；
3. 「AI 改自己代码」这条链路的安全性（只允许项目内 .py、改前备份、语法验证拦截）
   集中在一个文件里，便于审查。

v6.56 修复（2026-09-15，自改代码"几乎没成功过"的根因）：
  R1 **行尾无关匹配** —— 原先用 `old_text in src` 精确匹配；但项目内文件行尾不统一
     （desktop_pet.py 是 LF、memory_engine.py/tools_registry.py 是 CRLF），
     而 AI 经 JSON 传来的 old_text 一律是 LF → 在 CRLF 文件上**必然匹配失败**。
     现在改成"按行归一化后匹配连续行块"，并支持行尾空格差异。
  R2 **保留原文件行尾** —— 原先读用 newline='' + splitlines() + '\\n'.join()，
     会把整个文件行尾改写成 LF（实测 CRLF 444 → 0，git diff 爆炸）。现在按原文件行尾写回。
  R3 **备份修复** —— 原先 `datetime.datetime.now()` 但模块未 import datetime，
     NameError 被静默吞掉 → backup/ 一直为空，返回消息却提示"可用 backup 恢复"。
     现在真正写备份，并只在备份成功时才提它。
  R4 **语法校验改进程内 ast.parse** —— 原先 `subprocess.run([sys.executable, '-c', ...])`，
     冻结（PyInstaller）环境下 sys.executable 是桌宠 exe 本身 → 校验变成"再启动一只桌宠"。
  R5 **失败可见** —— 4 处 `except Exception: pass` 改为写日志（pet_log），不再静默。
  R6 冻结环境明确提示（打包版代码在 _internal 内、无 .git，改了也不生效）。

接口（纯函数，失败返回「（…」开头的可读文本，不抛异常）：
    search_code(keyword, max_results=20, base_dir=None)
    write_file_tool(filename, content, base_dir=None)
    edit_own_code(old_text, new_text, start_line=None, end_line=None, file='desktop_pet.py', base_dir=None)
"""
import ast
import os
import subprocess
import shutil
import sys


def _log(where, exc):
    """v6.56：本模块统一出口——只记日志，不改变行为（原先 4 处静默吞异常，出问题无从查）"""
    try:
        from pet_log import get_logger
        get_logger('selfcode').info('%s | %s: %s', where, type(exc).__name__, exc)
    except Exception:
        pass


def _norm_lines(text):
    """按行切分（兼容 CRLF/LF），并去掉每行尾部空白，便于"行尾无关"匹配"""
    return [ln.rstrip() for ln in (text or '').replace('\r\n', '\n').split('\n')]


def _file_eol(src):
    """探测原文件行尾风格（v6.56：写回时必须沿用，否则整文件被改写）"""
    return '\r\n' if '\r\n' in src else '\n'


def search_code(keyword, max_results=20, base_dir=None):
    """关键词搜索项目源码（所有 .py 模块，含子目录），返回 文件:行号:代码行（v6.41 定位工具）"""
    base_dir = base_dir or os.path.dirname(os.path.abspath(__file__))
    keyword = (keyword or '').strip()
    if not keyword:
        return '请提供搜索关键词'
    hits = []
    skip = {'backup', 'release_build', '__pycache__', '.git', '输出', 'node_modules'}
    for cur, dirs, files in os.walk(base_dir):
        dirs[:] = [d for d in dirs if d not in skip and not d.startswith('.')]
        for f in sorted(files):
            if not f.endswith('.py') or f.startswith('_'):
                continue
            rel = os.path.relpath(os.path.join(cur, f), base_dir)
            try:
                with open(os.path.join(cur, f), encoding='utf-8', errors='ignore') as fh:
                    for i, line in enumerate(fh, 1):
                        if keyword.lower() in line.lower():
                            hits.append(f'{rel}:{i}: {line.strip()[:100]}')
                            if len(hits) >= max_results:
                                break
            except Exception as e:
                _log('search_code', e)
            if len(hits) >= max_results:
                break
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
            try:
                ast.parse(content)   # v6.56：改进程内校验（冻结版也可用）
            except SyntaxError as e:
                return f'（❌ Python 语法校验失败，文件未保存：第 {e.lineno} 行 {e.msg}）请重新生成缩进正确、语法完整的代码后再调用 write_file'
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f'✅ 已生成文件：{path}（共 {len(content)} 字符' + ('，语法校验通过' if is_py else '') + '）'
    except Exception as e:
        _log('write_file_tool', e)
        return f'（写入失败：{e}）'


def edit_own_code(old_text, new_text, start_line=None, end_line=None, file='desktop_pet.py', base_dir=None):
    """AI 修改自己的代码——git 基线保护 + 语法验证 + 失败不落盘。

    v6.41 支持任意模块（file 参数，白名单 .py）；v6.25 两种编辑模式：
      ①按行号替换（start_line/end_line + new_text，推荐）；②old_text 匹配
    v6.56：old_text 匹配改为**行尾无关**（CRLF/LF 都能匹配、行尾空格差异容忍）、
           写回时**保留原文件行尾**、备份真正可用、语法校验进程内完成。
    """
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
        # 0. 版本保护：必须在 git 工作区内（v6.56：冻结环境给出明确原因）
        r = subprocess.run(['git', 'rev-parse', '--is-inside-work-tree'], cwd=base_dir,
                           capture_output=True, timeout=15)
        if r.returncode != 0:
            if getattr(sys, 'frozen', False):
                return ('（打包版无法自改：打包后的代码在 _internal 内、且没有 .git，改了也不会生效。'
                        '请用源码目录运行 python desktop_pet.py 后再让我改）')
            return '（不是 git 仓库，拒绝自改——需要版本保护）'
        base_hash = ''
        try:
            r0 = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=base_dir, capture_output=True, timeout=15)
            if r0.returncode == 0:
                base_hash = (r0.stdout or b'').decode().strip()
        except Exception as e:
            _log('git_head', e)
        # 2. 读 + 匹配（v6.56：先匹配成功、再写备份 —— 避免失败也留备份的噪音）
        with open(path, encoding='utf-8', newline='') as f:
            src = f.read()
        eol = _file_eol(src)
        lines = src.splitlines()
        tail_eol = src.endswith(('\n', '\r\n'))
        if start_line is not None:
            try:
                s = int(start_line) - 1
                e = (s + 1) if end_line is None else int(end_line)
                if s < 0 or s >= len(lines) or e < s or e > len(lines):
                    return f'（行号越界：文件共 {len(lines)} 行，请求 {start_line}~{end_line}）'
                new_lines = lines[:s] + new_text.replace('\r\n', '\n').split('\n') + lines[e:]
                where = f'第 {start_line}~{e} 行'
            except ValueError:
                return '（start_line/end_line 需要数字）'
            new_src = eol.join(new_lines) + (eol if tail_eol else '')
        else:
            old_n = _norm_lines(old_text)
            if old_n and old_n[-1] == '':
                old_n.pop()          # 末尾换行不算内容
            if not old_n:
                return '（old_text 为空）'
            n = len(old_n)
            cand = [i for i in range(max(0, len(lines) - n + 1))
                    if _norm_lines('\n'.join(lines[i:i + n])) == old_n]
            if len(cand) == 1:
                i = cand[0]
                new_lines = lines[:i] + new_text.replace('\r\n', '\n').split('\n') + lines[i + n:]
                new_src = eol.join(new_lines) + (eol if tail_eol else '')
                where = f'第 {i + 1}~{i + n} 行（按文本匹配）'
            elif len(cand) > 1:
                return f'（找到 {len(cand)} 处匹配（行 {cand[:5]}…），请提供更长的唯一上下文，或改用 start_line/end_line）'
            else:
                # 回退：兼容旧语义——整行块匹配不到时，再按“归一化后的行内子串”匹配
                src_n = src.replace('\r\n', '\n')
                old_s = old_text.replace('\r\n', '\n')
                cnt = src_n.count(old_s)
                if cnt == 0:
                    first = old_n[0][:20]
                    near = ''
                    for i, ln in enumerate(lines, 1):
                        if first and first in ln:
                            near = f'第 {i} 行附近：{ln[:80]}'
                            break
                    return (f'（未找到要修改的代码段（已按行尾无关匹配）{near}）'
                            f'建议改用按行号模式：read_file 拿准行号后传 start_line/end_line + new_text')
                if cnt > 1:
                    return f'（该文本在文件中出现 {cnt} 次，请提供更长的唯一上下文，或改用 start_line/end_line）'
                new_src = src_n.replace(old_s, new_text.replace('\r\n', '\n'), 1).replace('\n', eol)
                where = '按文本片段匹配'
        # 2.5 写备份（匹配已成功才备份）
        backup_name = ''
        try:
            import datetime as _dt
            bdir = os.path.join(base_dir, 'backup')
            os.makedirs(bdir, exist_ok=True)
            backup_name = f'{fname[:-3]}_{_dt.datetime.now().strftime("%Y%m%d_%H%M%S")}.py'
            shutil.copy2(path, os.path.join(bdir, backup_name))
        except Exception as e:
            _log('backup', e)
            backup_name = ''
        # 3. 语法验证（v6.56：进程内 ast.parse，冻结版同样可用）
        try:
            ast.parse(new_src)
        except SyntaxError as e:
            return f'（语法验证失败，未修改：第 {e.lineno} 行 {e.msg}）'
        # 4. 原子落盘（行尾沿用原文件）
        tmp = path + '.ai_tmp'
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(new_src)
        os.replace(tmp, path)
        # 5. 返回（v6.56：只在备份真的成功时才提它；给出文件与行号）
        rollback = f'git restore {fname}' if base_hash else 'backup/ 备份'
        bk = f'（改前备份：backup/{backup_name}）' if backup_name else '（⚠️ 改前备份失败，已记日志）'
        return (f'✅ 已修改 {fname} {where}。回滚：{rollback}。{bk}\n'
                f'修改会在下次 git 提交时入库；**需重启桌宠生效**；若异常对我说"回滚桌宠修改"。')
    except Exception as e:
        _log('edit_own_code', e)
        return f'（修改失败：{type(e).__name__}: {e}）'
