# -*- coding: utf-8 -*-
"""
桌宠插件管理器（v6.21 插件系统骨架）
================================================
- plugins/<name>/plugin.json（元数据）+ plugin.py（实现，可选）
- 五类：tool（AI 工具）/ menu（右键菜单）/ rules（提示词规则）/ theme（QSS 主题，预留）/ skill（预留）
- 安全三道闸：JSON 校验 + ast 语法校验 + 危险操作扫描
- 失败隔离：单个插件加载失败不影响主程序

plugin.json 字段：
    name/version/description/type/enabled/entry/tools/menu/rules/theme

tool 插件实现约定（plugin.py）：
    def <工具名>(args: dict) -> str: 直接返回字符串结果
menu 插件实现约定：
    def menu_<command>(args=None): 返回提示文本或 None
"""
import os
import json
import ast
import threading
import importlib.util

# 危险操作关键词（命中则拒绝加载该插件）——只拦破坏性/自修改类，网络与文件读写是插件正常能力
DANGEROUS_PATTERNS = [
    'os.system', 'subprocess', 'shutil.rmtree', 'shutil.move',
    'os.remove', 'os.rmdir', 'os.unlink', 'os.replace',
    '__import__', 'eval(', 'exec(', 'compile(',
    'winreg', 'ctypes.windll', 'SendKeys', 'pyautogui',
]
# 允许的插件文件类型
ALLOWED_ENTRY_EXTS = ('.py',)


class PluginManager:
    """插件管理器：扫描/加载/分发"""

    def __init__(self, plugins_dir):
        self.dir = plugins_dir
        self.plugins = {}          # name -> {dir, meta, module}
        self._lock = threading.RLock()  # 可重入：install/uninstall 内部会再调 scan()
        os.makedirs(self.dir, exist_ok=True)
        self.scan()

    # ---------- 加载 ----------
    def scan(self):
        """全量扫描 plugins/ 目录，加载 enabled 插件（失败隔离）"""
        with self._lock:
            self.plugins = {}
            if not os.path.isdir(self.dir):
                return
            for entry in sorted(os.listdir(self.dir)):
                pdir = os.path.join(self.dir, entry)
                if not os.path.isdir(pdir):
                    continue
                meta_path = os.path.join(pdir, 'plugin.json')
                if not os.path.isfile(meta_path):
                    continue
                try:
                    with open(meta_path, 'r', encoding='utf-8-sig') as f:  # utf-8-sig 容错 BOM
                        meta = json.load(f)
                    if not isinstance(meta, dict):
                        continue
                    if meta.get('enabled', True) is False:
                        continue
                    name = str(meta.get('name') or entry)  # 强制 str（AI 可能把 name 写成数字等）
                    module = self._load_module(pdir, meta) if meta.get('entry') else None
                    self.plugins[name] = {'dir': pdir, 'meta': meta, 'module': module}
                except Exception as e:
                    print(f'[Plugin] {entry} 加载失败（已跳过）: {e}')

    def _load_module(self, pdir, meta):
        """加载插件 Python 实现：语法校验 + 危险扫描 + exec"""
        entry = meta.get('entry')
        if not entry:
            return None
        path = os.path.join(pdir, entry)
        if not os.path.isfile(path) or not entry.lower().endswith(ALLOWED_ENTRY_EXTS):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                src = f.read()
            ast.parse(src)  # ① 语法校验
            for pat in DANGEROUS_PATTERNS:  # ② 危险操作扫描
                if pat in src:
                    print(f'[Plugin] {meta.get("name")} 含危险操作关键词「{pat}」，已拒绝加载')
                    return None
            spec = importlib.util.spec_from_file_location(
                f'pet_plugin_{meta.get("name", "x")}', path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # ③ 执行（失败由外层隔离）
            return mod
        except Exception as e:
            print(f'[Plugin] {meta.get("name")} 模块加载失败（已跳过）: {e}')
            return None

    # ---------- tool 插件 ----------
    def tool_schemas(self):
        """返回合并进 AI_TOOLS 的工具定义（只含实现加载成功的 tool 插件，v6.22）"""
        out = []
        for name, p in self.plugins.items():
            if p['meta'].get('type') == 'tool' and p['module'] is None:
                continue  # 实现加载失败的工具插件不暴露（否则有 schema 但调用失败）
            for t in (p['meta'].get('tools') or []):
                if not isinstance(t, dict) or not t.get('name'):
                    continue
                out.append({
                    'type': 'function',
                    'function': {
                        'name': t['name'],
                        'description': t.get('description') or f'[{name}] 插件工具',
                        'parameters': t.get('parameters') or {'type': 'object', 'properties': {}},
                    },
                })
        return out

    def tool_names(self):
        names = []
        for p in self.plugins.values():
            for t in (p['meta'].get('tools') or []):
                if t.get('name'):
                    names.append(t['name'])
        return names

    def handle_tool(self, tool_name, args):
        """按工具名找到插件模块里的同名函数并调用"""
        for pname, p in self.plugins.items():
            mod = p['module']
            if mod is None:
                continue
            handler = getattr(mod, tool_name, None)
            if callable(handler):
                try:
                    return handler(args or {})
                except Exception as e:
                    return f'（插件工具 {tool_name} 执行失败：{e}）'
        return f'（未找到插件工具 {tool_name}，请检查插件是否启用）'

    # ---------- menu 插件 ----------
    def menu_items(self):
        """[(label, command, plugin_name), ...]"""
        out = []
        for pname, p in self.plugins.items():
            for m in (p['meta'].get('menu') or []):
                if m.get('label') and m.get('command'):
                    out.append((m['label'], m['command'], pname))
        return out

    def handle_menu(self, command):
        for pname, p in self.plugins.items():
            mod = p['module']
            if mod is None:
                continue
            handler = getattr(mod, f'menu_{command}', None)
            if callable(handler):
                try:
                    return handler()
                except Exception as e:
                    return f'（菜单插件执行失败：{e}）'
        return None

    # ---------- rules 插件 ----------
    def rules_text(self):
        """收集所有 rules 插件的规则内容（注入 system prompt）"""
        parts = []
        for pname, p in self.plugins.items():
            rpath = p['meta'].get('rules')
            if not rpath:
                continue
            fpath = os.path.join(p['dir'], rpath)
            if os.path.isfile(fpath):
                try:
                    with open(fpath, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                    if content:
                        parts.append(content)
                except Exception:
                    pass
        return '\n'.join(parts)

    # ---------- theme 插件（v6.23） ----------
    def theme_names(self):
        """已启用的 theme 插件名列表"""
        return [name for name, p in self.plugins.items() if p['meta'].get('type') == 'theme']

    def theme_vars(self, name=None):
        """读取 theme 插件的颜色变量。theme 字段支持两种写法（v6.23.1 容错）：
        ① 字符串=颜色变量 json 文件路径；② 对象=内联颜色变量（AI 常见写法）"""
        out = {}
        for pname, p in self.plugins.items():
            if p['meta'].get('type') != 'theme':
                continue
            if name and pname != name:
                continue
            t = p['meta'].get('theme')
            if isinstance(t, dict):
                # 内联颜色对象
                out.update({k: v for k, v in t.items()})
            elif isinstance(t, str) and t:
                fpath = os.path.join(p['dir'], t)
                if os.path.isfile(fpath):
                    try:
                        with open(fpath, 'r', encoding='utf-8') as f:
                            vars_ = json.load(f)
                        if isinstance(vars_, dict):
                            out.update({k: v for k, v in vars_.items()})
                    except Exception:
                        pass
        return out

    # ---------- skill 复合技能插件（v6.23） ----------
    def skill_names(self):
        return [name for name, p in self.plugins.items() if p['meta'].get('type') == 'skill']

    def skill_steps(self, name):
        """返回 skill 插件的执行步骤文本（AI 照着做）"""
        p = self.plugins.get(name)
        if p is None or p['meta'].get('type') != 'skill':
            return None
        steps = p['meta'].get('steps') or []
        desc = p['meta'].get('description', '')
        lines = [f'技能「{name}」执行步骤（{desc}）：']
        lines += [f'{i + 1}. {s}' for i, s in enumerate(steps)]
        lines.append('按步骤依次执行，每步完成后继续下一步。')
        return '\n'.join(lines)

    # ---------- 安装 / 卸载 ----------
    def install(self, name, meta, entry_content=None, rules_content=None):
        """安装插件（AI 通道）：校验 + 写入 + 热加载。返回 (ok, message)"""
        # ① 名称合法性（强制 str，防 AI 传数字/None）
        import re
        name = str(name or '').strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,32}', name):
            return False, '插件名只能含字母/数字/下划线/连字符（≤32 字符）'
        # ② meta 校验
        if not isinstance(meta, dict) or not meta.get('type'):
            return False, 'plugin.json 需要包含 type 字段（tool/menu/rules/theme/skill）'
        if meta.get('type') not in ('tool', 'menu', 'rules', 'theme', 'skill'):
            return False, f"未知插件类型 {meta.get('type')}"
        if meta.get('entry') and not entry_content:
            return False, '声明了 entry 但没提供代码内容'
        # ③ entry 语法 + 危险扫描
        if entry_content:
            try:
                ast.parse(entry_content)
            except SyntaxError as e:
                return False, f'Python 语法错误：{e}'
            for pat in DANGEROUS_PATTERNS:
                if pat in entry_content:
                    return False, f'代码含危险操作「{pat}」，已拒绝安装'
        # 写入
        pdir = os.path.join(self.dir, name)
        try:
            os.makedirs(pdir, exist_ok=True)
            meta.setdefault('name', name)
            meta['name'] = str(meta['name'])  # 强制 str（防 AI 把 name 写成数字）
            meta.setdefault('version', '1.0.0')
            meta.setdefault('enabled', True)
            with open(os.path.join(pdir, 'plugin.json'), 'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            if meta.get('entry') and entry_content:
                with open(os.path.join(pdir, meta['entry']), 'w', encoding='utf-8') as f:
                    f.write(entry_content)
            # rules 类插件：写入规则内容文件
            if meta.get('type') == 'rules' and meta.get('rules') and rules_content:
                with open(os.path.join(pdir, meta['rules']), 'w', encoding='utf-8') as f:
                    f.write(rules_content)
        except Exception as e:
            return False, f'写入失败：{e}'
        # 热加载
        self.scan()
        if name in self.plugins:
            return True, f'✅ 插件 {name} 已安装并生效'
        if meta.get('enabled') is False:
            return True, f'✅ 插件 {name} 已写入（enabled=false 处于禁用状态，启用后生效）'
        return False, '插件写入成功但加载失败（见控制台日志），可执行 list_plugins 查看状态'

    def uninstall(self, name):
        import shutil
        name = str(name or '')  # 强制 str（防 AI 传数字等非字符串，v6.23.1 修复）
        with self._lock:
            if name not in self.plugins and not os.path.isdir(os.path.join(self.dir, name)):
                return False, f'插件 {name} 不存在'
            pdir = os.path.join(self.dir, name)
            try:
                shutil.rmtree(pdir)
            except Exception as e:
                return False, f'卸载失败：{e}'
            self.scan()
            return True, f'✅ 插件 {name} 已卸载'

    # ---------- 状态 ----------
    def status_text(self):
        if not self.plugins:
            return '未安装插件'
        parts = []
        for name, p in self.plugins.items():
            meta = p['meta']
            t = meta.get('type', '?')
            tools = len(meta.get('tools') or [])
            parts.append(f'{name}({t}' + (f',{tools}工具' if tools else '') + ')')
        return '；'.join(parts)
