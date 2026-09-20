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
# _load_module 的哨兵：策略拒绝（永禁代码 / 权限未确认）——调用方不要把它当成已加载
REJECTED = object()


class PluginManager:
    """插件管理器：扫描/加载/分发"""

    def __init__(self, plugins_dir):
        self.dir = plugins_dir
        self.plugins = {}          # name -> {dir, meta, module}
        self.rejected = {}         # name -> 拒绝原因（安全策略），给界面/诊断看
        self._lock = threading.RLock()  # 可重入：install/uninstall 内部会再调 scan()
        os.makedirs(self.dir, exist_ok=True)
        self.scan()

    # ---------- 加载 ----------
    def scan(self):
        """全量扫描 plugins/ 目录，加载 enabled 插件（失败隔离）"""
        with self._lock:
            self.plugins = {}
            self.rejected = {}
            if not os.path.isdir(self.dir):
                return
            for entry in sorted(os.listdir(self.dir)):
                pdir = os.path.join(self.dir, entry)
                if not os.path.isdir(pdir):
                    continue
                if entry.startswith('_'):      # _registry.json / _uninstalled / _tmp 等内部目录
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
                    if not meta.get('entry'):
                        self.plugins[name] = {'dir': pdir, 'meta': meta, 'module': None}
                        continue
                    module = self._load_module(pdir, meta)
                    if module is REJECTED:
                        # 安全策略拒载：**不挂进 plugins**（旧版会挂成 module=None，
                        # 看着像加载了，实际上只会在列表里捣乱，v6.67 修正）
                        self.rejected[name] = getattr(self, '_last_reject', '') or '安全策略拒载'
                        continue
                    self.plugins[name] = {'dir': pdir, 'meta': meta, 'module': module}
                except Exception as e:
                    print(f'[Plugin] {entry} 加载失败（已跳过）: {e}')

    def _load_module(self, pdir, meta):
        """加载插件 Python 实现：语法校验 + 静态扫描（分级）+ exec"""
        entry = meta.get('entry')
        if not entry:
            return None
        path = os.path.join(pdir, entry)
        if not os.path.isfile(path) or not entry.lower().endswith(ALLOWED_ENTRY_EXTS):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                src = f.read()
            import skill_pack
            declared = (meta.get('permissions') or {}).keys()
            # manifest_version ≥ 2 才按新规严管；v1 老插件只拦永禁（不误伤已有插件）
            strict = int(meta.get('manifest_version') or 1) >= 2
            ok, msg, _needed = skill_pack.scan_code(src, declared, strict=strict,
                                                    builtin=bool(meta.get('builtin')))   # ① 语法 + 永禁/分级扫描
            if not ok:
                print(f'[Plugin] {meta.get("name")} 拒绝加载：{msg}')
                self._last_reject = msg
                return REJECTED
            if not strict:
                self._last_reject = ''
                return self._exec_module(path, meta)
            # ② 声明了但使用者还没确认的权限 → 也不加载（避免未授权能力被用上）
            #    · 登记表里有 pending → 未确认
            #    · 没登记、不是随程序自带的官方包、却声明了权限 → 视为“手工塞进来的”，也要求先确认
            reg = skill_pack.read_registry(self.dir).get(str(meta.get('name'))) or {}
            declared = sorted((meta.get('permissions') or {}).keys())
            pending = list(reg.get('pending') or [])
            if not reg and declared and not meta.get('builtin'):
                pending = declared
            if pending:
                print(f'[Plugin] {meta.get("name")} 权限未确认（{"、".join(pending)}），暂不加载')
                self._last_reject = '权限未确认：' + '、'.join(pending)
                return REJECTED
            return self._exec_module(path, meta)
        except Exception as e:
            print(f'[Plugin] {meta.get("name")} 模块加载失败（已跳过）: {e}')
            return None

    def _exec_module(self, path, meta):
        """真正执行插件代码（已过语法/安全校验）"""
        try:
            spec = importlib.util.spec_from_file_location(
                f'pet_plugin_{meta.get("name", "x")}', path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # 执行（失败由外层隔离）
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
        # ② meta 校验（v6.67：走技能包规范，字段/类型/权限类别全检）
        import skill_pack
        ok, vmsg, meta = skill_pack.validate_manifest(meta, name_hint=name)
        if not ok:
            return False, vmsg
        if meta.get('entry') and not entry_content:
            return False, '声明了 entry 但没提供代码内容'
        # ③ entry 语法 + 静态扫描（永禁直接拒 / 分级关键词需声明权限）
        if entry_content:
            ok, msg, _needed = skill_pack.scan_code(entry_content, (meta.get('permissions') or {}).keys(),
                                                    builtin=bool(meta.get('builtin')))
            if not ok:
                return False, msg
        # 写入
        pdir = os.path.join(self.dir, name)
        declared = sorted((meta.get('permissions') or {}).keys())
        if declared:
            # v6.67：声明了权限 → 先落地但**禁用**，等使用者确认后再启用（不默认放行）
            meta['enabled'] = False
        try:
            os.makedirs(pdir, exist_ok=True)
            meta['name'] = str(meta['name'])  # 强制 str（防 AI 把 name 写成数字）
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
            # 登记来源/哈希/权限（来源=AI 通道）
            reg = skill_pack.read_registry(self.dir)
            reg[name] = {'version': meta.get('version', '1.0.0'), 'source': 'ai',
                         'installed_at': int(time.time()), 'hash': skill_pack.dir_hash(pdir),
                         'declared': declared, 'granted': [], 'pending': declared,
                         'enabled': bool(meta.get('enabled', True))}
            skill_pack.write_registry(self.dir, reg)
        except Exception as e:
            return False, f'写入失败：{e}'
        # 热加载
        self.scan()
        if name in self.plugins:
            return True, f'✅ 插件 {name} 已安装并生效'
        if declared:
            return True, ('✅ 插件 %s 已写入，但它申请了权限（%s），需确认后才启用'
                          % (name, '、'.join('%s %s' % (c, skill_pack.PERMISSIONS[c][0]) for c in declared)))
        if meta.get('enabled') is False:
            return True, f'✅ 插件 {name} 已写入（enabled=false 处于禁用状态，启用后生效）'
        return False, '插件写入成功但加载失败（见控制台日志），可执行 list_plugins 查看状态'

    def uninstall(self, name):
        """卸载（v6.67）：**移进停放区**而不是 rmtree 直接删，可找回

        旧实现用 shutil.rmtree，误删/误装无法恢复；现在交给 skill_pack.uninstall。
        """
        name = str(name or '')
        if name not in self.plugins and not os.path.isdir(os.path.join(self.dir, name)):
            return False, f'插件 {name} 不存在'
        import skill_pack
        import governance as gov
        with self._lock:
            ok, msg = skill_pack.uninstall(self.dir, name)
            gov.log_event('uninstall', 'skill:' + name, 'uninstall', msg, allowed=bool(ok))
            self.scan()
            return ok, msg

    # ---------- 技能包（v6.67 skill_pack 接入）----------
    def tool_owner(self, tool_name):
        """工具名 → 它属于哪个技能包（审计/额度用；找不到就返回工具名本身）"""
        for name, p in self.plugins.items():
            for t in (p['meta'].get('tools') or []):
                if t.get('name') == tool_name:
                    return name
        return str(tool_name)
    def packs(self):
        """列出技能包（含来源/版本/权限状态）—— 给设置界面与管理类工具用"""
        import skill_pack
        return skill_pack.list_packs(self.dir)

    def set_enabled(self, name, flag):
        """启用/禁用技能包（热生效，不需重启）"""
        import skill_pack
        import governance as gov
        with self._lock:
            ok, msg = skill_pack.set_enabled(self.dir, name, flag)
            gov.log_event('enable' if flag else 'disable', 'skill:' + str(name),
                          'set_enabled', msg, allowed=bool(ok))
            self.scan()
            return ok, msg

    def grant(self, name, perms):
        """确认技能包申请的权限（确认全部后才能启用）"""
        import skill_pack
        import governance as gov
        with self._lock:
            ok, msg = skill_pack.grant_permissions(self.dir, name, perms)
            gov.log_event('grant', 'skill:' + str(name), 'grant',
                          '%s → %s' % ('、'.join(perms or []), msg), allowed=bool(ok))
            self.scan()
            return ok, msg

    def install_pack(self, path):
        """从本地目录 / zip 安装技能包（按路径后缀判定），走完整校验"""
        import skill_pack
        import governance as gov
        path = str(path or '')
        with self._lock:
            if os.path.isdir(path):
                ok, msg, name = skill_pack.install_from_dir(path, self.dir, source='dir')
            elif os.path.isfile(path) and path.lower().endswith('.zip'):
                ok, msg, name = skill_pack.install_from_zip(path, self.dir, source='zip')
            else:
                return False, '请给我一个技能包目录或 .zip 文件'
            gov.log_event('install', 'skill:' + str(name or path), 'install',
                          '%s → %s' % (path, msg), allowed=bool(ok))
            self.scan()
            return ok, msg

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
