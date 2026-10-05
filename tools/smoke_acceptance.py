# -*- coding: utf-8 -*-
"""tools/smoke_acceptance.py —— ⭐ 阶段 D-3「端到端冒烟」（可反复跑 ✓）

⭐ 冒烟口径（路线图 D-3 ✓）：**起协作台 → 发起一轮 → 中途打断 → 恢复 → 停服务**
   ⇒ ⭐ **退出后自动复核三件事**：⭐ ① 端口无监听 ✓ ② 无残留进程 ✓ ③ 无脏文件 ✓

⭐ 设计纪律：
   · ⛔ **不新增端点** ✗（只用既有：`health`／`snapshot`／`interrupt`／`step`／`resume`／`queue` ✓）
   · ⭐ **端口被占 ⇒ 直接明示并退出** ✗（⛔ 不抢端口 ✗ 不杀别人进程 ✗）
   · ⭐ **无论成败都收尾**（`finally` 里杀子进程 ✓）
   · ⭐ 每步打印**原始观测**（⛔ 不打印"应该没问题" ✗）

用法（PowerShell ✓）:
    python tools\\smoke_acceptance.py                 # 默认 8899 ＋ demo-provider ✓
    python tools\\smoke_acceptance.py --port 8898 --base .
退出码：0 = 全绿 ✓ ｜ 1 = 有失败 ✗ ｜ 2 = 前置不满足（端口被占等 ✓）
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STEPS = []


def step(name, ok, detail=''):
    STEPS.append((name, bool(ok), detail))
    print('  %s %-34s %s' % ('✓' if ok else '✗', name, detail))


def port_in_use(port):
    with socket.socket() as s:
        s.settimeout(0.6)
        return s.connect_ex(('127.0.0.1', port)) == 0


def get(port, path, timeout=8):
    with urllib.request.urlopen('http://127.0.0.1:%d%s' % (port, path), timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def post(port, path, payload, timeout=15):
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (port, path),
                                 data=json.dumps(payload).encode('utf-8'),
                                 headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def git(base, *args):
    try:
        p = subprocess.run(['git'] + list(args), cwd=base, capture_output=True, text=True, timeout=30)
        return p.stdout.strip()
    except Exception as e:
        return 'ERR %r' % e


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default=REPO)
    ap.add_argument('--port', type=int, default=8899)
    ap.add_argument('--no-demo', action='store_true', help='不起 demo-provider（用真实 provider ✓）')
    a = ap.parse_args()
    base, port = os.path.abspath(a.base), a.port

    print('=== 阶段 D-3 端到端冒烟 | base=%s port=%d ===' % (base, port))

    # 前置
    if port_in_use(port):
        print('✗ 端口 %d 已被占用 ⇒ ⛔ 不抢端口 ✗（先确认是不是你自己起的服务 ✓）' % port)
        return 2
    step('前置：端口空闲', True, 'port=%d' % port)

    dirty_before = git(base, 'status', '--porcelain')
    step('前置：记录工作区状态', True, '%d 行' % len(dirty_before.splitlines()))

    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    env.pop('HTTP_PROXY', None), env.pop('HTTPS_PROXY', None), env.pop('ALL_PROXY', None)
    args = [sys.executable, os.path.join(base, 'collab', 'relay_server.py'),
            # ⭐ 冒烟日志写到**临时目录** ✓（⛔ 不往仓库/通道里留垃圾 ✗）
            '--log', os.path.join(tempfile.gettempdir(), 'smoke_acceptance_log.jsonl'),
            '--port', str(port),
            '--enable-actions', '--issue-title', '冒烟-阶段D']
    if not a.no_demo:
        args.append('--demo-provider')
    proc = subprocess.Popen(args, cwd=base, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        # 起服务
        up = False
        for i in range(40):
            time.sleep(1)
            try:
                j = get(port, '/api/health', timeout=2)
                if isinstance(j, dict):
                    up = True
                    step('起协作台：/api/health 200', True, 'seq=%s actions=%s' % (j.get('seq'), j.get('actions')))
                    break
            except Exception:
                pass
        step('起协作台：服务就绪', up, '%d 秒内' % (i + 1))
        if not up:
            return 1

        # 发起一轮
        post(port, '/api/interrupt', {'body': '（冒烟）请回一句', 'mode': 'queue'})
        s = post(port, '/api/step', {})
        step('发起一轮（queue ＋ step）', bool(s.get('turn_no')), 'turn_no=%s' % s.get('turn_no'))

        # 中途打断
        post(port, '/api/interrupt', {'body': '（冒烟）打断', 'mode': 'interrupt'})
        time.sleep(0.8)
        q = get(port, '/api/queue')
        step('中途打断 ⇒ interrupted=True', q.get('interrupted') is True,
             'interrupted=%s queued=%s' % (q.get('interrupted'), q.get('queued_count')))

        # 恢复
        try:
            post(port, '/api/resume', {})
            time.sleep(0.8)
            q2 = get(port, '/api/queue')
            step('恢复 ⇒ interrupted=False', q2.get('interrupted') is False,
                 'interrupted=%s' % q2.get('interrupted'))
        except urllib.error.HTTPError as e:
            step('恢复 ⇒ interrupted=False', False, 'HTTP %s（端点未开？）' % e.code)

        # 停服务（模拟"退出"）
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        time.sleep(2)

        # ⭐ 退出后三查
        step('退出后：端口无监听', not port_in_use(port), 'port=%d' % port)
        leftovers = []
        try:
            out = subprocess.run(['powershell', '-NoProfile', '-Command',
                                  "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | ForEach-Object { $_.CommandLine }"],
                                 capture_output=True, text=True, timeout=25).stdout
            leftovers = [l for l in out.splitlines() if 'relay_server.py' in l]
        except Exception as e:
            leftovers = ['检查异常 %r' % e]
        step('退出后：无残留 relay_server 进程', not leftovers, '残留 %d 个' % len(leftovers))

        dirty_after = git(base, 'status', '--porcelain')
        new_lines = [l for l in dirty_after.splitlines() if l not in dirty_before.splitlines()]
        step('退出后：无脏文件（新增改动/未跟踪）', not new_lines,
             '新增 %d 行%s' % (len(new_lines), ('：' + new_lines[0][:80]) if new_lines else ''))
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    bad = [s for s in STEPS if not s[1]]
    print('\n=== 结论：%d/%d 通过 %s ===' % (len(STEPS) - len(bad), len(STEPS), '✓ 全绿' if not bad else '✗ 有失败'))
    for n, ok, d in bad:
        print('   ✗ %s %s' % (n, d))
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
