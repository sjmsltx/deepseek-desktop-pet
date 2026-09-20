# -*- coding: utf-8 -*-
"""测试用的假 MCP server（FastMCP，走真实 stdio 协议）

工具特意覆盖三类，用来验证权限策略：
  read_note    —— 只读（读类动词）
  write_note   —— 写类（要确认）
  mystery      —— 名字看不出读写（保守：要确认）
"""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP('fake-test-server')


@mcp.tool()
def read_note(name: str) -> str:
    """读取一条便签内容"""
    return '便签[%s]：这是测试内容' % name


@mcp.tool()
def write_note(name: str, text: str) -> str:
    """写入一条便签"""
    return '已写入便签[%s]：%s' % (name, text)


@mcp.tool()
def mystery(item: str) -> str:
    """一个名字看不出读写的工具"""
    return 'mystery 处理了 %s' % item


if __name__ == '__main__':
    # --pid-file PATH：把本进程号写下来（测试用：验证断开后子进程真的结束了）
    import os
    import sys
    if '--pid-file' in sys.argv:
        p = sys.argv[sys.argv.index('--pid-file') + 1]
        with open(p, 'w', encoding='utf-8') as f:
            f.write(str(os.getpid()))
    mcp.run()
