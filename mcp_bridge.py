# -*- coding: utf-8 -*-
"""
MCP 桥接器（桌宠插件系统 MCP 连接器 v6.20）
================================================
让桌宠 AI 能调用外部 MCP server 的工具——社区几千个 MCP server 直接接入，
无需为每个工具写插件代码（MCP 是跨 harness 的行业标准工具协议，DSH/OpenClaw 同协议）。

配置（config.json）：
    "mcp_servers": [
        {"name": "files", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "E:/ai工作站"]},
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


class _McpConnection(threading.Thread):
    """单个 MCP server 的常驻连接（独立事件循环，线程内 run_forever）"""

    def __init__(self, name, spec):
        super().__init__(daemon=True)
        self.name = name
        self.spec = spec          # {'name', 'command'/'url', ...}
        self.loop = None
        self.session = None
        self.tools = []           # [{name, description, inputSchema}]
        self.error = None

    def run(self):
        try:
            with asyncio.Runner() as runner:  # 3.11+ 推荐：管理独立事件循环
                self.loop = runner.get_loop()
                runner.run(self._serve())     # _serve 内部 Future 挂起 → 常驻
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
                    result = await session.list_tools()
                    self.tools = [
                        {'name': t.name, 'description': t.description or '', 'inputSchema': t.input_schema or {}}
                        for t in result.tools
                    ]
                    await asyncio.Future()  # 永久挂起，保持连接
        except Exception as e:
            import traceback
            self.error = f'{e}\n{traceback.format_exc()}'

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
        self._load_config()

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
        return bool(self._specs)

    def connect_all(self):
        """启动时后台连接所有 server（不阻塞主线程）"""
        for spec in self._specs:
            conn = _McpConnection(spec['name'], spec)
            self.conns[spec['name']] = conn
            conn.start()

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
