# -*- coding: utf-8 -*-
"""voice_io.py — 语音朗读（v6.63 / v6.64 接入在线神经声线）
=============================================================

范围：**只做「朗读」**（TTS 输出），语音输入（ASR）属 P1，另行开工。

两档声线（默认走在线，音质好；离线作兜底）
----------------------------------------
| 引擎 | 合成 | 播放 | 依赖 | 音质 |
|---|---|---|---|---|
| **在线 `edge`**（默认） | edge-tts（微软神经声线，24kHz MP3） | MCI（ctypes winmm，可打断） | `edge_tts` 包（打包时随包，可选） | 好（与助手同款晓晓） |
| 离线 `offline` | WinRT 内置声线（失败回退 SAPI）→ WAV | winsound（异步、可 PURGE） | 零（系统自带 + 标准库） | 一般（拼接式，偏机械） |

- `engine='auto'`（默认）：先试在线，**失败或超时自动转离线**，不会因为断网就哑掉。
- 用户可显式选离线（不想联网时）或指定某个在线声线。

其它行为
--------
- **默认关闭**：`enabled=False` 时**零子进程、零音频**（连脚本都不启动）。
- **夜间静音**：默认 23:00–08:00 不出声 —— 用**本机本地时间**（是“用户所在时区的夜晚”，
  与计价用北京时间不同：计价看官方口径，静音看人的生活作息）。
- **顺序队列**：同一时刻只播一句，后续排队；`stop()` 立刻打断并清空队列。
- **文本清洗**：剥 `[emotion:xxx]` 标签、Markdown、代码块、URL、表情，截断到上限。
- 不依赖 PySide6（便于 headless 单测/复用）；`edge_tts` 采用**惰性导入**，缺了也能跑（自动转离线）。
"""
import os
import queue
import re
import subprocess
import threading
import time
import wave

from pet_log import get_logger

_log = get_logger('voice_io')

# 朗读文本上限（v6.75：300 → 1200，且可被配置覆盖）
# 使用者反馈“念到一半就停、不知道为啥”——根因就是这个硬上限 300 字：
# 超过就静默截断（只加一个“…”），既不报错也不提示，所以看着像“被系统截断”。
DEFAULT_MAX_CHARS = 1200

# 语速（v6.76）：统一用百分比表示，内部再按引擎换算
#   在线 edge-tts：'+25%' / '-10%'（直接支持）
#   离线 SAPI（System.Speech）：Rate = -10..10，换算 percent//10 并限幅
RATE_MIN, RATE_MAX = -50, 100


def normalize_rate(rate):
    """把用户输入的语速归一成 '+25%' / '-10%' / ''（非法或 0 都归一成 ''）"""
    s = str(rate or '').strip().replace('％', '%')
    if not s:
        return ''
    m = re.match(r'^([+-]?\d+)\s*%?$', s)
    if not m:
        return ''
    val = max(RATE_MIN, min(RATE_MAX, int(m.group(1))))
    if val == 0:
        return ''
    return '%+d%%' % val


def rate_to_sapi(rate):
    """'+25%' → 3（SAPI 的 -10..10）；无设置 → 0"""
    s = normalize_rate(rate)
    if not s:
        return 0
    return max(-10, min(10, int(s.rstrip('%')) // 10))


def rate_to_multiplier(rate):
    """'+25%' → 1.25（供本地 TTS 服务的 speed 字段用）"""
    s = normalize_rate(rate)
    if not s:
        return 1.0
    return 1.0 + int(s.rstrip('%')) / 100.0
DEFAULT_TIMEOUT = 30
EDGE_TIMEOUT = 20              # 在线合成超时（秒）；超了转离线
NIGHT_START_HOUR = 23          # 23:00 起静音
NIGHT_END_HOUR = 8             # 至 08:00
MCI_ALIAS = 'petvoice'         # MCI 播放句柄别名

# 声线清单：(配置值, 显示名, 引擎)
VOICE_CHOICES = (
    ('edge:zh-CN-XiaoxiaoNeural', '在线 · 晓晓（女声，温暖 · 与助手同款）', 'edge'),
    ('edge:zh-CN-XiaoyiNeural', '在线 · 晓伊（女声，活泼）', 'edge'),
    ('edge:zh-CN-YunxiNeural', '在线 · 云希（男声，阳光）', 'edge'),
    ('edge:zh-CN-YunyangNeural', '在线 · 云扬（男声，专业）', 'edge'),
    ('edge:zh-CN-YunxiaNeural', '在线 · 云夏（男声，可爱）', 'edge'),
    ('offline:Huihui', '离线 · 慧慧（女声，不联网）', 'offline'),
    ('offline:Yaoyao', '离线 · 瑶瑶（女声，不联网）', 'offline'),
    ('offline:Kangkang', '离线 · 康康（男声，不联网）', 'offline'),
)
DEFAULT_VOICE = 'edge:zh-CN-XiaoxiaoNeural'

_EMOTION_RE = re.compile(r'\[emotion:[^\]]*\]', re.I)
_CODE_FENCE_RE = re.compile(r'```.*?```', re.S)
_INLINE_CODE_RE = re.compile(r'`([^`]*)`')
_URL_RE = re.compile(r'https?://\S+')
_MD_LINK_RE = re.compile(r'\[([^\]]*)\]\([^)]*\)')
_MD_SYMBOL_RE = re.compile(r'[*_~#>`|]+')
_EMOJI_RE = re.compile(
    '[\U0001F300-\U0001FAFF\U0001F000-\U0001F2FF\u2600-\u27BF\uFE0F\u2B00-\u2BFF]')


def choose_speech_text(text, mode='summary', summary=''):
    """按「朗读内容」策略挑出要念的文本（v6.76）。返回 (要念的文本, 备注)

    mode：
      'full'    → 全文（旧行为）
      'summary' → 有 AI 摘要（工具 set_voice_summary）就念摘要；
                  否则**兜底自动选段**：首段 + 末段，跳过代码块/表格/长列表
      'manual'  → 不自动念（使用者选中后右键朗读）
    """
    s = str(text or '')
    if not s.strip():
        return '', '空文本'
    m = str(mode or 'summary').strip().lower()
    if m == 'manual':
        return '', 'manual：不自动念'
    if m == 'full':
        return s, ''
    sm = str(summary or '').strip()
    if sm:
        return sm, '用 AI 摘要'
    # —— 兜底：首段 + 末段 ——
    blocks = [b.strip() for b in re.split(r'\n\s*\n', s) if b.strip()]
    keep = []
    for b in blocks:
        if b.startswith('```'):                    # 代码块
            continue
        if b.lstrip().startswith('|'):             # 表格
            continue
        listy = [ln for ln in b.splitlines() if re.match(r'^\s*([-*+]|\d+[.)])\s+', ln)]
        if listy and len(listy) >= 4 and len(listy) >= len(b.splitlines()) - 1:
            continue                               # 长列表（要点项）→ 跳过，听着累
        keep.append(b)
    if not keep:
        return s, '兜底失败，改念全文'
    if len(keep) == 1:
        picked = keep[0]
    else:
        picked = keep[0] + '\n' + keep[-1]
        if len(picked) < 20 and len(keep) > 2:     # 首尾都太短 → 补一段
            picked = keep[0] + '\n' + keep[1] + '\n' + keep[-1]
    return picked, '兜底：首段+末段'


def clean_for_speech(text, max_chars=DEFAULT_MAX_CHARS):
    """把回复文本处理成「适合念出来」的样子。返回 '' 表示没什么可念的。

    v6.75：超长时不再静默截断 —— 返回的文本末尾会带「（后略）」，
    并且调用方（VoiceIO.speak）会记一条日志说明“原 N 字 → 念 M 字”，
    避免再出现“莫名其妙被截断”的排查困境。
    """
    s = str(text or '')
    if not s.strip():
        return ''
    s = _CODE_FENCE_RE.sub('（代码省略）', s)
    s = _INLINE_CODE_RE.sub(r'\1', s)
    s = _MD_LINK_RE.sub(r'\1', s)
    s = _URL_RE.sub('链接', s)
    s = _EMOTION_RE.sub('', s)
    s = _EMOJI_RE.sub('', s)
    s = _MD_SYMBOL_RE.sub('', s)
    s = re.sub(r'^\s*[-•·]\s*', '', s, flags=re.M)      # 列表符号
    s = re.sub(r'[ \t]+', ' ', s)
    s = re.sub(r'\n{2,}', '\n', s).strip()
    if len(s) > max_chars:
        s = s[:max_chars].rstrip() + '（后略）'
    if not re.search(r'[\u4e00-\u9fffA-Za-z0-9]', s):
        return ''
    return s


def is_night(now=None, start=NIGHT_START_HOUR, end=NIGHT_END_HOUR):
    """是否处于静音时段（用**本机本地时间**：用户所在时区的夜里）"""
    try:
        h = (now or time.localtime()).tm_hour if not hasattr(now, 'hour') else now.hour
        if start <= end:
            return start <= h < end
        return h >= start or h < end          # 跨零点（23→8）
    except Exception:
        return False


def _win_flags():
    """Windows 下启动子进程的 CREATE_NO_WINDOW（消除控制台闪窗，v6.64）"""
    try:
        return getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
    except Exception:
        return 0


def split_sentences(text, max_len=60):
    """把一段话切成适合“边合成边播”的小句（v6.64，降延时）

    按中英文句末标点切；单句过长再按逗号/顿号回退切，保证首句够短、出声够快。
    """
    s = str(text or '').strip()
    if not s:
        return []
    parts = re.split(r'(?<=[。！？!?；;…])', s)
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        while len(p) > max_len:
            cut = max(p.rfind('，', 0, max_len), p.rfind(',', 0, max_len),
                      p.rfind('、', 0, max_len))
            if cut <= 0:
                cut = max_len
            out.append(p[:cut + 1].strip())
            p = p[cut + 1:].strip()
        if p:
            out.append(p)
    return out or [s]


def list_system_voices(ps1_path, timeout=25):
    try:
        proc = subprocess.run(
            ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ps1_path,
             '-ListVoices'],
            capture_output=True, timeout=timeout, creationflags=_win_flags())
        out = (proc.stdout or b'').decode('utf-8', 'ignore')
    except Exception as e:
        _log.debug('列系统声线失败：%s', e)
        return []
    res, seen = [], set()
    for line in out.splitlines():
        line = line.strip()
        if not line or '|' not in line:
            continue
        cols = line.split('|')
        name = re.sub(r'^Microsoft\s+', '', str(cols[0]).split(':', 1)[-1]).strip()
        # SAPI 侧名字带 “ Desktop” 后缀（同一个声线的另一份），归一后去重
        name = re.sub(r'\s+Desktop$', '', name)
        lang = (cols[1] if len(cols) > 1 else '').strip()
        if not name or name in seen:
            continue
        seen.add(name)
        res.append(('offline:%s' % name, '离线 · %s（%s）' % (name, lang or '?')))
    return res


def list_edge_voices(locale_prefix='zh-', timeout=EDGE_TIMEOUT):
    """列出在线可用声线（需联网）。返回 [(spec, label)]；失败返回 []"""
    try:
        import asyncio
        import edge_tts
    except Exception:
        return []

    async def _run():
        return await asyncio.wait_for(edge_tts.list_voices(), timeout=timeout)

    try:
        voices = asyncio.run(_run())
    except Exception as e:
        _log.debug('列在线声线失败：%s', e)
        return []
    res = []
    for v in (voices or []):
        sn = str(v.get('ShortName') or '')
        if not sn or (locale_prefix and not sn.startswith(locale_prefix)):
            continue
        g = '女声' if str(v.get('Gender')) == 'Female' else '男声'
        short = sn.replace('zh-CN-', '').replace('zh-TW-', '').replace('Neural', '')
        res.append(('edge:%s' % sn, '在线 · %s（%s）' % (short, g)))
    res.sort()
    return res


def parse_voice_spec(spec):
    """'edge:zh-CN-XiaoxiaoNeural' → ('edge', 'zh-CN-XiaoxiaoNeural')；空/非法 → 默认在线声线

    也支持本地自建服务：'local:http://127.0.0.1:9880' → ('local', 'http://127.0.0.1:9880')
    （用于按 GPT-SoVITS / CosyVoice / ChatTTS 这类本地 TTS 服务 —— 训练/克隆好之后直接填地址即可）
    """
    s = str(spec or '').strip()
    if not s:
        return parse_voice_spec(DEFAULT_VOICE)
    if ':' in s:
        eng, _, name = s.partition(':')
        eng = eng.strip().lower()
        if eng in ('edge', 'offline', 'winrt', 'sapi', 'local'):
            return ('offline' if eng in ('winrt', 'sapi') else eng), name.strip()
    # 只写了声线名（兼容旧配置：Huihui 这类就是离线声线）
    if s in ('Huihui', 'Yaoyao', 'Kangkang'):
        return 'offline', s
    if s.startswith('http://') or s.startswith('https://'):
        return 'local', s
    if s.startswith('zh-'):
        return 'edge', s
    return parse_voice_spec(DEFAULT_VOICE)


def probe_local_service(url, timeout=3):
    """探一下本地 TTS 服务是否在回应（v6.64）

    这类服务（GPT-SoVITS 的 api_v2 / CosyVoice / ChatTTS）没有统一的 /health，
    所以“能拿到任何 HTTP 响应”就算活着（404 也算）——够用于给用户一个明确提示。
    """
    import urllib.error
    import urllib.request
    base = str(url or '').strip().rstrip('/')
    if not base:
        return False, '未填地址'
    try:
        req = urllib.request.Request(base + '/', method='GET')
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, 'HTTP %s' % r.status
    except urllib.error.HTTPError as e:
        return True, 'HTTP %s（服务在跑）' % e.code
    except Exception as e:
        return False, '%s: %s' % (type(e).__name__, str(e)[:80])


def _mci(cmd):
    """MCI 命令（Windows 自带，播 MP3 用）。非 Windows / 失败 → 返回 (False, '')"""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(256)
        rc = ctypes.windll.winmm.mciSendStringW(cmd, buf, 254, None)
        return (rc == 0), buf.value
    except Exception:
        return False, ''


class VoiceIO:
    """朗读器：在线 edge-tts（默认，音质好）/ 离线系统声线（兜底），失败自动降级"""

    def __init__(self, base_dir, enabled=False, engine='auto', voice='',
                 night_quiet=True, max_chars=DEFAULT_MAX_CHARS, timeout=DEFAULT_TIMEOUT,
                 runner=None, local_url='', local_ref='', local_prompt='', local_lang='zh',
                 local_timeout=20, rate=''):
        self.base_dir = base_dir
        self.ps1 = os.path.join(base_dir, 'tts_helper.ps1')
        self.enabled = bool(enabled)
        self.engine = engine or 'auto'          # auto / edge / offline / local
        self.voice = voice or DEFAULT_VOICE     # 'edge:…' / 'offline:…' / 'local:http://…'
        self.rate = normalize_rate(rate)        # v6.76 语速，统一存成 '+25%' / '-10%' / ''
        self.local_url = local_url or ''        # 本地自建 TTS 服务（自训练/克隆模型）
        self.local_ref = local_ref or ''        # 参考音频（零样本克隆用）
        self.local_prompt = local_prompt or ''  # 参考音频对应的文本
        self.local_lang = local_lang or 'zh'
        self.local_timeout = int(local_timeout)
        self.night_quiet = bool(night_quiet)
        self.max_chars = int(max_chars)
        self.timeout = int(timeout)
        self.last_error = ''
        self.last_engine = ''
        self.fell_back = False                  # 上一次是否从在线降级到离线
        self.spoken_count = 0
        self._runner = runner                   # 测试注入用；None → 用真实链路
        self._q = queue.Queue()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop_all = False
        self._playing = False
        self._worker = threading.Thread(target=self._loop, daemon=True)
        self._worker.start()

    # ---------- 对外接口 ----------
    def set_config(self, enabled=None, engine=None, voice=None, night_quiet=None,
                   local_url=None, local_ref=None, local_prompt=None, rate=None):
        with self._lock:
            if enabled is not None:
                self.enabled = bool(enabled)
            if engine:
                self.engine = engine
            if voice is not None:
                self.voice = voice
            if rate is not None:
                self.rate = normalize_rate(rate)
            if night_quiet is not None:
                self.night_quiet = bool(night_quiet)
            if local_url is not None:
                self.local_url = local_url
            if local_ref is not None:
                self.local_ref = local_ref
            if local_prompt is not None:
                self.local_prompt = local_prompt

    def blocked_reason(self, now=None):
        """现在不能朗读的原因（'' = 可以读）—— 供界面如实提示"""
        if not self.enabled:
            return 'off'
        if self.night_quiet and is_night(now):
            return 'night'
        return ''

    def speak(self, text, now=None, force=False):
        """排队朗读一段文本。返回 True 表示已入队（不代表已播完）

        force=True → 忽略「开关关闭」与「夜间静音」（用于用户主动点「朗读这一条 / 试听」）
        """
        if not force:
            reason = self.blocked_reason(now)
            if reason:
                _log.debug('朗读跳过（%s）', reason)
                return False
        spoken = clean_for_speech(text, self.max_chars)
        if not spoken:
            return False
        # v6.75：截断不再“莫名其妙”—— 过长时把“原 N 字 → 念 M 字”写进日志
        if len(str(text or '')) > self.max_chars:
            _log.info('朗读文本超限，已截断：原 %d 字 → 念 %d 字'
                      '（上限 %d，可在 config.json 改 voice_max_chars）',
                      len(str(text or '')), self.max_chars, self.max_chars)
        self._q.put(spoken)
        self._wake.set()
        return True

    def stop(self):
        """立刻打断当前朗读并清空队列"""
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass
        self._stop_all = True
        self._wake.set()
        self._purge()
        return True

    def pending(self):
        return self._q.qsize()

    def engine_plan(self):
        """按配置算出引擎尝试顺序（返回 ['local','edge','offline'] 这类列表）

        本地服务 → 在线 → 离线：逐级降级，保证“总有声音”，但优先用用户自己的声音。
        """
        want = self.engine
        if want in ('edge', 'offline', 'local'):
            return [want, 'offline'] if want != 'offline' else ['offline']
        spec_engine, _ = parse_voice_spec(self.voice)
        if spec_engine == 'local':
            return ['local', 'edge', 'offline']
        if spec_engine == 'offline':
            return ['offline']
        return ['edge', 'offline']

    # ---------- 播放：WAV 用 winsound，MP3 用 MCI ----------
    def _purge(self):
        try:
            import winsound
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass
        _mci('stop %s' % MCI_ALIAS)
        _mci('close %s' % MCI_ALIAS)

    def _play_wav(self, path):
        """winsound 异步播放；返回时长（秒）"""
        dur = 0.0
        try:
            with wave.open(path) as w:
                dur = w.getnframes() / float(w.getframerate() or 1)
        except Exception:
            dur = 3.0
        try:
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception as e:
            self.last_error = '播放失败：%s' % e
            return 0.0
        return dur

    def _play_mp3(self, path):
        """MCI 播放 MP3；返回时长（秒）。失败返回 0（调用方据此降级）"""
        _mci('close %s' % MCI_ALIAS)
        ok, _ = _mci('open "%s" type mpegvideo alias %s' % (path, MCI_ALIAS))
        if not ok:
            self.last_error = 'MCI 打不开音频'
            return 0.0
        _, ms = _mci('status %s length' % MCI_ALIAS)
        try:
            dur = float(ms) / 1000.0
        except ValueError:
            dur = 3.0
        ok, _ = _mci('play %s' % MCI_ALIAS)
        if not ok:
            self.last_error = 'MCI 播放失败'
            return 0.0
        return dur

    # ---------- 合成 ----------
    def _synth_edge(self, text, out_path):
        """在线合成（edge-tts，MP3）。返回 (是否成功, 错误)"""
        try:
            import asyncio
            import edge_tts            # 惰性导入：没装/没网都不影响离线朗读
        except Exception as e:
            return False, 'edge_tts 不可用：%s' % type(e).__name__
        _, vname = parse_voice_spec(self.voice)
        if not vname.startswith('zh-') and not vname.startswith('en-'):
            vname = 'zh-CN-XiaoxiaoNeural'

        async def _run():
            # v6.76：语速（'+25%' / '-10%'；'/' → 默认语速）
            comm = edge_tts.Communicate(text, vname, rate=(self.rate or '+0%'))
            await asyncio.wait_for(comm.save(out_path), timeout=EDGE_TIMEOUT)

        try:
            asyncio.run(_run())
        except Exception as e:
            return False, '在线合成失败：%s' % str(e)[:100]
        if not os.path.exists(out_path) or os.path.getsize(out_path) < 256:
            return False, '在线合成没有产出音频'
        return True, ''

    def _synth_local(self, text, base):
        """本地自建 TTS 服务（v6.64）：POST 文本 → 直接拿音频字节

        约定（兼容 GPT-SoVITS api_v2 / CosyVoice / ChatTTS 这类常见实现）：
        `POST {base}/tts`，body = {'text': ..., 'text_lang': 'zh',
        'ref_audio_path': …, 'prompt_text': …}，响应体直接是音频（wav/mp3）。
        返回 (path, kind, error)。
        """
        import json as _json
        import urllib.request
        _, url = parse_voice_spec(self.voice)
        url = (url or self.local_url or '').strip().rstrip('/')
        if not url:
            return '', '', '未配置本地服务地址'
        payload = {'text': text, 'text_lang': (self.local_lang or 'zh'), 'media_type': 'auto'}
        # v6.76：语速（可选字段，服务端不认识会忽略；认的话按倍数调速）
        _spd = rate_to_multiplier(self.rate)
        if _spd != 1.0:
            payload['speed'] = _spd
        if self.local_ref:
            payload['ref_audio_path'] = self.local_ref
        if self.local_prompt:
            payload['prompt_text'] = self.local_prompt
        try:
            req = urllib.request.Request(
                url + '/tts', data=_json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=self.local_timeout) as r:
                ctype = (r.headers.get('Content-Type') or '').lower()
                data = r.read()
        except Exception as e:
            return '', '', '本地 TTS 服务不可用：%s' % str(e)[:100]
        if not data:
            return '', '', '本地服务返回了空音频'
        kind = 'mp3' if ('mpeg' in ctype or 'mp3' in ctype
                         or data[:3] == b'ID3' or data[:2] in (b'\xff\xfb', b'\xff\xf3')) else 'wav'
        path = base + ('.mp3' if kind == 'mp3' else '.wav')
        try:
            with open(path, 'wb') as f:
                f.write(data)
        except Exception as e:
            return '', '', '写入音频失败：%s' % str(e)[:80]
        return path, kind, ''

    def _synth_offline(self, text, out_path):
        """离线合成（tts_helper.ps1：WinRT → SAPI 兜底），产出 WAV。返回 (是否成功, 错误)"""
        if not os.path.exists(self.ps1):
            return False, '离线合成脚本缺失：%s' % self.ps1
        try:
            _, vname = parse_voice_spec(self.voice)
            if vname.startswith('zh-') or vname.startswith('en-'):
                vname = ''                     # 在线声线名不适用于系统声线 → 用默认
            cmd = ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', self.ps1,
                   '-Text', text, '-Out', out_path]
            if self.engine in ('winrt', 'sapi'):
                cmd += ['-Engine', self.engine]
            if vname:
                cmd += ['-Voice', vname]
            _sapi_rate = rate_to_sapi(self.rate)     # v6.76 语速：percent → SAPI -10..10
            if _sapi_rate:
                cmd += ['-Rate', str(_sapi_rate)]
            # v6.64：CREATE_NO_WINDOW —— 不再先闪一下控制台黑框（使用者反馈很突兀）
            proc = subprocess.run(cmd, capture_output=True, timeout=self.timeout,
                                  creationflags=_win_flags())
        except Exception as e:
            return False, '离线合成失败：%s' % str(e)[:100]
        if not os.path.exists(out_path) or os.path.getsize(out_path) < 128:
            err = ((proc.stdout or b'').decode('utf-8', 'ignore')[:100] + ' ' +
                   (proc.stderr or b'').decode('utf-8', 'ignore')[:160]).strip()
            return False, '离线合成失败：%s' % err
        return True, ''

    # ---------- 主链路（默认实现；测试可注入 runner） ----------
    def _synth_any(self, text, base):
        """按引擎顺序合成一句，返回 (path, kind, engine)；全失败返回 (None, '', '')"""
        last_err = ''
        for idx, engine in enumerate(self.engine_plan()):
            if engine == 'local':
                path, kind, err = self._synth_local(text, base)
                if path:
                    self._mark_engine(idx, 'local', last_err)
                    return path, kind, 'local'
                last_err = err
                self.fell_back = True
            elif engine == 'edge':
                mp3 = base + '.mp3'
                ok, err = self._synth_edge(text, mp3)
                if ok:
                    self._mark_engine(idx, 'edge', last_err)
                    return mp3, 'mp3', 'edge'
                last_err = err
                self.fell_back = True
            else:
                wav = base + '.wav'
                ok, err = self._synth_offline(text, wav)
                if ok:
                    self._mark_engine(idx, 'offline', last_err)
                    return wav, 'wav', 'offline'
                last_err = err
        self.last_error = last_err
        return None, '', ''

    def _mark_engine(self, idx, engine, last_err):
        """记下实际用的引擎；若是“前一个引擎失败后降级”来的，把原因留着（用户要能看出音色为何变了）"""
        self.last_engine = engine
        if idx > 0 and last_err:
            self.fell_back = True
            self.last_error = '已降级（%s）' % last_err
        else:
            self.last_error = ''

    def _play_kind(self, path, kind):
        return self._play_mp3(path) if kind == 'mp3' else self._play_wav(path)

    def _default_runner(self, out_base, text):
        """句子级流水线（v6.64 降延时）：

        合成第 1 句 → 立刻开声 → **在它播放期间并行合成下一句** → 播完无缝接上。
        听感延时 ≈ 首句的合成时间，而不是整段文本的合成时间。
        """
        chunks = split_sentences(text)
        if not chunks:
            return 0.0
        self.fell_back = False                     # 本轮是否发生“在线→离线”降级
        prepared = None
        total = 0.0
        first_engine = ''
        for i, ch in enumerate(chunks):
            if self._stop_all:                     # 被 stop() 打断
                break
            if prepared is None:
                path, kind, engine = self._synth_any(ch, '%s_%d' % (out_base, i))
                if not path:
                    return total
            else:
                path, kind, engine = prepared
            t0 = time.time()
            dur = self._play_kind(path, kind)
            if not dur and kind == 'mp3':
                # 在线合成好了却播不出来（少见）→ 这一句现场转离线
                w = '%s_%do.wav' % (out_base, i)
                ok, _err = self._synth_offline(ch, w)
                if ok:
                    dur = self._play_wav(w)
                    kind, engine = 'wav', 'offline'
            if not dur:
                break
            if not first_engine:
                first_engine = engine
            total += dur
            # ★ 播放期间把下一句先合成好（这步是降延时的关键）
            prepared = (self._synth_any(chunks[i + 1], '%s_%d' % (out_base, i + 1))
                        if i + 1 < len(chunks) else None)
            remaining = dur - (time.time() - t0)
            if remaining > 0:
                self._wake.clear()
                self._wake.wait(timeout=min(remaining, 60))
                if self._stop_all:                  # stop() 叫醒 → 立刻掐断
                    self._purge()
                    break
        if not first_engine and not self.last_engine:
            self.last_engine = ''
        return total

    def _loop(self):
        while True:
            try:
                item = self._q.get(timeout=0.5)
            except queue.Empty:
                if self._stop_all:
                    self._stop_all = False
                continue
            if item is None:
                return
            if self._stop_all:
                self._stop_all = False
                continue
            base = os.path.join(self.base_dir, '_pet_tts_%d' % int(time.time() * 1000))
            try:
                self._playing = True
                runner = self._runner or self._default_runner
                dur = float(runner(base, item) or 0.0)   # runner 内部负责“边播边合成”的节奏
                if dur:
                    self.spoken_count += 1
                self._purge()
            except Exception as e:
                self.last_error = str(e)[:160]
                _log.debug('朗读失败：%s', e)
            finally:
                self._playing = False
                try:
                    import glob as _glob
                    for p in _glob.glob(base + '*'):   # 分句产出的多个临时音频一并清掉
                        try:
                            os.remove(p)
                        except Exception:
                            pass
                except Exception:
                    pass
