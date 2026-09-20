# -*- coding: utf-8 -*-
"""asr.py — 离线语音输入（v6.66）
=================================

做什么：调用 `asr_helper.ps1`（WinRT SpeechRecognizer）做**单句中文识别**，
把结果交给宿主填进输入框（**不自动发送**）。

为什么这么做（对照使用者的两条思路）
- 系统自带语音输入（Win+H）能用，但要用户自己按快捷键、还得先把光标放进输入框，
  且识别结果由系统浮窗控制、程序拿不到；所以**自己识别**更可控。
- Windows 11 的语音输入依赖 `Language.Speech~~~<语言>` 语言包（本机 zh-CN 已装 ✓）；
  本模块先做**能力检测**，没装语言包/没麦克风时给出明确原因，而不是静默失败。

零依赖、离线：只用系统 WinRT + 子进程；`CREATE_NO_WINDOW` 启动，不闪控制台。
不依赖 PySide6（可 headless 测试）。
"""
import os
import subprocess
import threading

from pet_log import get_logger

_log = get_logger('asr')

DEFAULT_LANG = 'zh-CN'
DEFAULT_TIMEOUT = 25


def _win_flags():
    try:
        return getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
    except Exception:
        return 0


def parse_result(stdout):
    """解析 asr_helper.ps1 的输出。返回 (text, confidence, error)

    v6.66：ERR 之后可能还有细节行（PS 异常消息本身带换行）→ 要把后续行一并当成错误说明，
    否则“privacy policy”这类关键信息会落在第二行、关键字就匹配不到。
    """
    lines = [ln.strip() for ln in str(stdout or '').splitlines() if ln.strip()]
    for i, line in enumerate(lines):
        if line.startswith('OK|'):
            parts = line.split('|', 2)
            conf = parts[1].strip() if len(parts) > 1 else ''
            text = parts[2].strip() if len(parts) > 2 else ''
            return text, conf, ''
        if line.startswith('ERR|'):
            msg = ' '.join([line.split('|', 1)[1].strip()] + lines[i + 1:])
            return '', '', msg or '识别失败'
    return '', '', '没有解析到识别结果'


class AsrEngine:
    """语音输入引擎：能力检测 + 单句识别 + 可取消"""

    def __init__(self, base_dir, lang=DEFAULT_LANG, timeout=DEFAULT_TIMEOUT, runner=None):
        self.base_dir = base_dir
        self.ps1 = os.path.join(base_dir, 'asr_helper.ps1')
        self.lang = lang or DEFAULT_LANG
        self.timeout = int(timeout)
        self._runner = runner            # 测试注入：(args, timeout) -> (rc, stdout, stderr)
        self._proc = None
        self._lock = threading.Lock()
        self._avail = None               # 能力检测结果缓存
        self._policy_blocked = False     # 实测到“语音隐私策略未接受”（一次就够，之后一直提醒）

    # Windows 语音隐私策略未接受时的说明（实测 2026-09-19：本机就是这种状态）
    POLICY_HINT = ('Windows 的「在线语音识别」隐私策略未开启 —— '
                   '去 设置 → 隐私和安全性 → 语音 → 打开「在线语音识别」后即可离线识别；'
                   '暂时也可以用系统自带的 Win+H 语音输入')
    POLICY_MARK = 'privacy policy'

    # ---------- 能力检测 ----------
    def available(self, refresh=False):
        """本机能不能做语音识别。返回 (bool, 说明)"""
        with self._lock:
            if self._policy_blocked:
                return (False, self.POLICY_HINT)
            if self._avail is not None and not refresh:
                return self._avail
        if not os.path.exists(self.ps1):
            res = (False, '缺少 asr_helper.ps1')
            with self._lock:
                self._avail = res
            return res
        rc, out, err = self._run(['-Check'], timeout=30)
        text, conf, error = parse_result(out)
        if error:
            res = (False, error)
        else:
            res = (True, '识别语言 %s（可用：%s）' % (conf or '?', text or '?'))
        with self._lock:
            self._avail = res
        return res

    # ---------- 识别 ----------
    def listen(self):
        """听一句。返回 (text, confidence, error)；已取消/超时都会在 error 里说明"""
        if not os.path.exists(self.ps1):
            return '', '', '缺少 asr_helper.ps1'
        try:
            rc, out, err = self._run(['-Lang', self.lang], timeout=self.timeout)
        except subprocess.TimeoutExpired:
            self.cancel()
            return '', '', '超时（没听到声音？）—— 也可以试试系统自带的 Win+H 语音输入'
        except Exception as e:
            return '', '', '%s: %s' % (type(e).__name__, str(e)[:80])
        text, conf, error = parse_result(out)
        if error:
            low = error.lower()
            if self.POLICY_MARK in low or 'privacy' in low:
                # 这是系统隐私策略，不是 bug，也不该我们默默改注册表 → 说明白让用户去开
                self._policy_blocked = True
                return '', '', self.POLICY_HINT
            if 'denied' in low or 'access' in low or '隐私' in error:
                error = '麦克风权限被拒（Windows 设置 → 隐私和安全性 → 麦克风 → 允许桌面应用访问）'
            return '', '', error
        return text, conf, ''

    def cancel(self):
        """取消当前这轮识别（kill 子进程）"""
        with self._lock:
            p = self._proc
        if p is not None:
            try:
                p.kill()
            except Exception:
                pass
            return True
        return False

    def clip(self):
        return self.ps1

    # ---------- 底层 ----------
    def _run(self, extra_args, timeout):
        args = ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', self.ps1] + list(extra_args)
        if self._runner is not None:
            return self._runner(args, timeout)
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                creationflags=_win_flags())
        with self._lock:
            self._proc = proc
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()          # 超时必须先把子进程收掉，否则会残留占用麦克风
                proc.communicate(timeout=3)
            except Exception:
                pass
            raise
        finally:
            with self._lock:
                self._proc = None
        return proc.returncode, (out or b'').decode('utf-8', 'ignore'), (err or b'').decode('utf-8', 'ignore')
