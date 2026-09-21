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
import socket
import subprocess
import sys

# ---- 可配置项（改这里即可，不要散落到别处）----------------------------------
DSH_ROOT = os.environ.get('DSH_ROOT') or r'D:\dsh'
DSH_HOME = os.environ.get('DSH_HOME') or os.path.join(os.path.expanduser('~'), '.dsh')
DEFAULT_PORT = int(os.environ.get('DSH_PORT') or 3080)
HTTP_TIMEOUT = 8

# 启动日志的候选位置（启动器写第一个，手工启动可能写临时目录）
LOG_CANDIDATES = [
    os.path.join(DSH_ROOT, 'dsh-web.log'),
    os.path.join(os.environ.get('TEMP', ''), 'dsh_web.log'),
]


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


def is_serving(port: int = DEFAULT_PORT, timeout: float = 2.0) -> bool:
    """端口是否在监听（不发起 HTTP，最便宜的存活判断）。"""
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=timeout):
            return True
    except Exception:
        return False


def read_token_url(port: int = DEFAULT_PORT):
    """从启动日志里取带令牌的访问地址；取不到返回 None。

    日志形如：  dsh web: http://127.0.0.1:3080/?token=xxxxxxxx
    """
    pattern = re.compile(r'http://127\.0\.0\.1:%d/\S*' % port)
    for path in LOG_CANDIDATES:
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
        out = subprocess.run(['powershell', '-NoProfile', '-Command', script],
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
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, len(resp.read()), ''
    except Exception as exc:
        return None, 0, repr(exc)


def read_version(timeout: int = 20):
    """取 DSH 版本号（跑 dsh --version）；取不到返回 None。"""
    cands = [os.path.join(DSH_ROOT, 'dsh.cmd'), os.path.join(DSH_ROOT, 'dsh.ps1')]
    for exe in cands:
        if not os.path.exists(exe):
            continue
        try:
            out = subprocess.run([exe, '--version'], capture_output=True, text=True,
                                 timeout=timeout, cwd=DSH_ROOT, shell=False)
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
    path = os.path.join(DSH_HOME, 'settings.yaml')
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


def probe(port: int = DEFAULT_PORT) -> dict:
    """一次拿到全部状态，供桌宠决定"显示什么 / 隐藏什么"。"""
    info = {
        'serving': False,
        'url': None,
        'status': None,
        'bytes': 0,
        'version': None,
        'settings_ok': False,
        'settings_keys': [],
        'port': port,
        'root': DSH_ROOT,
        'reason': '',
    }
    info['serving'] = is_serving(port)
    if not info['serving']:
        info['reason'] = '服务未运行（端口 %d 没有监听）' % port
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
    try:
        ps = ('Get-CimInstance Win32_Process -Filter "Name=\'node.exe\'" | '
              'Where-Object { $_.CommandLine -and $_.CommandLine -like "*%s*" -and '
              '$_.CommandLine -like \'*bin.js*\' -and $_.CommandLine -like \'*web*\' } | '
              'ForEach-Object { Stop-Process -Id $_.ProcessId -Force; 1 }' % DSH_ROOT)
        out = subprocess.run(['powershell', '-NoProfile', '-Command', ps],
                             capture_output=True, text=True, timeout=25)
        killed = len([l for l in (out.stdout or '').splitlines() if l.strip() == '1'])
    except Exception as exc:
        _log('stop_local_dsh 失败：%r' % exc)
    return killed


if __name__ == '__main__':  # 手工自检：python dsh_adapter.py
    import json
    print(json.dumps(probe(), ensure_ascii=False, indent=2))
