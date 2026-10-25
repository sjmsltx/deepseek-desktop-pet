#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""commit_safe.py —— 提交时强制使用 sjmsltx 身份，并当场校验

## 为什么要有它（2026-10-25）

本轮查清一件事，比原以为的严重：

    GIT_AUTHOR_NAME=zwork / GIT_COMMITTER_NAME=zwork

在这台机器上 **User 级和 Machine 级都是空的，只在进程级有值** ——
是**执行环境注入**的，不是 Owner 配的，也不是谁手写的。

=> 这就是「同一类错犯了第二次」的根源：
   任何一方的会话里，只要不显式清这四个变量，`git commit` 就记成
   `zwork <zwork@local>`。而且**优先级高于 `git config user.name`** ——
   所以"配了全局身份"根本挡不住它。

2026-10-25 那个 98756bb 就是这么来的：作者 zwork，还已经推到 GitHub，
最后靠 `rebase --exec 'git commit --amend --reset-author'` + force push 才修回来。

## 它做什么

1 从**当前进程**删掉 4 个 GIT_* 变量（不改系统环境，只影响这一次 commit）
2 显式指定 -c user.name / -c user.email
3 提交后**立刻回读** %an <%ae> / %cn <%ce>，任何一项不对就报错退出
   ⛔ 不靠"我设了所以一定对"—— 那正是本轮反复栽的"看起来在判断"

## 用法

    python tools\\commit_safe.py -m "提交信息"
    python tools\\commit_safe.py -F 消息文件.txt
    python tools\\commit_safe.py -m "..." --amend        # 改最近一个

退出码：0 = 提交成功且身份正确 / 1 = git 失败 / 2 = 身份校验不过
"""
import os
import subprocess
import sys

NAME = 'sjmsltx'
EMAIL = 'sjmsltx@users.noreply.github.com'
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GIT = os.environ.get('GIT_EXE', r'D:\Git\cmd\git.exe')


def clean_env():
    """去掉执行环境注入的 GIT_AUTHOR_* / GIT_COMMITTER_*。

    ⛔ 只影响本进程派生的子进程，不写系统环境、不改注册表。
    """
    return {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}


def git(*args):
    r = subprocess.run([GIT] + list(args), cwd=REPO, capture_output=True,
                       env=clean_env())
    return (r.returncode,
            r.stdout.decode('utf-8', 'replace').strip(),
            r.stderr.decode('utf-8', 'replace').strip())


def main(argv):
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__)
        return 0

    amend = '--amend' in argv
    rest = [a for a in argv if a != '--amend']

    # ⛔ 用 -F 传消息时，--amend 与 -F 可以共存；顺序无要求，但 --amend 放在 commit 后
    cmd = [GIT,
           '-c', 'user.name=' + NAME,
           '-c', 'user.email=' + EMAIL,
           'commit']
    if amend:
        cmd.append('--amend')
    cmd += rest

    injected = {k: v for k, v in os.environ.items()
                if k.startswith(('GIT_AUTHOR_', 'GIT_COMMITTER_'))}
    if injected:
        print('[commit_safe] 执行环境注入了身份变量（本工具已覆盖，仅本次生效）：')
        for k, v in sorted(injected.items()):
            print('    %-22s = %s' % (k, v))

    r = subprocess.run(cmd, cwd=REPO, capture_output=True, env=clean_env())
    out = r.stdout.decode('utf-8', 'replace').strip()
    err = r.stderr.decode('utf-8', 'replace').strip()
    if out:
        print(out)
    if r.returncode != 0:
        print('[commit_safe] ✗ git 提交失败：')
        print(err[:1200])
        return 1

    # 提交后当场回读 —— 不假设"我设了就一定对"
    _, a, _ = git('log', '-1', '--pretty=%an <%ae>')
    _, c, _ = git('log', '-1', '--pretty=%cn <%ce>')
    _, sha, _ = git('log', '-1', '--pretty=%h')
    want = '%s <%s>' % (NAME, EMAIL)
    ok = (a == want) and (c == want)
    print('[commit_safe] %s  author=%s  committer=%s  %s'
          % (sha, a, c, '✓' if ok else '✗ 身份不对'))
    if not ok:
        print('[commit_safe] ⛔ 身份校验不过，用这条修：')
        print('    git -c user.name=%s -c user.email=%s commit --amend --no-edit --reset-author'
              % (NAME, EMAIL))
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
