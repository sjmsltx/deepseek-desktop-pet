# -*- coding: utf-8 -*-
"""DSH 适配层（3.0 · P0）—— 全项目唯一允许知道 DeepSeek Harness 细节的地方。

三条铁律（改这个文件时不许违反）：
  1. 只读：绝不写 DSH 的任何文件（settings.yaml / profiles / 日志都不写）；
  2. .credentials.yaml 永不读取（官方口径是"只写"），密钥由用户自己在界面里填；
  3. 任何异常都不得冒泡打断桌宠 —— 一律降级返回，让调用方决定怎么提示。

对外只暴露这几个函数：
  probe()          → 一次拿到状态字典（服务在不在 / 带令牌地址 / 版本 / 配置可否读）
  read_token_url() → 从启动日志里取"带令牌的访问地址"
  read_settings()  → 只读镜像 DSH 的设置（失败返回 {}，绝不抛）
  stop_local_dsh() → 结束属于本机 DSH_ROOT 的服务进程（只在需要重启时用）

依赖：仅标准库（urllib / socket / re / subprocess），不引入第三方包。
"""
from __future__ import annotations

import os
import re
import platform_layer  # P0-3：受控起进程（白名单）
import socket
import subprocess
import sys

# ---- 可配置项（改这里即可，不要散落到别处）----------------------------------
DSH_ROOT = os.environ.get('DSH_ROOT') or r'D:\dsh'
DSH_HOME = os.environ.get('DSH_HOME') or os.path.join(os.path.expanduser('~'), '.dsh')
DEFAULT_PORT = int(os.environ.get('DSH_PORT') or 3080)
HTTP_TIMEOUT = 8

# 2026-10-25：DSH 恒在 127.0.0.1，请求一律绕代理。
#   ⛔ 为什么不 import net_local：本文件声明"仅标准库、可单独复制/单测"，
#     多一个第一方依赖就破坏了这个性质（见模块 docstring）。
#   ⛔ 为什么不写在函数里：会往函数体的 try 块加行，把下面既有的
#     `except Exception as exc` 推离基线行号 ⇒ 静默护栏按行号比对时假报"新增"。
import urllib.request as _urllib_request          # noqa: E402  (仅标准库)

_NO_PROXY_OPENER = _urllib_request.build_opener(_urllib_request.ProxyHandler({}))

# 启动日志的候选位置（启动器写第一个，手工启动可能写临时目录）
# ⚠ 这是**静态兜底候选**；真正优先的是发现到的 root 下的 dsh-web.log
#   （见 _candidate_logs）。改这里不影响"装在别处"的场景。
LOG_CANDIDATES = [
    os.path.join(DSH_ROOT, 'dsh-web.log'),
    os.path.join(os.environ.get('TEMP', ''), 'dsh_web.log'),
]

# ---- 端口 / 安装位置的来源顺序（解决“别人的 DSH 自定义了端口怎么整”）-------
#   1) 用户配置  桌宠目录下 dsh_config.json： {"root": "...", "port": 3081}
#   2) 环境变量  DSH_ROOT / DSH_PORT
#   3) 运行中进程 扫描 node 进程命令行里的 bin.js 路径与 --port（真实发现，不靠猜）
#   4) 日志       从启动日志里出现的 127.0.0.1:<port> 反推
#   5) 默认值    D:\dsh + 3080
USER_CONFIG_NAME = 'dsh_config.json'
USER_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), USER_CONFIG_NAME)
_DISCOVERY_CACHE = {'ts': 0.0, 'data': None}
_DISCOVERY_TTL = 30.0

#: `installed()` 的**结果**缓存（2026-10-31）。
#: ⚠ 为什么单独一层：`installed()` 会走 `resolve_root()` → `discover()` → 扫进程
#:   （实测 0.28~0.30 秒），而它被**右键菜单在 UI 线程**调用
#:   （`contextMenuEvent` → `_build_context_menu()`）⇒ 菜单弹出前要等这么久。
#:   「DSH 装没装/装在哪」是极低频变化的属性，没必要每 30 秒重算。
#: ⛔ 这不是第二套判据：语义仍是 `_has_marker(resolve_root())`，只是缓存结果。
#: TTL 与 `_DISCOVERY_TTL` 分开：port 会随 DSH 重启变化（要灵敏），
#: 而「装没装」几乎不变（可以慢）。
_INSTALLED_CACHE = {'ts': 0.0, 'val': None}
_INSTALLED_TTL = 300.0


def load_user_config() -> dict:
    """读桌宠目录下的 dsh_config.json（用户显式配置，优先级最高）。损坏就当没有。"""
    try:
        if os.path.exists(USER_CONFIG_PATH):
            import json
            with open(USER_CONFIG_PATH, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
    except Exception as exc:
        _log('load_user_config 失败：%r' % exc)
    return {}


def _running_dsh_processes(timeout: int = 15) -> list:
    """扫描正在运行的 DSH web 进程（只读进程信息，不碰它的任何文件）。

    返回 [{'pid': int, 'cmdline': str, 'root': str|None, 'port': int|None}]
    """
    found = []
    if sys.platform != 'win32':
        return found
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | "
          "Where-Object { $_.CommandLine -and $_.CommandLine -like '*bin.js*' -and "
          "$_.CommandLine -like '*web*' } | "
          "ForEach-Object { $_.ProcessId.ToString() + '|' + $_.CommandLine }")
    try:
        out = platform_layer.safe_spawn(['powershell', '-NoProfile', '-Command', ps],
                                     capture_output=True, text=True, timeout=timeout)
    except Exception as exc:
        _log('_running_dsh_processes 失败：%r' % exc)
        return found
    for line in (out.stdout or '').splitlines():
        line = line.strip()
        if '|' not in line:
            continue
        pid_s, _, cmd = line.partition('|')
        try:
            pid = int(pid_s.strip())
        except Exception:
            pid = 0
        port = None
        m = re.search(r'--port\s+(\d+)', cmd)
        if m:
            port = int(m.group(1))
        root = None
        m2 = re.search(r'([A-Za-z]:\\[^"\s]*?)\\node_modules\\@deepseek-ai\\dsh\\', cmd)
        if m2:
            root = m2.group(1)
        found.append({'pid': pid, 'cmdline': cmd, 'root': root, 'port': port})
    return found


# 2026-10-30 修（WX-150 §3.3）：原来只用静态 `LOG_CANDIDATES`，而同一类功能的
# `read_token_url()` 用 `_candidate_logs()`（先发现值、再静态候选）。
# ⇒ DSH 装在别处、没配端口、进程没在跑时，会去默认位置读一个可能不存在的旧日志，
#   拿不到端口 → 回落 3080。改成与 `read_token_url` 同一口径。
# ⚠ 既有测试 `test_dsh_panel.py` 的 autouse fixture 会 patch `resolve_root`，
#   所以 `_candidate_logs()` 的发现路径指向不存在的临时目录，不会被本机真实日志污染。
def _port_from_logs(root: str = None):
    """从启动日志里反推端口（形如 http://127.0.0.1:3081/?token=...）"""
    for path in _candidate_logs(root):
        try:
            if not path or not os.path.exists(path):
                continue
            with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
                for line in fh:
                    m = re.search(r'http://127\.0\.0\.1:(\d+)/', line)
                    if m:
                        return int(m.group(1))
        except Exception:
            continue
    return None


def discover(force: bool = False) -> dict:
    """一次算出 root / port 与各自来源（带 30 秒缓存，避免反复拉进程列表）。"""
    import time
    now = time.time()
    if not force and _DISCOVERY_CACHE['data'] and (now - _DISCOVERY_CACHE['ts']) < _DISCOVERY_TTL:
        return _DISCOVERY_CACHE['data']

    cfg = load_user_config()

    # 2026-10-30 修：原先无条件先扫进程（真起 PowerShell，0.5 秒），
    # 即使用户已经配好 root+port 也照扫一遍。改成只有配置里缺哪项才扫。
    need_scan = not (cfg.get('root') and cfg.get('port'))
    procs = _running_dsh_processes() if need_scan else []
    proc_root = next((p['root'] for p in procs if p['root']), None)
    proc_port = next((p['port'] for p in procs if p['port']), None)

    if cfg.get('root'):
        root, root_src = str(cfg['root']), '用户配置 dsh_config.json'
    elif os.environ.get('DSH_ROOT'):
        root, root_src = os.environ['DSH_ROOT'], '环境变量 DSH_ROOT'
    elif proc_root:
        root, root_src = proc_root, '运行中进程'
    else:
        root, root_src = DSH_ROOT, '默认值 D:\\dsh'

    if cfg.get('port'):
        port, port_src = int(cfg['port']), '用户配置 dsh_config.json'
    elif os.environ.get('DSH_PORT'):
        port, port_src = int(os.environ['DSH_PORT']), '环境变量 DSH_PORT'
    elif proc_port:
        port, port_src = int(proc_port), '运行中进程的 --port'
    elif _port_from_logs(root):
        # ⚠ 必须把已算好的 root 传进去：不传的话它会走 resolve_root() → 递归回本函数。
        # ⚠ 2026-10-31 更正（WX-151 §六 指出）：**这里实际调了两次**
        #   （elif 判一次、取值再一次），之前注释写「合并成一次」是假的。
        #   两次都是读本地日志文件，实测代价约 5 毫秒，不值得为它改流程；
        #   但注释必须说实话，否则下一个人读到这里会算错。
        port, port_src = int(_port_from_logs(root)), '启动日志'
    else:
        port, port_src = DEFAULT_PORT, '默认值 3080'

    data = {
        'root': root, 'root_source': root_src,
        'port': port, 'port_source': port_src,
        'running': len(procs),
        'processes': procs,
    }
    _DISCOVERY_CACHE.update({'ts': now, 'data': data})
    return data


def resolve_root() -> str:
    return discover()['root']


def resolve_port() -> int:
    return discover()['port']


def installed(force: bool = False) -> bool:
    """DSH 是否装在本机（**统一判据**，菜单与设置都用它）。

    2026-10-30 加：原先菜单判 `os.path.exists(DSH_ROOT)` —— 那个是模块导入时定死的
    静态常量，用户把 DSH 装在别处并配好 dsh_config.json 后，菜单仍会显示
    「⚠️ 未检测到 DSH」。这里统一走发现值。

    判据：发现到的 root 存在，**且**里面有 DSH 的标志之一
          （`node_modules/@deepseek-ai/dsh` 或 `start-dsh.ps1` 或 `dsh.cmd`）。
    ⛔ 只判目录存在不够：默认目录可能是个空壳或被别的项目占了。

    ⚠ 口径（2026-10-30 二审后定）：**只有一个定义 —— `_has_marker(resolve_root())`**。

    第一版我写成「按优先级选一个候选，不合格就扫进程兜底」，被 WX-150 §2.1 用实测
    反例否掉了（我自己也复现过）：配置 root 指向坏路径、而 DSH 正在默认目录跑着时，
    `resolve_root()` 返回坏路径但 fallback 扫到进程 ⇒ 本函数返回 True
    ⇒ **菜单说「已检测到」，面板拿坏路径去拉 → 打不开**。
    那正是本函数要消灭的 bug①，用 fallback 等于把它又造了一遍。

    ⛔ 不许在这里再实现一套"够不够装"的算法：
      面板用 `resolve_root()` 找启动器，本函数就必须用同一个 root 判。
      两个函数回答同一个问题，只能一处定义、另一处引用。

    ⚠ 性能取舍（明账）：`resolve_root()` → `discover()` 冷缓存要扫进程（实测 0.53 秒），
      菜单在 UI 线程调用（`contextMenuEvent`）⇒ **缓存过期后第一次右键最多慢 0.5 秒**。
      接受理由：0.5 秒延迟 vs「说检测到但打不开」，后者是骗人。

    ⚠ 2026-10-31 优化：结果带 `_INSTALLED_TTL`（300 秒）缓存 ⇒
      菜单只在「缓存过期后的第一次」付这 0.3 秒，之后都是微秒级（实测 0.10 毫秒）。
      `force=True` **连下游 discover 缓存一起穿透**（2026-10-31 修：原来只穿本层，
      因为 `resolve_root()` 不带 force）。设置页「重测 DSH」走这条。
    """
    import time as _t
    if not force and _INSTALLED_CACHE['val'] is not None:
        if (_t.time() - _INSTALLED_CACHE['ts']) < _INSTALLED_TTL:
            return _INSTALLED_CACHE['val']
    try:
        if force:
            # ⚠ 2026-10-31（WX-152 §四 指出，我实测确认）：
            #   `resolve_root()` **没有 force 参数**，它只能吃 `discover()` 的 30 秒缓存
            #   ⇒ 原来写 `_has_marker(resolve_root())` 时，force 只穿透了「本层缓存」，
            #     下游 discover 缓存照样命中 ⇒ 签名说「强制重算」，实际重算不到底。
            #   现在 force 时直接拿 `discover(force=True)` 的 root，连下游一起穿。
            val = _has_marker(discover(force=True)['root'])
        else:
            val = _has_marker(resolve_root())
    except Exception as exc:
        _silent_log('installed() 判定失败：%r' % exc)
        return False
    _INSTALLED_CACHE.update({'ts': _t.time(), 'val': val})
    return val


def _has_marker(root: str) -> bool:
    """目录里有 DSH 的**真实**标志吗（只做 os.path 检查，不起进程）

    ⚠ 2026-11-02 收紧（WX-166 §三 报出、我核实成立）：
      原来只要 `node_modules/@deepseek-ai/dsh` **存在**、或根目录有 `start-dsh.ps1`，
      就算「已安装」。实测反例（本机真发生过）——某次测试在 TEMP 造的桩：

          node_modules/@deepseek-ai/dsh   1 字节空**文件**
          start-dsh.ps1                   5 字节

      ⇒ `installed()` 返回 True，界面报「✓ 已检测到」，
        而启动器拉不起来，**且一句报警都没有**，用户根本不会去查。
        这比「判成未安装」更坏：未安装至少会被发现。

    ⇒ 现在要求**能真跑起来的证据**，不再把上面那两样单独算数：
      ① npm 包入口 `node_modules/@deepseek-ai/dsh/lib/bin.js`
         （0.1.5-rc.2 与 0.2.1-rc.5 都有它 —— 微信侧 2026-11-01 实测，跨版本稳定）
      ② 根目录的 npm bin 垫片 `dsh.cmd` / `dsh.ps1`（只有真装过才会生成）

    ⛔ 别再往回加「目录存在就算」：桩最容易造的就是空目录。
    """
    try:
        if not root or not os.path.isdir(root):
            return False
        # ① npm 包入口：真装过才有（跨版本稳定的那个文件）
        if os.path.isfile(os.path.join(root, 'node_modules', '@deepseek-ai', 'dsh',
                                       'lib', 'bin.js')):
            return True
        # ② npm bin 垫片：真装过才会生成
        for shim in ('dsh.cmd', 'dsh.ps1'):
            if os.path.isfile(os.path.join(root, shim)):
                return True
        return False
    except Exception as exc:
        # 落痕：路径里有非法字符 / 权限拒绝都可能走到这里，
        # 静默返回 False 会让人以为"没装"，实际是查不了（两回事）
        _silent_log('_has_marker(%r) 检查失败：%r' % (root, exc))
        return False


def installed_detail(serving_timeout: float = None, force: bool = False) -> dict:
    """给界面用的一句话诊断：装没装 / 位置哪来 / 在不在跑。

    serving_timeout 传 None（默认）= **跟随 `is_serving` 的当前默认值**（现为 0.7 秒）；
    传具体值则覆盖。设置页状态行用的就是默认。
    ⚠ 实测：本机连 127.0.0.1 的空闲端口返回**超时**而非 ECONNREFUSED
      ⇒ 每次探活都会吃满整个超时，所以默认值从 2.0 一路降到 0.7。
    ⛔ 这里**不写死秒数**（原写「默认 0.6 秒」已过期两轮）——
      要写就写「当前」，否则调 `is_serving` 默认值时这里又落后一遍。
    """
    d = discover(force=force)
    ok = installed(force=force)
    # ⚠ 2026-11-02：`installed` 收紧成「有真程序入口」。
    #   但「目录在、启动器在、入口不在」与「压根没装」是两件事，
    #   一律报「✗ 未检测到」等于把线索藏起来（WX-166 报的那个桩正是这样）。
    #   ⇒ 单独给个标记，让界面能说清「缺的是哪一样」。
    entry_missing = False
    try:
        r = d.get('root') or ''
        if r and os.path.isdir(r) and not ok:
            entry_missing = any(os.path.isfile(os.path.join(r, f))
                                for f in ('start-dsh.ps1', 'dsh.cmd'))
    except Exception as exc:
        # 落痕：查不了 ≠ 不缺（静默返回 False 会让人以为"入口在"）
        _silent_log('installed_detail 判定 entry_missing 失败：%r' % exc)
        entry_missing = False
    return {
        'installed': ok,
        'entry_missing': entry_missing,
        'root': d['root'],
        'root_source': d['root_source'],
        'port': d['port'],
        'port_source': d['port_source'],
        'running': d['running'],
        'serving': (is_serving(d['port'], timeout=serving_timeout)
                    if serving_timeout is not None else is_serving(d['port'])),
    }


def save_user_config(root: str = None, port: int = None) -> bool:
    """写桌宠目录下的 `dsh_config.json`（用户显式指定 DSH 位置/端口）。

    2026-10-30 加：原先只能手写这个文件或设环境变量，设置界面没有入口。

    - 传 `None` = 该项保持不变；传空串/0 = **删掉该项**（回到自动发现）
    - 写完立刻清发现缓存，调用方无需再手动 refresh
    ⛔ 只写桌宠自己目录下的这个文件，绝不碰 DSH 的任何文件（三铁律第 1 条）。
    """
    try:
        import json
        cfg = load_user_config()
        if root is not None:
            r = str(root).strip()
            if r:
                cfg['root'] = r
            else:
                cfg.pop('root', None)
        if port is not None:
            try:
                p = int(port)
            except (TypeError, ValueError):
                p = 0
            if p > 0:
                cfg['port'] = p
            else:
                cfg.pop('port', None)
        if cfg:
            with open(USER_CONFIG_PATH, 'w', encoding='utf-8') as fh:
                json.dump(cfg, fh, ensure_ascii=False, indent=1)
        elif os.path.exists(USER_CONFIG_PATH):
            # 都清空了 → 删文件，别留个空 {} 让人以为配了东西
            os.remove(USER_CONFIG_PATH)
        # 缓存必须清：否则界面点了保存，30 秒内还显示旧状态
        _DISCOVERY_CACHE.update({'ts': 0.0, 'data': None})
        # installed() 的结果缓存也要清 —— 否则改了位置，右键菜单 5 分钟不更新
        _INSTALLED_CACHE.update({'ts': 0.0, 'val': None})
        return True
    except Exception as exc:
        _silent_log('save_user_config 失败：%r' % exc)
        return False


def _candidate_logs(root: str = None) -> list:
    """日志候选：先看发现到的安装位置，再看静态候选（去重）。

    ⚠ 2026-10-30：加 `root` 参数是为了**打断递归**。
      本函数默认调 `resolve_root()`，而它 → `discover()`，
      而 `discover()` 内部又要调 `_port_from_logs()` 读日志 ——
      若 `_port_from_logs` 也走本函数（root=None），就成了
        discover → _port_from_logs → _candidate_logs → resolve_root → discover
      实测直接卡死（>120 秒不返回，整个 DSH 功能挂死）。
      ⇒ 凡是**在 discover 内部**被调用的，必须把已算好的 root 传进来。
    """
    paths = []
    try:
        r = root if root is not None else resolve_root()
        p = os.path.join(r, 'dsh-web.log')
        if p not in paths:
            paths.append(p)
    except Exception:
        pass
    for p in LOG_CANDIDATES:
        if p and p not in paths:
            paths.append(p)
    return paths


def _log(msg: str) -> None:
    """轻量日志：写项目 logs/ 下（失败就算了，绝不影响主流程）。"""
    try:
        base = os.path.dirname(os.path.abspath(__file__))
        d = os.path.join(base, 'logs')
        os.makedirs(d, exist_ok=True)
        import datetime
        with open(os.path.join(d, 'dsh_adapter.log'), 'a', encoding='utf-8') as fh:
            fh.write('[%s] %s\n' % (datetime.datetime.now().strftime('%H:%M:%S'), msg))
    except Exception:
        pass


# ⭐ 静默护栏的 `_LOG_NAMES` **不认识 `_log`**（只认 `_silent_log` / `log` / `warning` …）。
#   本模块的日志函数偏偏叫 `_log` ⇒ 写了日志也会被判"没落痕"。
#   `dsh_panel.py` 早就踩过这条并留了同样做法：用被识别的名字做同义别名。
#   ⛔ 不改护栏（那是全项目的口径）✓ 只在本模块加别名 ✓（2026-10-30）
_silent_log = _log


def is_serving(port: int = None, timeout: float = 0.7) -> bool:
    """端口是否在监听（不发起 HTTP，最便宜的存活判断）。port=None 时用自动发现的端口。

    ⚠ 2026-10-30：默认超时 **2.0 → 0.7**。原因不是"想快"，是本机实测出来的：
      连一个**空闲**的 127.0.0.1 端口返回的是**超时**而不是 ECONNREFUSED
      （裸 socket：timeout=0.3/1.0/2.0 分别吃掉 0.31/1.00/2.00 秒），
      ⇒ 判"服务没跑"每次都要等满整个超时。
      而连一个**正在监听**的端口是内核几毫秒内完成，0.7 秒已是百倍余量。
    ⛔ 这里等的是内核握手，不是网络往返 —— 别按"网速慢"的思路往上调。
    """
    port = port or resolve_port()
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=timeout):
            return True
    except Exception:
        return False


def read_token_url(port: int = None):
    """从启动日志里取带令牌的访问地址；取不到返回 None。

    日志形如：  dsh web: http://127.0.0.1:3080/?token=xxxxxxxx
    """
    port = port or resolve_port()
    pattern = re.compile(r'http://127\.0\.0\.1:%d/\S*' % port)
    for path in _candidate_logs():
        try:
            if not path or not os.path.exists(path):
                continue
            with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
                lines = [ln for ln in fh if 'token=' in ln]
            for line in reversed(lines):
                m = pattern.search(line)
                if m:
                    return m.group(0).strip()
        except Exception as exc:  # 读日志失败：换下一个候选，绝不抛
            _log('read_token_url 读取 %s 失败：%r' % (path, exc))
    return None


def http_status(url: str, timeout: int = HTTP_TIMEOUT):
    """取 HTTP 状态码与长度。

    实现说明（2026-09-21 实测）：
      · 用 Python 的 urllib 直接请求 127.0.0.1:3080 会被 DSH 的“浏览器信任栅栏”判 401，
        而同一个地址用 PowerShell 的 Invoke-WebRequest、或直接交给浏览器打开，都能拿到 200。
        这是客户栈差异，不是令牌/地址错误。
      · 所以这里优先用 PowerShell 走已验证可用的那条路；失败再退回 urllib 做诊断。
    返回 (status, bytes, err)；err 为空字符串表示成功。
    """
    code, size, err = _http_status_ps(url, timeout)
    if code and code == 200:
        return code, size, ''
    # 退回 urllib（仅用于诊断/在非 Windows 环境）
    py_code, py_size, py_err = _http_status_urllib(url, timeout)
    if py_code == 200:
        return py_code, py_size, ''
    return (code or py_code), (size or py_size), (err or py_err)


def _http_status_ps(url: str, timeout: int = HTTP_TIMEOUT):
    if sys.platform != 'win32':
        return None, 0, 'non-windows'
    script = (
        "try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec %d '%s'; "
        "Write-Output ('OK ' + $r.StatusCode + ' ' + $r.RawContentLength) } "
        "catch { Write-Output ('ERR ' + $_.Exception.Message) }" % (timeout, url.replace("'", "''"))
    )
    try:
        out = platform_layer.safe_spawn(['powershell', '-NoProfile', '-Command', script],
                                     capture_output=True, text=True, timeout=timeout + 15)
        text = (out.stdout or '').strip()
        if text.startswith('OK '):
            parts = text.split()
            return int(parts[1]), int(parts[2]) if len(parts) > 2 else 0, ''
        return None, 0, text[:200] or 'powershell 探测失败'
    except Exception as exc:
        return None, 0, repr(exc)


def _http_status_urllib(url: str, timeout: int = HTTP_TIMEOUT):
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={'User-Agent': 'DeepSeekPet/3.0 (dsh_adapter)'})
        with _NO_PROXY_OPENER.open(req, timeout=timeout) as resp:
            return resp.status, len(resp.read()), ''
    except Exception as exc:
        return None, 0, repr(exc)


def read_version(timeout: int = 20):
    """取 DSH 版本号（跑 dsh --version）；取不到返回 None。用自动发现到的安装位置。"""
    root = resolve_root()
    cands = [os.path.join(root, 'dsh.cmd'), os.path.join(root, 'dsh.ps1')]
    for exe in cands:
        if not os.path.exists(exe):
            continue
        try:
            out = platform_layer.safe_spawn([exe, '--version'], capture_output=True, text=True,
                                        timeout=timeout, cwd=root, shell=False)
            text = (out.stdout or '') + (out.stderr or '')
            m = re.search(r'(\d+\.\d+\.\d+(?:[-.][A-Za-z0-9.]+)?)', text)
            if m:
                return m.group(1)
        except Exception as exc:
            _log('read_version 失败：%r' % exc)
    return None


def read_settings():
    """只读镜像 DSH 的设置文件。

    成功返回 dict；文件不存在 / 解析不了 / 没有 YAML 库 → 返回 {}
    （调用方据此降级：不显示模型信息，改为"打开它的设置页"）。
    """
    home = load_user_config().get('home') or DSH_HOME
    path = os.path.join(home, 'settings.yaml')
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
            text = fh.read()
    except Exception as exc:
        _log('read_settings 读取失败：%r' % exc)
        return {}
    try:
        import yaml  # 有就用，没有就降级
        data = yaml.safe_load(text) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        pass
    # 极简降级解析：只认 "键: 值" 的顶层行，够用来判断"有没有配过模型"
    out = {}
    for line in text.splitlines():
        if not line or line.startswith((' ', '\t', '#')):
            continue
        if ':' in line:
            k, _, v = line.partition(':')
            out[k.strip()] = v.strip()
    return out


def probe(port: int = None) -> dict:
    """一次拿到全部状态，供桌宠决定"显示什么 / 隐藏什么"。port=None 时自动发现。"""
    disc = discover()
    port = port or disc['port']
    info = {
        'serving': False,
        'url': None,
        'status': None,
        'bytes': 0,
        'version': None,
        'settings_ok': False,
        'settings_keys': [],
        'port': port,
        'port_source': disc['port_source'],
        'root': disc['root'],
        'root_source': disc['root_source'],
        'reason': '',
    }
    info['serving'] = is_serving(port)
    if not info['serving']:
        info['reason'] = '服务未运行（端口 %d 没有监听；端口来源：%s）' % (port, disc['port_source'])
        info['version'] = read_version()
        return info

    url = read_token_url(port)
    info['url'] = url
    if not url:
        info['reason'] = '服务在跑，但读不到带令牌的地址（启动日志格式可能变了）'
        info['version'] = read_version()
        return info

    status, size, err = http_status(url)
    info['status'] = status
    info['bytes'] = size
    if status != 200:
        info['reason'] = '带令牌访问失败：%s' % (err or ('HTTP %s' % status))
    settings = read_settings()
    info['settings_keys'] = sorted(settings.keys())[:20]
    info['settings_ok'] = bool(settings)
    info['version'] = read_version()
    return info


def stop_local_dsh() -> int:
    """结束"属于本机 DSH_ROOT 的" web 服务进程（不碰别人的 node）。返回结束的进程数。"""
    killed = 0
    if sys.platform != 'win32':
        return 0
    # 2026-10-30 修：原来用静态 DSH_ROOT（模块导入时定死）——
    # 用户把 DSH 装在别处并配好 dsh_config.json 后，这里仍然只去停 D:\dsh 的进程。
    try:
        _r = resolve_root()
        # ⛔ 空 root 不许拼进 PowerShell（会变成 -like "**" 匹配一切）
        if not _r:
            _log('stop_local_dsh: 解析不到 DSH 位置，拒绝执行（防误杀）')
            return 0
        ps = ('Get-CimInstance Win32_Process -Filter "Name=\'node.exe\'" | '
              'Where-Object { $_.CommandLine -and $_.CommandLine -like "*%s*" -and '
              '$_.CommandLine -like \'*bin.js*\' -and $_.CommandLine -like \'*web*\' } | '
              'ForEach-Object { Stop-Process -Id $_.ProcessId -Force; 1 }' % _r)
        out = platform_layer.safe_spawn(['powershell', '-NoProfile', '-Command', ps],
                                     capture_output=True, text=True, timeout=25)
        killed = len([l for l in (out.stdout or '').splitlines() if l.strip() == '1'])
    except Exception as exc:
        _silent_log('stop_local_dsh 失败：%r' % exc)
    return killed


if __name__ == '__main__':  # 手工自检：python dsh_adapter.py
    import json
    print(json.dumps(probe(), ensure_ascii=False, indent=2))
