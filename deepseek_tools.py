# -*- coding: utf-8 -*-
"""deepseek_tools.py — DeepSeek「全家桶应用 API」统一封装（2026-11-13）

覆盖五个接口：Search / Fetch / OCR / ASR / TTS。
设计原则与 memory_embed.py 一致：**可选组件，缺失即降级，但绝不静默**。

═══════════════════════════════════════════════════════════════════
实测得出的硬约束（2026-11-13 亲手跑出来的，别凭文档改）
═══════════════════════════════════════════════════════════════════

1. OCR 会 **HTTP 200 + body 里带 error**（格式不支持时）。
   只判状态码会把失败当成功（拿到空文本还以为「识别结果就是空」）。
   实测：纯 .txt 文件连续两次都是 200 + `{"error": {...}}`。
   ⇒ `_json_or_error()` 必须同时检查 status 与 body 的 error 键。

2. ASR 文件超过 8 MiB 时，服务端**直接断连接**（WinError 10054），
   不是返回 413。⇒ 必须**本地先查大小**，不能指望服务端报错。

3. TTS 返回的 WAV，`data` 段长度写的是 `0xFFFFFFFF`（流式占位）。
   按头算时长会得到荒谬值（实测算出 89478 秒）。
   ⇒ 时长一律按**文件实际长度**反推。

4. Search 的罕见词可能返回**垃圾结果**（某 PDF 抽出的 "None None None" 表格），
   但它的 `rerank_score` 只有 0.105，而正常结果 2.2~2.3。
   官方口径：`rerank_score >= 1.5` 为优质；`authority >= 3` 为极权威。
   ⇒ 默认按 `min_rerank=1.5` 过滤，能挡掉这类噪声。

5. Search 的 count 只接受 **1~50**，越界是 400（不是截断）。

6. 并发实测：40 并发全部 200，实测到 57 QPS。
   ⇒ 旧代码里「官方 QPS 仅 5」的 200ms 强制间隔**过严约 20 倍**。

7. OCR 偶发返回空文本（1 次，随后连测 8 次都正常）。
   ⇒ 空结果重试一次，仍空才当失败。

计费（官方 2026-11-13）：Search/Fetch 5 元/千次、OCR 1.5 元/千页、
TTS 3 元/万字符（限时 1.5）、ASR 0.78 元/小时（限时 0.39）。
只有成功且产出结果才计费。
"""
import io
import json
import logging
import os
import re
import struct
import time
import urllib.error
import urllib.request
import uuid

_log = logging.getLogger('pet.deepseek_tools')

BASE = 'https://api.deepseek.com'
SEARCH_URL = BASE + '/v1/tools/search'
FETCH_URL = BASE + '/v1/tools/fetch'
OCR_URL = BASE + '/v1/tools/ocr'
ASR_URL = BASE + '/v1/tools/asr'
TTS_URL = BASE + '/v1/tools/tts'

#: 官方限制（实测确认）
SEARCH_COUNT_MIN, SEARCH_COUNT_MAX = 1, 50
OCR_MAX_BYTES = 100 * 1024 * 1024
ASR_MAX_BYTES = 8 * 1024 * 1024
ASR_MAX_SECONDS = 120
TTS_MAX_BILLED_CHARS = 10000

#: 官方口径：rerank_score >= 1.5 为优质结果
RERANK_GOOD = 1.5

#: TTS 合法音色（实测：传别的返回 400 invalid voice_id）
TTS_VOICES = ('stella', 'tide')
TTS_FORMATS = ('wav', 'pcm')

#: 网络超时（秒）。OCR 官方说总时长上限 180s，这里留足。
T_SEARCH = 40
T_FETCH = 60
T_OCR = 180
T_ASR = 90
T_TTS = 60


# ---------------------------------------------------------------- 基础设施

def api_key(base_dir=''):
    """取 DeepSeek Key：先 config.json，再环境变量。取不到返回 ''。

    ⛔ 不打日志、不打印 —— 凭证不进日志是硬约束。
    """
    try:
        p = os.path.join(base_dir or os.path.dirname(os.path.abspath(__file__)),
                         'config.json')
        if os.path.isfile(p):
            with io.open(p, encoding='utf-8') as f:
                d = json.loads(f.read())
            k = str(d.get('deepseek_api_key') or '').strip()
            if k:
                return k
    except Exception as exc:
        _log.warning('读 config.json 取 Key 失败：%s', exc)
    return str(os.environ.get('DEEPSEEK_API_KEY') or '').strip()


class ApiError(Exception):
    """带状态码与官方 message 的错误（message 直接给人看）"""

    def __init__(self, status, message, code=''):
        self.status = status
        self.message = message or ''
        self.code = code or ''
        Exception.__init__(self, 'HTTP %s: %s' % (status, self.message or code))

    def human(self):
        """翻成用户能懂的一句话（照着实测到的错误码写，不瞎猜）"""
        s, m = self.status, (self.message or '')
        if s == 400:
            return '请求不合法：%s' % (m or '参数有误')
        if s == 401:
            return 'DeepSeek Key 无效或已过期 —— 请在 设置 → 模型 里重新填写'
        if s == 402:
            return '余额不足，请先充值（DeepSeek 平台）'
        if s == 403:
            return '被安全策略拒绝：%s' % (m or '内容或目标不允许')
        if s == 404:
            return '取不到内容：%s' % (m or '地址不可用或被站点拦截')
        if s == 408:
            return 'HTTP 408：请求超时，稍后重试'
        if s == 413:
            return 'HTTP 413：文件太大'
        if s == 429:
            return '搜索接口限流（429），稍等片刻再试'
        if s == 500:
            return 'HTTP 500：服务器内部错误，稍后重试'
        if s == 503:
            return 'HTTP 503：服务繁忙，稍后重试'
        if s == 504:
            return 'HTTP 504：下游超时，稍后重试'
        if s < 0:
            return '网络错误：%s' % m
        return 'HTTP %s：%s' % (s, m or self.code)


def _request(url, body, key, timeout, content_type='application/json'):
    """返回 (status, bytes)。网络异常返回 (-1, 错误说明 bytes)。"""
    req = urllib.request.Request(
        url, data=body,
        headers={'Content-Type': content_type,
                 'Authorization': 'Bearer ' + key})
    try:
        import net_local          # 项目自带：只在环回地址绕代理
        opener = net_local.urlopen
    except Exception as exc:
        # 回退标准 urllib 是正常路径（没装/没这个模块），但要能查出来
        _log.debug('net_local 不可用，回退标准 urllib：%s', exc)
        opener = urllib.request.urlopen
    try:
        with opener(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except Exception as exc:
        _log.warning('请求失败：%s', exc)
        return -1, ('%s' % exc).encode('utf-8', 'replace')


def _json_or_error(url, payload, key, timeout):
    """POST JSON 并**同时**检查状态码与 body 里的 error 键。

    ⚠ 实测：OCR 在格式不支持时给 HTTP 200 + {"error": ...}。
      只判状态码会把失败当成功。这里统一在 200 下也查 error。
    """
    status, raw = _request(url, json.dumps(payload).encode('utf-8'), key, timeout)
    if status < 0:
        raise ApiError(status, raw.decode('utf-8', 'replace')[:200])
    try:
        obj = json.loads(raw.decode('utf-8', 'replace'))
    except Exception:
        raise ApiError(status, '返回不是 JSON：%s' % raw[:160].decode('utf-8', 'replace'))
    if isinstance(obj, dict) and obj.get('error'):
        err = obj['error'] if isinstance(obj['error'], dict) else {'message': str(obj['error'])}
        raise ApiError(status, err.get('message') or '', err.get('code') or '')
    if status != 200:
        raise ApiError(status, '')
    return obj


def _multipart(fields, file_field, filename, file_bytes, mime='application/octet-stream'):
    """构造 multipart/form-data。fields 是 [(name, value)] 的普通文本字段。"""
    b = '----petboundary' + uuid.uuid4().hex
    chunks = []
    for name, value in fields:
        chunks.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                       % (b, name, value)).encode('utf-8'))
    chunks.append(('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\n'
                   'Content-Type: %s\r\n\r\n' % (b, file_field, filename, mime)).encode('utf-8'))
    chunks.append(file_bytes)
    chunks.append(('\r\n--%s--\r\n' % b).encode('utf-8'))
    return b''.join(chunks), 'multipart/form-data; boundary=' + b


# ---------------------------------------------------------------- Search

def search(query, count=5, need_content=False, min_rerank=None,
           ori_question=None, localization=None, key='', timeout=T_SEARCH):
    """网页搜索。返回 (results, error)。

    results: 列表，每项含 rerank_score / title / url / snippet / summary /
             content / site_name / site_icon / date / authority
    min_rerank: 低于此分数的结果被丢弃（None = 不筛）。
                默认由调用方决定；官方口径 1.5 为优质。
    """
    q = (query or '').strip()
    if not q:
        return [], '搜索词不能为空'
    q = q[:128]                                  # 官方上限 128 字符（实测越界 400）
    try:
        c = int(count)
    except Exception as exc:
        _log.warning('count=%r 不是整数，用默认 5：%s', count, exc)
        c = 5
    c = max(SEARCH_COUNT_MIN, min(SEARCH_COUNT_MAX, c))
    payload = {'query': q, 'count': c}
    if need_content:
        payload['need_content'] = True
    if ori_question:
        payload['ori_question'] = str(ori_question)[:128]
    if localization:
        payload['localization'] = str(localization)
    try:
        obj = _json_or_error(SEARCH_URL, payload, key, timeout)
    except ApiError as exc:
        return [], exc.human()
    rs = obj.get('results') or []
    if min_rerank is not None:
        try:
            lo = float(min_rerank)
        except Exception as exc:
            _log.warning('min_rerank=%r 不是数字，本次不筛：%s', min_rerank, exc)
            lo = 0.0
        if lo > 0:
            # 2026-11-13：**分数缺失 ≠ 分数差**。
            #   原写法 `float(x.get(...) or 0)` 会把「没有这个字段」当成 0 直接丢掉；
            #   一旦服务端改版少了该字段，整批结果会被清空，表现为「搜索无结果」——
            #   比不筛还糟。现在只有「分数确实是数字」时才参与筛选。
            kept = []
            for x in rs:
                sc = x.get('rerank_score')
                try:
                    scv = float(sc)
                except (TypeError, ValueError):
                    kept.append(x)          # 不知道分数 ⇒ 不参与筛选，保留
                    continue
                if scv >= lo:
                    kept.append(x)
            _log.info('搜索 %r：%d 条 → 按 rerank_score>=%.2f 保留 %d 条',
                      q, len(rs), lo, len(kept))
            rs = kept
    return rs, ''


def format_results(results, max_items=5, with_summary=True):
    """把结构化结果排成给模型看的纯文本（省 token：默认不用 content）"""
    if not results:
        return '（没有找到相关结果）'
    out = []
    for i, x in enumerate(results[:max_items], 1):
        title = (x.get('title') or '').strip() or '(无标题)'
        out.append('%d. %s' % (i, title))
        out.append('   %s' % (x.get('url') or ''))
        sm = (x.get('summary') or x.get('snippet') or '').strip()
        if with_summary and sm:
            out.append('   %s' % sm[:600].replace('\n', ' '))
        meta = []
        if x.get('date'):
            meta.append(str(x['date'])[:10])
        if x.get('site_name'):
            meta.append(str(x['site_name']))
        if x.get('authority') is not None:
            meta.append('权威度 %s' % x.get('authority'))
        if meta:
            out.append('   （%s）' % ' · '.join(meta))
    return '\n'.join(out)


# ---------------------------------------------------------------- Fetch

def fetch(url, key='', timeout=T_FETCH):
    """抓取单页 → (title, markdown_content, error)"""
    u = (url or '').strip()
    if not u:
        return '', '', '网址不能为空'
    if not re.match(r'^https?://', u, re.I):
        return '', '', '只支持 http/https 网址'
    if len(u) > 8192:
        return '', '', '网址过长（上限 8192 字符）'
    try:
        obj = _json_or_error(FETCH_URL, {'url': u}, key, timeout)
    except ApiError as exc:
        return '', '', exc.human()
    return (obj.get('title') or '', obj.get('content') or '', '')


# ---------------------------------------------------------------- OCR

def ocr(file_path, purpose='text_recognition', key='', timeout=T_OCR,
        retry_empty=True):
    """识别文档/图片 → (pages, error)

    pages: [{'index': 0, 'text': '...', 'finish_reason': 'stop'}, ...]
    purpose: text_recognition（纯文字优先）| rich_layout_recognition（带坐标与表格）
    """
    if purpose not in ('text_recognition', 'rich_layout_recognition'):
        return [], 'purpose 只能是 text_recognition / rich_layout_recognition'
    p = (file_path or '').strip()
    if not p or not os.path.isfile(p):
        return [], '文件不存在：%s' % (p or '(空)')
    size = os.path.getsize(p)
    if size > OCR_MAX_BYTES:
        return [], '文件超过 100 MiB（%.1f MiB）' % (size / 1048576.0)
    if size == 0:
        return [], '文件是空的'
    try:
        # ⛔ 不许写成「open 后直接 .read()」的一行式 —— 长驻进程里是真实句柄泄漏
        #   （tests/test_product_open_hygiene.py 钉着这条）
        with io.open(p, 'rb') as f:
            data = f.read()
    except Exception as exc:
        _log.warning('读文件失败 %s：%s', p, exc)
        return [], '读文件失败：%s' % exc
    body, ctype = _multipart([('purpose', purpose)], 'file',
                             os.path.basename(p), data, mime_hint(p))
    status, raw = _request(OCR_URL, body, key, timeout, content_type=ctype)
    if status < 0:
        return [], '网络错误：%s' % raw.decode('utf-8', 'replace')[:160]
    try:
        obj = json.loads(raw.decode('utf-8', 'replace'))
    except Exception as exc:
        _log.warning('OCR 返回不是 JSON：%s', exc)
        return [], '返回不是 JSON：%s' % raw[:160].decode('utf-8', 'replace')
    # ⚠ 这一条是实测踩出来的：格式不支持时给 200 + error
    if isinstance(obj, dict) and obj.get('error'):
        err = obj['error'] if isinstance(obj['error'], dict) else {'message': str(obj['error'])}
        return [], ApiError(status or 400, err.get('message') or '').human()
    if status != 200:
        return [], ApiError(status, '').human()
    pages = obj.get('pages') or []
    text_all = ''.join((pg.get('text') or '') for pg in pages)
    if retry_empty and not text_all.strip():
        # 实测：偶发空返回（1 次，随后连测 8 次正常）⇒ 重试一次
        _log.info('OCR 返回空，重试一次：%s', os.path.basename(p))
        time.sleep(0.6)
        return ocr(file_path, purpose, key, timeout, retry_empty=False)
    return pages, ''


def ocr_text(file_path, purpose='text_recognition', key=''):
    """只要合并后的文本。失败返回 ''（调用方自己提示）。"""
    pages, err = ocr(file_path, purpose, key)
    if err:
        return ''
    return '\n'.join((pg.get('text') or '') for pg in pages).strip()


def strip_layout_marks(text):
    """把 rich_layout 的 <｜ref｜>…<｜/ref｜><｜box｜>[[...]]<｜/box｜> 去掉，只留文字。

    给「只想读文字、不要坐标」的场景用。表格会保留成 HTML <table>。
    """
    if not text:
        return ''
    s = re.sub(r'<｜ref｜>[^<]*<｜/ref｜>', '', text)
    s = re.sub(r'<｜box｜>\[\[[^\]]*\]\]<｜/box｜>', '', s)
    return re.sub(r'[ \t]{2,}', ' ', s).strip()


def mime_hint(path):
    e = os.path.splitext(str(path))[1].lower()
    return {
        '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.webp': 'image/webp', '.gif': 'image/gif', '.bmp': 'image/bmp',
        '.tif': 'image/tiff', '.tiff': 'image/tiff',
        '.pdf': 'application/pdf',
        '.doc': 'application/msword',
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.ppt': 'application/vnd.ms-powerpoint',
        '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    }.get(e, 'application/octet-stream')


# ---------------------------------------------------------------- ASR

def wav_info(path):
    """读 WAV 头 → dict(rate, channels, bits, seconds, bytes)。

    ⚠ `data` 段长度可能是 0xFFFFFFFF（TTS 那种流式占位）⇒ 不可信时用文件长度反推。
    """
    try:
        size = os.path.getsize(path)
        with io.open(path, 'rb') as f:
            head = f.read(4096)
    except Exception as exc:
        _log.warning('读 WAV 头失败 %s：%s', path, exc)
        return None
    if head[:4] != b'RIFF' or head[8:12] != b'WAVE':
        return None
    pos, fmt, declared = 12, None, None
    while pos + 8 <= len(head):
        cid = head[pos:pos + 4]
        sz = struct.unpack('<I', head[pos + 4:pos + 8])[0]
        if cid == b'fmt ' and pos + 8 + 16 <= len(head):
            fmt = struct.unpack('<HHIIHH', head[pos + 8:pos + 24])
        elif cid == b'data':
            declared = sz
            break
        pos += 8 + sz + (sz & 1)
    if not fmt:
        return None
    _, ch, rate, _, _, bits = fmt
    if not (rate and ch and bits):
        return None
    bytes_per_sec = rate * ch * (bits // 8)
    payload = declared if (declared not in (None, 0, 0xFFFFFFFF)
                           and declared <= size) else max(0, size - 44)
    return {'rate': rate, 'channels': ch, 'bits': bits,
            'seconds': payload / float(bytes_per_sec) if bytes_per_sec else 0,
            'bytes': size}


def asr(file_path, key='', timeout=T_ASR):
    """语音识别 → (text, error)。项目录音是 16 kHz/16 bit/单声道，官方支持。"""
    p = (file_path or '').strip()
    if not p or not os.path.isfile(p):
        return '', '录音文件不存在'
    size = os.path.getsize(p)
    # ⚠ 实测：超 8 MiB 服务端直接断连接（WinError 10054），不返回 413
    if size > ASR_MAX_BYTES:
        return '', '录音文件超过 8 MiB（%.1f MiB）——请缩短录音' % (size / 1048576.0)
    info = wav_info(p)
    if info and info['seconds'] > ASR_MAX_SECONDS:
        return '', ('录音 %.0f 秒，超过 120 秒上限 —— 请缩短' % info['seconds'])
    try:
        with io.open(p, 'rb') as f:      # 同上：不许一行式 open
            data = f.read()
    except Exception as exc:
        _log.warning('读录音失败 %s：%s', p, exc)
        return '', '读录音失败：%s' % exc
    body, ctype = _multipart([], 'file', os.path.basename(p), data,
                             mime='audio/wav')
    status, raw = _request(ASR_URL, body, key, timeout, content_type=ctype)
    if status < 0:
        return '', '网络错误：%s' % raw.decode('utf-8', 'replace')[:160]
    try:
        obj = json.loads(raw.decode('utf-8', 'replace'))
    except Exception as exc:
        _log.warning('ASR 返回不是 JSON：%s', exc)
        return '', '返回不是 JSON：%s' % raw[:160].decode('utf-8', 'replace')
    if isinstance(obj, dict) and obj.get('error'):
        err = obj['error'] if isinstance(obj['error'], dict) else {'message': str(obj['error'])}
        return '', ApiError(status or 400, err.get('message') or '').human()
    if status != 200:
        return '', ApiError(status, '').human()
    return str(obj.get('text') or '').strip(), ''


# ---------------------------------------------------------------- TTS

def tts(text, voice='stella', fmt='wav', filter_markdown=None, key='', timeout=T_TTS):
    """语音合成 → (audio_bytes, content_type, error)

    voice: stella（海星，女声，默认）/ tide（暗潮，男声）
    fmt:   wav / pcm（24 kHz、16 位、单声道）
    """
    t = (text or '').strip()
    if not t:
        return b'', '', '要朗读的文本为空'
    v = (voice or 'stella').strip().lower()
    # 本地先校验：实测传非法音色服务端返 400，白跑一次调用
    if v not in TTS_VOICES:
        return b'', '', '不支持的音色 %r（可选：%s）' % (v, ' / '.join(TTS_VOICES))
    fm = (fmt or 'wav').strip().lower()
    if fm not in TTS_FORMATS:
        return b'', '', '不支持的格式 %r（可选：%s）' % (fm, ' / '.join(TTS_FORMATS))
    billed = sum(2 if '\u4e00' <= ch <= '\u9fff' else 1 for ch in t)
    if billed > TTS_MAX_BILLED_CHARS:
        return b'', '', '文本超过 10,000 计费字符（当前 %d）' % billed
    payload = {'text': t, 'voice_id': v, 'format': fm}
    if filter_markdown is not None:
        payload['filter_markdown'] = bool(filter_markdown)
    status, raw = _request(TTS_URL, json.dumps(payload).encode('utf-8'), key, timeout)
    if status < 0:
        return b'', '', '网络错误：%s' % raw.decode('utf-8', 'replace')[:160]
    if status != 200:
        try:
            obj = json.loads(raw.decode('utf-8', 'replace'))
            err = obj.get('error') if isinstance(obj, dict) else None
            msg = (err or {}).get('message') if isinstance(err, dict) else ''
        except Exception as exc:
            _log.debug('TTS 错误体不是 JSON：%s', exc)
            msg = raw[:160].decode('utf-8', 'replace')
        return b'', '', ApiError(status, msg or '').human()
    return raw, 'audio/wav' if fm == 'wav' else 'audio/pcm', ''


def tts_seconds(wav_bytes):
    """从 WAV 字节算真实时长（不信 data 段头，实测那里是 0xFFFFFFFF）"""
    if not wav_bytes or wav_bytes[:4] != b'RIFF':
        return 0.0
    i = wav_bytes.find(b'data')
    if i < 0:
        return 0.0
    payload = len(wav_bytes) - (i + 8)
    return max(0.0, payload / 48000.0)          # 24 kHz * 16 bit * 1 ch
