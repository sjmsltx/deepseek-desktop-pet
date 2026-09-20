# -*- coding: utf-8 -*-
"""
MCP 桥接器（桌宠插件系统 MCP 连接器 v6.20）
================================================
让桌宠 AI 能调用外部 MCP server 的工具——社区几千个 MCP server 直接接入，
无需为每个工具写插件代码（MCP 是跨 harness 的行业标准工具协议，DSH/OpenClaw 同协议）。

配置（config.json）：
    "mcp_servers": [
        {"name": "files", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "<你的目录>"]},
        {"name": "remote", "url": "https://example.com/mcp"}
    ]

工作方式：
    - 每个 server 一个常驻后台线程 + 独立事件循环（asyncio.run_forever 保持连接）
    - 连接后 list_tools → 合并进 AI_TOOLS（工具名 mcp_<server>_<tool>）
    - AI 调用 → run_coroutine_threadsafe 转发到对应 server
"""
import asyncio
import json
import threading
import time

# ---------------- 权限策略（v6.68）----------------
# MCP 工具的“写不写”判断顺序：① server 给的注解 ② 工具名动词 ③ 都不认识 → 保守要求确认
READ_VERBS = ('read', 'list', 'get', 'search', 'find', 'query', 'info', 'status', 'describe',
              'show', 'view', 'stat', 'count', 'head', 'ls', 'dir', 'scan', 'inspect', 'check')
WRITE_VERBS = ('write', 'create', 'add', 'update', 'delete', 'remove', 'move', 'rename', 'copy',
               'edit', 'modify', 'set', 'put', 'post', 'patch', 'exec', 'run', 'call', 'send',
               'kill', 'install', 'uninstall', 'mkdir', 'touch', 'append', 'merge', 'upload',
               'download', 'save', 'commit', 'push', 'publish', 'apply', 'replace', 'insert')

# ---------------- 推荐清单（一键添加；全部默认关，不替你改配置）----------------
CATALOG = (
    {'key': 'time', 'title': '时间（官方示例）', 'transport': 'stdio',
     'command': 'uvx', 'args': ['mcp-server-time'], 'readonly': True,
     'note': '查/换算时区时间，纯只读，依赖本机 uvx 或 npx'},
    {'key': 'filesystem', 'title': '文件系统（只读模式）', 'transport': 'stdio',
     'command': 'npx', 'args': ['-y', '@modelcontextprotocol/server-filesystem'],
     'readonly': True, 'note': '读写本地指定目录；只读模式请把参数填成 --readonly 加目录'},
    {'key': 'fetch', 'title': '网页抓取', 'transport': 'stdio',
     'command': 'uvx', 'args': ['mcp-server-fetch'], 'readonly': True,
     'note': '抓网页转 Markdown（会联网）'},
    {'key': 'sqlite', 'title': 'SQLite', 'transport': 'stdio',
     'command': 'uvx', 'args': ['mcp-server-sqlite', '--db-path', '数据库文件路径'], 'readonly': False,
     'note': '查/改本地 SQLite 数据库（需自己填 db 路径）'},
    {'key': 'git', 'title': 'Git 仓库', 'transport': 'stdio',
     'command': 'uvx', 'args': ['mcp-server-git', '--repository', '仓库路径'], 'readonly': False,
     'note': '看/操作本地 git 仓库（需自己填仓库路径）'},
)


def classify_tool(tool):
    """返回 (read_only, why)：判断这个 MCP 工具是不是只读

    顺序：① server 的 annotations ② 名字里的动词 ③ 不认识就当“要确认”
    """
    if tool.get('destructive'):
        return False, 'server 标注为破坏性操作'
    if tool.get('read_only'):
        return True, 'server 标注只读'
    name = str(tool.get('name') or '').lower()
    has_read = any(v in name for v in READ_VERBS)
    has_write = any(v in name for v in WRITE_VERBS)
    if has_write and not has_read:
        return False, '名字含写类动词（%s）' % next(v for v in WRITE_VERBS if v in name)
    if has_read and not has_write:
        return True, '名字含读类动词（%s）' % next(v for v in READ_VERBS if v in name)
    if has_read and has_write:
        return False, '名字读写动词都有，保守处理'
    return False, '名字看不出是读还是写，保守处理'


class _McpConnection(threading.Thread):
    """单个 MCP server 的常驻连接（独立事件循环，线程内 run_forever）"""

    def __init__(self, name, spec):
        super().__init__(daemon=True)
        self.name = name
        self.spec = spec          # {'name', 'command'/'url', ...}
        self.loop = None
        self.session = None
        self.tools = []           # [{name, description, inputSchema, read_only, destructive}]
        self.error = None
        self._hold = None         # 撑住连接的 Future（stop() 靠取消它来断开）

    def run(self):
        try:
            with asyncio.Runner() as runner:  # 3.11+ 推荐：管理独立事件循环
                self.loop = runner.get_loop()
                runner.run(self._serve())     # _serve 内部 Future 挂起 → 常驻
        except asyncio.CancelledError:
            pass                              # stop() 主动断开：正常路径，不当错误
        except Exception as e:
            import traceback
            self.error = f'{e}\n{traceback.format_exc()}'

    async def _serve(self):
        """连接 + 列工具 + 永久挂起保持连接（async with 上下文不退出）"""
        try:
            from mcp import ClientSession
            if self.spec.get('url'):
                from mcp.client.streamable_http import streamable_http_client
                cm = streamable_http_client(self.spec['url'])
            else:
                from mcp import StdioServerParameters
                from mcp.client.stdio import stdio_client
                params = StdioServerParameters(command=self.spec['command'], args=self.spec.get('args') or [], env=None)
                cm = stdio_client(params)
            async with cm as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self.session = session
                    self._hold = asyncio.get_running_loop().create_future()
                    result = await session.list_tools()
                    tools = []
                    for t in result.tools:
                        # ★ v6.68 fix：本 SDK 版本字段名是 inputSchema（不是 input_schema）。
                        #   ——旧代码写 t.input_schema 直接抛 AttributeError，整个连接挂掉、
                        #   工具数永远是 0。只有拿**真实 MCP server** 接才会暴露这个 bug。
                        schema = (getattr(t, 'input_schema', None)
                                  or getattr(t, 'inputSchema', None) or {})
                        ann = getattr(t, 'annotations', None)
                        tools.append({
                            'name': t.name,
                            'description': t.description or '',
                            'inputSchema': schema or {},
                            'read_only': bool(getattr(ann, 'readOnlyHint', False)) if ann else False,
                            'destructive': bool(getattr(ann, 'destructiveHint', False)) if ann else False,
                        })
                    self.tools = tools
                    try:
                        await self._hold   # 永久挂起，保持连接（stop() 会取消它）
                    except asyncio.CancelledError:
                        pass               # 主动断开：安静退出上下文
                    else:
                        try:
                            import governance as gov
                            gov.log_event('connect', 'mcp:' + self.name, 'connected',
                                          '%d 个工具' % len(tools))
                        except Exception:
                            pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            import traceback
            self.error = f'{e}\n{traceback.format_exc()}'
            try:
                import governance as gov
                gov.log_event('error', 'mcp:' + self.name, 'connect_failed', str(e)[:200], allowed=False)
            except Exception:
                pass

    def stop(self, timeout=4):
        """断开：取消撑住的 Future，让 async with 正常退出（子进程跟着结束）"""
        try:
            if self.loop is not None and self._hold is not None and not self._hold.done():
                self.loop.call_soon_threadsafe(self._hold.cancel)
        except Exception:
            pass
        try:
            self.join(timeout)
        except Exception:
            pass
        self.session = None
        self.tools = []

    def call(self, tool_name, args, timeout=60):
        if self.loop is None or self.session is None:
            return f'（MCP server {self.name} 未连接）'
        fut = asyncio.run_coroutine_threadsafe(self._call(tool_name, args), self.loop)
        try:
            return fut.result(timeout=timeout)
        except asyncio.TimeoutError:
            return f'（MCP 调用超时：{self.name}/{tool_name}）'
        except Exception as e:
            return f'（MCP 调用失败：{e}）'

    async def _call(self, tool_name, args):
        try:
            result = await self.session.call_tool(tool_name, args or {})
            if getattr(result, 'is_error', False):
                return f'（MCP 错误）{result}'
            texts = []
            for c in (result.content or []):
                if hasattr(c, 'text'):
                    texts.append(c.text)
                else:
                    texts.append(str(c))
            return '\n'.join(texts) if texts else '（无输出）'
        except Exception as e:
            return f'（MCP 工具执行失败：{e}）'


class McpBridge:
    """MCP 桥接器：管理多个 server 连接，提供工具列表与调用转发"""

    def __init__(self, config_path):
        self.config_path = config_path
        self.conns = {}          # name -> _McpConnection
        self._specs = []
        self.logs = []           # 最近事件（连接/错误），给管理界面看
        self._load_config()

    # ---------- 日志 ----------
    def _log(self, text):
        self.logs.append((time.strftime('%H:%M:%S'), str(text)[:200]))
        self.logs = self.logs[-60:]

    # ---------- 配置 ----------
    def _read_cfg(self):
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _write_cfg(self, servers):
        cfg = self._read_cfg()
        cfg['mcp_servers'] = servers
        try:
            tmp = self.config_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            import os
            os.replace(tmp, self.config_path)
            return True
        except Exception as e:
            self._log('写配置失败：%s' % e)
            return False

    def _load_config(self):
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            servers = cfg.get('mcp_servers') or []
            if isinstance(servers, list):
                self._specs = [s for s in servers
                               if isinstance(s, dict) and s.get('name')
                               and (s.get('command') or s.get('url'))]
        except Exception:
            self._specs = []

    def is_enabled(self):
        return bool([s for s in self._specs if s.get('enabled', True)])

    def connect_all(self):
        """启动时后台连接所有 server（不阻塞主线程）"""
        for spec in self._specs:
            if spec.get('enabled', True) is False:
                continue
            conn = _McpConnection(spec['name'], spec)
            self.conns[spec['name']] = conn
            conn.start()
            self._log('连接 %s…' % spec['name'])

    def status_text(self):
        """连接状态摘要（供 AI/用户查看）"""
        if not self._specs:
            return ''
        lines = []
        for name, conn in self.conns.items():
            if conn.error:
                lines.append(f'{name}: 连接失败({conn.error[:60]})')
            elif conn.session is not None:
                lines.append(f'{name}: 已连接({len(conn.tools)} 个工具)')
            else:
                lines.append(f'{name}: 连接中…')
        return '；'.join(lines)

    def tool_schemas(self):
        """返回可合并进 AI_TOOLS 的工具定义列表（只含已连接成功的）"""
        out = []
        for name, conn in self.conns.items():
            for t in conn.tools:
                key = f'mcp_{name}_{t["name"]}'
                out.append({
                    'type': 'function',
                    'function': {
                        'name': key,
                        'description': f'[MCP:{name}] {t["description"] or t["name"]}',
                        'parameters': t['inputSchema'] or {'type': 'object', 'properties': {}},
                    },
                })
        return out

    # ---------- 管理（设置界面用）----------
    def servers(self):
        """给界面看的完整状态：配置 + 连接 + 工具 + 权限判断"""
        out = []
        by_name = {s['name']: s for s in self._specs}
        names = list(dict.fromkeys(list(by_name) + list(self.conns)))
        for name in names:
            spec = by_name.get(name, {})
            conn = self.conns.get(name)
            tools = []
            for t in (conn.tools if conn else []):
                ro, why = classify_tool(t)
                tools.append({'name': t['name'], 'description': t['description'],
                              'read_only': ro, 'why': why})
            if conn is None:
                state = '已禁用' if spec.get('enabled', True) is False else '未连接'
            elif conn.error:
                state = '连接失败'
            elif conn.session is not None:
                state = '已连接'
            else:
                state = '连接中…'
            out.append({
                'name': name, 'title': spec.get('title') or name,
                'transport': 'HTTP' if spec.get('url') else 'stdio',
                'target': spec.get('url') or (' '.join([spec.get('command', '')] + list(spec.get('args') or []))).strip(),
                'enabled': bool(spec.get('enabled', True)), 'state': state,
                'tool_count': len(tools), 'tools': tools,
                'need_confirm': [t['name'] for t in tools if not t['read_only']],
                'error': (conn.error or '').splitlines()[0] if conn and conn.error else '',
            })
        return out

    def add_server(self, spec, replace=False):
        """新增/覆盖一个 server（写入 config.json 并热连接）"""
        name = str((spec or {}).get('name') or '').strip()
        if not name:
            return False, '要给 server 起个名字'
        if not spec.get('command') and not spec.get('url'):
            return False, '要么给 command（stdio），要么给 url（HTTP）'
        servers = [dict(s) for s in self._specs]
        hit = [s for s in servers if s.get('name') == name]
        if hit and not replace:
            return False, '已经有叫 %s 的 server 了（可先删掉或换名字）' % name
        spec = dict(spec)
        spec['name'] = name
        spec.setdefault('enabled', True)
        servers = [s for s in servers if s.get('name') != name] + [spec]
        if not self._write_cfg(servers):
            return False, '写 config.json 失败'
        self._specs = servers
        self.restart(name)
        import governance as gov
        gov.log_event('install', 'mcp:' + name, 'add_server',
                      'transport=%s target=%s' % ('HTTP' if spec.get('url') else 'stdio',
                                                  spec.get('url') or spec.get('command')))
        if spec.get('url'):
            # 使用者主动添加远程地址 = 同意该域名 → 自动计入出网白名单（留痕）
            host = gov.host_of(spec['url'])
            if host:
                gov.add_net_rule(host)
                gov.log_event('net', 'mcp:' + name, 'allowlist+', host)
        return True, '已添加 %s（%s）' % (name, 'HTTP' if spec.get('url') else 'stdio')

    def remove_server(self, name):
        name = str(name or '')
        servers = [s for s in self._specs if s.get('name') != name]
        if len(servers) == len(self._specs):
            return False, '没有叫 %s 的 server' % name
        conn = self.conns.pop(name, None)
        if conn is not None:
            conn.stop()
        if not self._write_cfg(servers):
            return False, '写 config.json 失败'
        self._specs = servers
        self._log('已删除 %s' % name)
        try:
            import governance as gov
            gov.log_event('uninstall', 'mcp:' + name, 'remove_server', '删除外部服务配置')
        except Exception:
            pass
        return True, '已删除 %s' % name

    def set_enabled(self, name, flag):
        servers = [dict(s) for s in self._specs]
        hit = [s for s in servers if s.get('name') == str(name)]
        if not hit:
            return False, '没有叫 %s 的 server' % name
        hit[0]['enabled'] = bool(flag)
        if not self._write_cfg(servers):
            return False, '写 config.json 失败'
        self._specs = servers
        if flag:
            self.restart(name)
        else:
            conn = self.conns.pop(str(name), None)
            if conn is not None:
                conn.stop()
        return True, '%s 已%s' % (name, '启用并连接' if flag else '断开并禁用')

    def restart(self, name):
        name = str(name)
        old = self.conns.pop(name, None)
        if old is not None:
            old.stop()
        spec = next((s for s in self._specs if s.get('name') == name), None)
        if not spec or spec.get('enabled', True) is False:
            return False, '%s 未启用或不存在' % name
        conn = _McpConnection(name, spec)
        self.conns[name] = conn
        conn.start()
        self._log('重新连接 %s…' % name)
        return True, '正在连接 %s…' % name

    def needs_confirm(self, full_name):
        """这个 MCP 工具调用前要不要先问使用者（写类工具默认要问）"""
        parts = str(full_name).split('_', 2)
        if len(parts) < 3:
            return False, ''
        conn = self.conns.get(parts[1])
        if conn is None:
            return False, ''
        tool = next((t for t in conn.tools if t['name'] == parts[2]), None)
        if tool is None:
            return False, ''
        ro, why = classify_tool(tool)
        if ro:
            return False, why
        if not self.auto_confirm_writes():
            return False, why + '（已关闭写类确认）'
        return True, why

    def auto_confirm_writes(self):
        """默认 True = 写类 MCP 工具调用前先问；False 则不再问"""
        return bool(self._read_cfg().get('mcp_confirm_writes', True))

    def set_auto_confirm_writes(self, flag):
        cfg = self._read_cfg()
        cfg['mcp_confirm_writes'] = bool(flag)
        try:
            tmp = self.config_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            import os
            os.replace(tmp, self.config_path)
            return True, '写类工具调用前%s再问' % ('会' if flag else '不会')
        except Exception as e:
            return False, '写配置失败：%s' % e

    def call_tool(self, full_name, args):
        """按 mcp_<server>_<tool> 解析并转发"""
        parts = full_name.split('_', 2)
        if len(parts) < 3 or parts[0] != 'mcp':
            return f'（MCP 工具名格式错误：{full_name}）'
        server_name, tool_name = parts[1], parts[2]
        conn = self.conns.get(server_name)
        if conn is None:
            return f'（MCP server {server_name} 未配置）'
        return conn.call(tool_name, args)
