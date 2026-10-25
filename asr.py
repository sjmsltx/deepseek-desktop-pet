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


def _decode_out(raw):
    """解子进程输出（GBK 兜底）

    为什么不能只用 utf-8：调用方用 CREATE_NO_WINDOW 启动 ps1（没有控制台），
    PowerShell 5.1 此时按系统 ANSI 代码页输出 —— 本机是 GBK。
    实测 2026-10-21：固定按 utf-8 解码，中文全成乱码，连带两个后果：
      ① _classify_error 匹配不到关键字，真因被吞成「识别失败」
      ② 识别成功的文本填进输入框也是乱码
    ps1 已强制 UTF-8 输出；这里再留一层兜底，防旧脚本或环境差异。
    """
    if isinstance(raw, str):
        return raw
    b = raw or b''
    try:
        return b.decode('utf-8')
    except UnicodeDecodeError:
        return b.decode('gbk', 'replace')


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
        if line.startswith('REJECTED|'):
            # 「听到了但没听准」与「没听到」要分开，提示语不同
            return '', 'Rejected', line.split('|', 1)[1].strip() or '听到了但没听准'
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
        self._sapi_cache = None          # SAPI 已装识别器语言（None=还没探测过）
        self._last_winrt_rejected = False  # 上一轮 WinRT 是否"听到了但不敢认"
        #: 低于这个置信度就把"可能不准"明确告诉使用者 —— 直接回应"时灵时不灵"
        self.LOW_CONF = 0.35

    # Windows 语音隐私策略未接受时的说明（实测 2026-09-19 / 2026-09-20 两次都是这种状态）
    POLICY_HINT = ('Windows 的「语音识别」隐私策略没真正生效（实测注册表里 '
                   'Speech_OneCore\\Settings\\SpeechRecognizer 键不存在）。\n'
                   '请检查：设置 → 隐私和安全性 → 语音 → 「在线语音识别」打开；'
                   '同时确认上面的语音总开关也是开的；改完要重启桌宠（策略在启动时缓存）。\n'
                   '仍不行就用系统自带的 Win+H 语音输入（不依赖这个策略）。')
    POLICY_MARK = 'privacy policy'
    # v6.75：错误消息取不到（HRESULT 本地化缺失）时，实测就是“策略未接受”——把它也归到策略类
    POLICY_MARKS_EXTRA = ('could not be found', 'text associated with this error code',
                          'not accepted', 'privacy',
                          # 真正表示「策略未接受」的 HRESULT（SPERR_SPEECH_PRIVACY_POLICY_NOT_ACCEPTED）
                          '0x80045509',
                          # 中文系统上 HRESULT 文案是本地化的
                          '隐私策略', '隐私声明')
    # ⛔ 2026-10-25 从上面撤掉了三条：'could not be found' / 'text associated with this
    #   error code' / '无法找到与此错误代码'。
    #   它们命中的是本机那个「无法找到与此错误代码关联的文本」，而该错误的真实来源是
    #   InvalidOperationException **0x80131509** = 「没编译识别约束就调识别」，
    #   与隐私策略毫无关系。旧版靠这三条把它归成 policy，于是：
    #     ① 永久封杀 WinRT（_policy_blocked=True）
    #     ② 每次点 🎤 都白跑一轮必然失败的识别
    #     ③ 提示把使用者引向"去开隐私开关"—— 而那个开关本来就开着
    #        （实测 HKCU\...\Speech_OneCore\Settings\OnlineSpeechPrivacy\HasAccepted = 1）
    #   教训：按文案猜错误类型会猜错，要看 HRESULT。
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
        # 0x80131509 / InvalidOperationException = 识别器状态不对（典型是没编译约束）。
        # 这是程序自身问题，不该让使用者跑去改系统设置。
        if '0x80131509' in low or 'invalidoperationexception' in low:
            return 'engine', ('识别器状态异常（多半是约束没编译）。已记录；'
                              '若持续出现请把这条提示报给作者')
        # 本地化文案缺失（只有「无法找到与此错误代码关联的文本」、没有错误码）：
        # 这类问题使用者无从下手，也绝不是隐私开关的事 —— 归 engine 并说清是程序侧
        if '无法找到与此错误代码' in low or '找不到与此错误代码' in low:
            return 'engine', ('识别器返回了一个没有本地化文案的错误（程序侧问题，'
                              '与麦克风和隐私设置无关）。已记录；若持续出现请报给作者')
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
            blocked = self._policy_blocked
            if not blocked and self._avail is not None and not refresh:
                return self._avail
        if blocked:
            # WinRT 被 OneCore 语音隐私策略挡住 ≠ 整个语音输入不能用：
            # System.Speech（SAPI）是另一套识别栈，不受那条策略约束。
            # 实测本机 SAPI 装了 zh-CN 识别器，且能把合成的中文语音原样识别出来（2026-10-21）。
            # 旧版在这里直接 return False —— 于是 _toggle_listen 在 listen() 之前就退出，
            # SAPI 永远得不到尝试机会；而只有 SAPI 成功才能复位这个标志 ⇒ 自己把路锁死。
            cults = self._sapi_cultures()
            if cults:
                return (True, '备用识别可用（System.Speech：%s）；WinRT 被隐私策略挡住，将直接走备用'
                        % ','.join(cults[:3]))
            return (False, self.POLICY_HINT)
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

    def _sapi_cultures(self):
        """SAPI（System.Speech）已装的识别器语言列表；探测一次就缓存。

        为什么要它：判断「还能不能用」必须问 SAPI，而不是拿 WinRT 的失败当整机结论。
        返回 [] 表示 SAPI 也没有可用识别器。
        """
        with self._lock:
            if self._sapi_cache is not None:
                return self._sapi_cache
        if not os.path.exists(self.ps1):
            return []
        try:
            _rc, out, _err = self._run(['-List'], timeout=20)
        except Exception as e:
            _log.warning('枚举 SAPI 识别器失败：%s' % e)
            return []
        # 输出契约：LIST|zh-CN,en-US（**不能用** parse_result —— 它认的是 OK|<置信度>|<文本>，
        # 会把 "OK|zh-CN" 里的 zh-CN 当成置信度、文本读成空，导致这里永远返回 []）
        payload = ''
        for ln in str(out or '').splitlines():
            s = ln.strip()
            if s.startswith('LIST|'):
                payload = s[5:]
                break
            if s.startswith('ERR|'):
                _log.warning('枚举 SAPI 识别器失败：%s' % s[4:])
                return []
        cults = [c.strip() for c in payload.split(',') if c.strip()]
        with self._lock:
            self._sapi_cache = cults
        return cults

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
            # 2026-10-25：asr_http_url 可能是本地 whisper 服务，也可能在云端。
            #   net_local 只在 host 是环回地址时绕代理，云端行为不变。
            import net_local
            with net_local.urlopen(req, timeout=60) as r:
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

        路径：先 WinRT（OneCore，真正的中文识别模型）；它**不可用/抛异常**时降级 SAPI
        （System.Speech，质量明显差，仅作兜底）。

        2026-10-25 更正：旧注释说「WinRT 常被 OneCore 隐私策略挡住」——**那是误判**。
        真实原因是没有 CompileConstraintsAsync 就调 RecognizeAsync，会抛
        InvalidOperationException 0x80131509；而注册表里
        OnlineSpeechPrivacy 下的 HasAccepted 一直是 1。修好编译之后 WinRT 才第一次真正被用上。
        这也解释了为什么以前"时灵时不灵"：一直在用质量最差的 SAPI。
        """
        if not os.path.exists(self.ps1):
            return '', '', '缺少 asr_helper.ps1'
        winrt_err, winrt_hint = '', ''
        if self._policy_blocked:
            # 上一轮已实测过 WinRT 被 OneCore 隐私策略挡住：别再白等一轮必然失败的识别
            # （那一轮最长 25 秒，使用者会以为按钮坏了），直接进下面的 SAPI 降级。
            winrt_err = 'WinRT 已被系统语音隐私策略挡住，直接走备用识别'
        else:
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
                if (conf or '').strip().lower() == 'rejected':
                    # WinRT 听到了声音但不敢认（本机实测：外放与静音都 Rejected）。
                    # 这时仍要降级 SAPI —— 宁可给一个低可信的猜测，也不要"点了完全没反应"。
                    # （原先为了省时间直接返回，依据是"WinRT 一定更好"；但本机实测
                    #   WinRT 0% 出字、SAPI 约 2/3 能出字，那个依据不成立。）
                    self._last_winrt_rejected = True
                    winrt_err = '识别器听到了声音但不敢确认'
                    winrt_hint = ''
                else:
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

        if getattr(self, '_last_winrt_rejected', False):
            self._last_winrt_rejected = False
            return '', '', ('没听准 —— 备用识别也没给出结果。'
                            '本机麦克风底噪较大（实测静音峰值约 25%），'
                            '建议靠近麦克风、在安静处说，或换用在线识别接口')
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
        return proc.returncode, _decode_out(out), _decode_out(err)
