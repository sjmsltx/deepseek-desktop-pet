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
        self.last_engine = ''            # v6.77 上一次成功的识别路径：'winrt' / 'sapi'
        self._policy_blocked = False     # 实测到“语音隐私策略未接受”（一次就够，之后一直提醒）

    # Windows 语音隐私策略未接受时的说明（实测 2026-09-19 / 2026-09-20 两次都是这种状态）
    POLICY_HINT = ('Windows 的「语音识别」隐私策略没真正生效（实测注册表里 '
                   'Speech_OneCore\\Settings\\SpeechRecognizer 键不存在）。\n'
                   '请检查：设置 → 隐私和安全性 → 语音 → 「在线语音识别」打开；'
                   '同时确认上面的语音总开关也是开的；改完要重启桌宠（策略在启动时缓存）。\n'
                   '仍不行就用系统自带的 Win+H 语音输入（不依赖这个策略）。')
    POLICY_MARK = 'privacy policy'
    # v6.75：错误消息取不到（HRESULT 本地化缺失）时，实测就是“策略未接受”——把它也归到策略类
    POLICY_MARKS_EXTRA = ('could not be found', 'text associated with this error code',
                          '0x8004', 'not accepted', 'privacy')
    MIC_MARKS = ('denied', 'access', 'microphone', '麦克风', 'denied by')
    LANG_MARKS = ('language', '语言', 'not installed', 'language pack')

    def _classify_error(self, err):
        """把 WinRT/子进程错误分类成可操作的提示（v6.75）

        旧版只认 “privacy policy” 字样；实测本机报的是
        “The text associated with this error code could not be found.”（连本地化文案都取不到）
        → 匹配不上 → 使用者只看到一句无意义的“识别失败”，真因丢掉了。
        """
        low = str(err or '').lower()
        if self.POLICY_MARK in low or any(m in low for m in self.POLICY_MARKS_EXTRA):
            return 'policy', self.POLICY_HINT
        if any(m in low for m in self.MIC_MARKS):
            return 'mic', ('麦克风权限被拒 —— 去 设置 → 隐私和安全性 → 麦克风 → '
                           '允许桌面应用访问后重试')
        if any(m in low for m in self.LANG_MARKS):
            return 'lang', ('系统里没装中文语音识别语言包 —— 设置 → 时间和语言 → 语言和区域 '
                            '→ 中文（简体）→ 语言选项 → 安装「语音」组件')
        return 'other', None

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

    # ---------- 后端分发（v6.77）----------
    #   auto   —— 先 WinRT，失败自动降级 SAPI（默认）
    #   winh   —— 应急：直接触发系统的 Win+H 语音输入（零依赖，质量好，但交互略绕）
    #   whisper—— 本地 whisper.cpp（插口：需配置 exe 与模型路径）
    #   http   —— 联网 ASR API（插口：需配置 URL 与 Key）
    def backend(self):
        return str(getattr(self, 'backend_name', 'auto') or 'auto').strip().lower()

    def listen(self):
        """按当前后端识别一句。返回 (text, confidence, error)"""
        b = self.backend()
        if b == 'winh':
            return self.trigger_win_h()
        if b == 'whisper':
            return self._listen_whisper()
        if b == 'http':
            return self._listen_http()
        return self._listen_local()

    # ---------- C：应急路径 —— 触发系统语音输入（默认 Win+H）----------
    @staticmethod
    def parse_hotkey(spec):
        """把 'win+h' / 'ctrl+shift+space' 这类字符串解析成 (modifiers, vk)

        v6.77：Win+H 在 Windows 10/11 上是**系统固定快捷键**，但旧系统没有、
        也可能被别的软件抢占 → 所以做成可配置，解析不了就回落 win+h。
        支持的修饰键：win / ctrl / alt / shift；主键支持字母、数字、f1-f24、
        以及 space / tab / enter / esc 等常用名。
        """
        MODS = {'win': 0x5B, 'ctrl': 0x11, 'alt': 0x12, 'shift': 0x10}
        NAMED = {'space': 0x20, 'tab': 0x09, 'enter': 0x0D, 'esc': 0x1B, 'escape': 0x1B,
                 'backspace': 0x08, 'delete': 0x2E, 'insert': 0x2D, 'home': 0x24,
                 'end': 0x23, 'pageup': 0x21, 'pagedown': 0x22}
        mods, vk = [0x5B], 0x48          # 默认 Win+H
        s = str(spec or '').strip().lower().replace(' ', '')
        if not s:
            return mods, vk
        parts = [p for p in s.split('+') if p]
        if not parts:
            return mods, vk
        new_mods, main = [], parts[-1]
        for p in parts[:-1]:
            if p in MODS:
                new_mods.append(MODS[p])
            else:
                return mods, vk          # 看不懂就回落默认
        if len(main) == 1 and main.isalnum():
            key = ord(main.upper())
        elif main in NAMED:
            key = NAMED[main]
        elif len(main) >= 2 and main[0] == 'f' and main[1:].isdigit() and 1 <= int(main[1:]) <= 24:
            key = 0x70 + int(main[1:]) - 1
        else:
            return mods, vk
        return (new_mods or [0x5B]), key

    def _send_hotkey(self, mods, key):
        """真正按下组合键（测试里可注入替身，避免副作用）"""
        if getattr(self, '_key_sender', None) is not None:
            return self._key_sender(mods, key)
        import ctypes
        KEYEVENTF_KEYUP = 0x0002
        u = ctypes.windll.user32
        for m in mods:
            u.keybd_event(m, 0, 0, 0)
        u.keybd_event(key, 0, 0, 0)
        u.keybd_event(key, 0, KEYEVENTF_KEYUP, 0)
        for m in reversed(mods):
            u.keybd_event(m, 0, KEYEVENTF_KEYUP, 0)
        return True

    def trigger_win_h(self):
        """模拟按下可配置热键（默认 Win+H），让 Windows 自己的「语音输入」接管

        为什么可用：质量比 SAPI 好得多（走系统模型），且**零依赖**；
        代价是系统会弹它自己的语音条，识别结果由系统写入当前焦点控件（我们拿不到文本）。
        """
        if os.name != 'nt':
            return '', '', '系统语音输入（Win+H）只在 Windows 上可用'
        try:
            spec = str(getattr(self, 'winh_hotkey', 'win+h') or 'win+h')
            mods, key = self.parse_hotkey(spec)
            self._send_hotkey(mods, key)
            self.last_engine = 'winh'
            return '', '', ('已唤起系统语音输入（%s）：请直接说话，识别结果会打进输入框。'
                            '（这条路被系统接管，桌宠拿不到文本；若没反应，可在设置里改热键，'
                            '或改用 whisper / 联网接口后端）' % spec)
        except Exception as e:
            return '', '', '唤起失败：%s' % e

    # ---------- 录音（A / D 两条路都需要）----------
    def record_wav(self, seconds=6, out_path=None):
        """用 winmm MCI 录一段 wav（零依赖）。返回 (wav路径, 错误)"""
        if os.name != 'nt':
            return '', '录音只在 Windows 上实现了'
        import ctypes
        import time as _t
        out_path = out_path or os.path.join(self.base_dir, '_asr_rec.wav')
        try:
            mci = ctypes.windll.winmm.mciSendStringW
            errbuf = ctypes.create_unicode_buffer(512)

            def _call(cmd, b=None):
                b = b if b is not None else ctypes.create_unicode_buffer(256)
                rc = mci(cmd, b, 256, None)
                if rc:
                    msg = ''
                    try:
                        eb = ctypes.create_unicode_buffer(256)
                        ctypes.windll.winmm.mciGetErrorStringW(rc, eb, 256)
                        msg = eb.value
                    except Exception:
                        pass
                    return rc, msg
                return 0, ''

            if os.path.exists(out_path):
                try:
                    os.remove(out_path)
                except Exception:
                    pass
            rc, msg = _call('open new type waveaudio alias asrrec')
            if rc:
                return '', '打不开录音设备（可能被占用）：%s' % (msg or rc)
            # 实测坑：录制前必须给**完整格式串**（含 alignment/bytespersec），
            # 只给 bitspersample/channels/samplespersec 时 record 会失败
            _call('set asrrec time format ms bitspersample 16 channels 1 '
                  'samplespersec 16000 alignment 2 bytespersec 32000')
            rc, msg = _call('record asrrec')
            if rc:
                _call('close asrrec')
                return '', '开始录音失败：%s' % (msg or rc)
            _t.sleep(max(1, int(seconds)))
            _call('stop asrrec')
            b2 = ctypes.create_unicode_buffer(512)
            rc, msg = _call('save asrrec "%s"' % out_path.replace('"', ''), b2)
            _call('close asrrec')
            if rc != 0 or not os.path.exists(out_path):
                return '', '保存录音失败：%s' % (msg or rc)
            self.last_record = out_path
            return out_path, ''
        except Exception as e:
            return '', '录音异常：%s' % e

    # ---------- A：本地 whisper.cpp（插口）----------
    def _listen_whisper(self):
        """调用 whisper.cpp 做识别（需在设置里配好 exe 与模型路径）"""
        exe = str(getattr(self, 'whisper_exe', '') or '').strip()
        model = str(getattr(self, 'whisper_model', '') or '').strip()
        if not exe or not os.path.isfile(exe):
            return '', '', ('还没配置 whisper 可执行文件（设置 → 语音 → 识别后端选 whisper，'
                            '填好 whisper.cpp 的 main.exe 路径）—— 现在可以先用 winh 应急')
        if not model or not os.path.isfile(model):
            return '', '', '还没配置 whisper 模型文件（.bin，如 ggml-small.bin）'
        wav, err = self.record_wav(seconds=int(getattr(self, 'record_seconds', 6) or 6))
        if err:
            return '', '', err
        try:
            cmd = [exe, '-m', model, '-f', wav, '-l', str(self.lang or 'zh')[:2], '-nt']
            proc = subprocess.run(cmd, capture_output=True, timeout=120,
                                  creationflags=_win_flags())
            out = (proc.stdout or b'').decode('utf-8', 'replace')
            text = ' '.join(x.strip() for x in out.splitlines() if x.strip())
            if not text:
                return '', '', 'whisper 没听出内容（或输出为空）'
            self.last_engine = 'whisper'
            return text, '', ''
        except Exception as e:
            return '', '', 'whisper 调用失败：%s' % str(e)[:120]
        finally:
            try:
                os.remove(wav)
            except Exception:
                pass

    # ---------- D：联网 ASR API（插口）----------
    def _listen_http(self):
        """POST 录音到自定义 ASR 接口（需在设置里配好 URL 与 Key）"""
        url = str(getattr(self, 'asr_http_url', '') or '').strip()
        key = str(getattr(self, 'asr_http_key', '') or '').strip()
        if not url:
            return '', '', '还没配置 ASR 接口地址（设置 → 语音 → 识别后端选 http）'
        wav, err = self.record_wav(seconds=int(getattr(self, 'record_seconds', 6) or 6))
        if err:
            return '', '', err
        try:
            import json as _json
            import urllib.request
            with open(wav, 'rb') as f:
                audio = f.read()
            req = urllib.request.Request(
                url, data=_json.dumps({'audio_b64': __import__('base64').b64encode(audio)
                                       .decode('ascii'), 'lang': self.lang}).encode('utf-8'),
                headers={'Content-Type': 'application/json',
                         **({'Authorization': 'Bearer ' + key} if key else {})})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = _json.loads(r.read().decode('utf-8', 'replace'))
            text = str(data.get('text') or '').strip()
            if not text:
                return '', '', '接口没返回 text 字段'
            self.last_engine = 'http'
            return text, str(data.get('confidence') or ''), ''
        except Exception as e:
            return '', '', '接口调用失败：%s' % str(e)[:140]
        finally:
            try:
                os.remove(wav)
            except Exception:
                pass

    # ---------- 本地双路径（WinRT → SAPI）----------
    def _listen_local(self):
        """听一句。返回 (text, confidence, error)

        v6.77：**双路径** —— 先试 WinRT（OneCore，识别质量好）；失败则自动降级到 SAPI
        （System.Speech，走另一套识别栈，**不依赖那个一直卡人的 OneCore 隐私策略**）。
        两条都失败时，把可操作提示优先返回（而不是一句无意义的原始报错）。
        """
        if not os.path.exists(self.ps1):
            return '', '', '缺少 asr_helper.ps1'
        winrt_err, winrt_hint = '', ''
        try:
            rc, out, err = self._run(['-Lang', self.lang], timeout=self.timeout)
            text, conf, error = parse_result(out)
            if not error:
                self.last_engine = 'winrt'
                return text, conf, ''
            kind, hint = self._classify_error(error)
            if kind == 'policy':
                # 系统隐私策略没接受：不是 bug，也不该我们默默改注册表
                self._policy_blocked = True
            winrt_err = error
            winrt_hint = hint or ''
        except subprocess.TimeoutExpired:
            self.cancel()
            return '', '', '超时（没听到声音？）—— 也可以试试系统自带的 Win+H 语音输入'
        except Exception as e:
            winrt_err = '%s: %s' % (type(e).__name__, str(e)[:80])

        # —— 降级：SAPI（System.Speech）——
        try:
            rc, out2, err2 = self._run(['-Lang', self.lang, '-Engine', 'sapi'],
                                       timeout=(self.timeout or 30))
            text2, conf2, error2 = parse_result(out2)
            if not error2:
                self.last_engine = 'sapi'
                self._policy_blocked = False      # SAPI 走通了 → 不再宣称“被策略阻断”
                return text2, conf2, ''
            sapi_hint = self._classify_error(error2)[1] or error2
        except Exception as e:
            sapi_hint = '%s: %s' % (type(e).__name__, str(e)[:80])

        tail = '；已自动尝试备用识别（SAPI）也没成：%s' % str(sapi_hint)[:120]
        return '', '', (winrt_hint or winrt_err or '识别失败') + tail

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
