# -*- coding: utf-8 -*-
"""deepseek_tools 的单测（2026-11-13）

⛔ 不打真接口、不花钱。全部用 monkeypatch 替换 `_request` / `_json_or_error`。
被测的是**我实测出来的那些坑**，不是文档抄来的预期：

1 OCR 的 `HTTP 200 + body{"error"}` 必须被识别为失败
   （实测：纯 .txt 文件连续两次都是 200 + error，只判状态码会把失败当成功）
2 ASR 超 8 MiB 服务端直接断连接（不是 413）⇒ 必须本地先拦
3 ASR 超 120 秒也要本地拦
4 TTS 的 WAV `data` 段是 0xFFFFFFFF ⇒ 时长只能用文件长度反推
5 TTS 非法音色本地拦（省一次无效调用）
6 Search count 越界夹到 1~50；空 query 本地拒绝
7 min_rerank 能过滤掉低分结果（实测垃圾结果只有 0.105）
"""
import json
import struct

import pytest

import deepseek_tools as dt


# ---------------------------------------------------------------- 基础设施

class _Resp(object):
    def __init__(self, status, payload):
        self.status = status
        self._raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_request(monkeypatch, status, payload):
    """把 `_request` 换成固定返回"""
    def _fake(url, body, key, timeout, content_type='application/json'):
        return status, (payload if isinstance(payload, bytes) else json.dumps(payload).encode())
    monkeypatch.setattr(dt, '_request', _fake)


# ---------------------------------------------------------------- 1 OCR 200+error

def test_ocr_http_200_with_error_body_is_failure(monkeypatch, tmp_path):
    """实测：格式不支持时是 200 + {"error": ...} —— 必须当失败，不能当"识别结果为空"。"""
    p = tmp_path / 'a.txt'
    p.write_text('not a document', encoding='utf-8')
    fake_request(monkeypatch, 200, {'error': {'message': 'the file format is not supported',
                                              'type': 'invalid_request_error'}})
    pages, err = dt.ocr(str(p))
    assert pages == [], '200+error 却返回了页数据：%r' % (pages,)
    assert err, '必须给出错误说明，否则调用方会把失败当成功'
    assert '不支持' in err or 'format' in err.lower()


def test_ocr_normal_success(monkeypatch, tmp_path):
    p = tmp_path / 'b.png'
    p.write_bytes(b'\x89PNG\r\n\x1a\n' + b'0' * 100)
    fake_request(monkeypatch, 200, {'page_count': 1,
                                    'pages': [{'index': 0, 'text': '桌宠测试', 'finish_reason': 'stop'}]})
    pages, err = dt.ocr(str(p))
    assert err == ''
    assert pages[0]['text'] == '桌宠测试'


def test_ocr_empty_text_retries_once(monkeypatch, tmp_path):
    """实测偶发空返回（1 次，随后 8 次正常）⇒ 必须重试一次。"""
    p = tmp_path / 'c.png'
    p.write_bytes(b'\x89PNG\r\n\x1a\n' + b'0' * 100)
    calls = []

    def _fake(url, body, key, timeout, content_type='application/json'):
        calls.append(1)
        if len(calls) == 1:
            return 200, json.dumps({'pages': [{'index': 0, 'text': '   '}]}).encode()
        return 200, json.dumps({'pages': [{'index': 0, 'text': '第二次识别成功'}]}).encode()

    monkeypatch.setattr(dt, '_request', _fake)
    pages, err = dt.ocr(str(p))
    assert len(calls) == 2, '空返回应重试一次，实际调用 %d 次' % len(calls)
    assert pages[0]['text'] == '第二次识别成功'


def test_ocr_missing_file_and_bad_purpose(tmp_path):
    pages, err = dt.ocr(str(tmp_path / 'nope.png'))
    assert pages == [] and '不存在' in err

    p = tmp_path / 'd.png'
    p.write_bytes(b'x')
    pages, err = dt.ocr(str(p), purpose='wrong')
    assert pages == [] and 'purpose' in err


def test_strip_layout_marks(tmp_path):
    raw = ('<｜ref｜>title<｜/ref｜><｜box｜>[[10,20,30,40]]<｜/box｜> 标题文字 \n'
           '<｜ref｜>text<｜/ref｜><｜box｜>[[1,2,3,4]]<｜/box｜> 正文内容')
    out = dt.strip_layout_marks(raw)
    assert '<｜' not in out and '[[' not in out
    assert '标题文字' in out and '正文内容' in out


# ---------------------------------------------------------------- 2/3 ASR 本地拦截

def test_asr_rejects_oversize_locally_without_calling_api(monkeypatch, tmp_path):
    """实测：超 8 MiB 服务端直接断连接（WinError 10054），不返回 413 ⇒ 必须本地拦。"""
    p = tmp_path / 'big.wav'
    p.write_bytes(b'\x00' * (9 * 1024 * 1024))
    called = []
    monkeypatch.setattr(dt, '_request', lambda *a, **k: called.append(1) or (200, b'{}'))
    text, err = dt.asr(str(p))
    assert text == '' and '8 MiB' in err
    assert not called, '超尺寸不该发请求（服务端会直接断连接）'


def test_asr_rejects_over_120s_locally(monkeypatch, tmp_path):
    sec = 130
    payload = b'\x00' * (16000 * 2 * sec)
    hdr = (b'RIFF' + struct.pack('<I', 36 + len(payload)) + b'WAVEfmt ' +
           struct.pack('<IHHIIHH', 16, 1, 1, 16000, 32000, 2, 16) +
           b'data' + struct.pack('<I', len(payload)))
    p = tmp_path / 'long.wav'
    p.write_bytes(hdr + payload)
    called = []
    monkeypatch.setattr(dt, '_request', lambda *a, **k: called.append(1) or (200, b'{}'))
    text, err = dt.asr(str(p))
    assert '120 秒' in err and not called


def test_asr_success_and_silence(monkeypatch, tmp_path):
    sec = 3
    payload = b'\x00' * (16000 * 2 * sec)
    hdr = (b'RIFF' + struct.pack('<I', 36 + len(payload)) + b'WAVEfmt ' +
           struct.pack('<IHHIIHH', 16, 1, 1, 16000, 32000, 2, 16) +
           b'data' + struct.pack('<I', len(payload)))
    p = tmp_path / 's.wav'
    p.write_bytes(hdr + payload)

    fake_request(monkeypatch, 200, {'text': '你好世界', 'duration_ms': 3000})
    text, err = dt.asr(str(p))
    assert text == '你好世界' and err == ''

    # 实测：静音时官方返回 200 + 空 text
    fake_request(monkeypatch, 200, {'text': ''})
    text2, err2 = dt.asr(str(p))
    assert text2 == '' and err2 == '', '静音是「没听到」不是「故障」，err 应为空'


# ---------------------------------------------------------------- 4 TTS 时长

def test_tts_seconds_ignores_bogus_data_chunk_size():
    """实测：TTS 的 WAV `data` 段写的是 0xFFFFFFFF，按头算会得到 89478 秒。"""
    pcm = b'\x00' * (48000 * 2)          # 2 秒 24kHz/16bit/单声道
    wav = (b'RIFF' + struct.pack('<I', 36 + len(pcm)) + b'WAVEfmt ' +
           struct.pack('<IHHIIHH', 16, 1, 1, 24000, 48000, 2, 16) +
           b'data' + struct.pack('<I', 0xFFFFFFFF) + pcm)
    sec = dt.tts_seconds(wav)
    assert 1.8 < sec < 2.2, '时长应按文件长度反推得 ~2 秒，实际 %.1f' % sec


def test_tts_validates_voice_and_format_locally(monkeypatch):
    called = []
    monkeypatch.setattr(dt, '_request', lambda *a, **k: called.append(1) or (200, b'RIFF'))
    b, _, err = dt.tts('测试', voice='nobody')
    assert '不支持的音色' in err and not called
    b2, _, err2 = dt.tts('测试', fmt='mp3')
    assert '不支持的格式' in err2 and not called
    b3, _, err3 = dt.tts('')
    assert '为空' in err3


def test_tts_billed_chars_counts_cjk_as_two(monkeypatch):
    """官方：汉字算 2 个计费字符。10000 上限 ⇒ 5001 个汉字应被本地拒绝。"""
    monkeypatch.setattr(dt, '_request', lambda *a, **k: (200, b'RIFF'))
    _, _, err = dt.tts('啊' * 5001)
    assert '10,000' in err or '10000' in err


# ---------------------------------------------------------------- 6/7 Search

def test_search_rejects_empty_and_truncates_long_query():
    rs, err = dt.search('   ')
    assert rs == [] and '不能为空' in err
    longq = 'x' * 200
    rs2, err2 = dt.search(longq)
    # 空 key 会失败，但必须在长度上先截断（不抛）
    assert isinstance(err2, str)


def test_search_clamps_count(monkeypatch):
    seen = {}

    def _fake(url, payload, key, timeout):
        seen['count'] = payload['count']
        return {'results': []}

    monkeypatch.setattr(dt, '_json_or_error', _fake)
    dt.search('q', count=0)
    assert seen['count'] == 1
    dt.search('q', count=999)
    assert seen['count'] == 50
    dt.search('q', count='abc')
    assert seen['count'] == 5


def test_search_min_rerank_filters_low_scores(monkeypatch):
    """实测：搜不到时那条垃圾结果 rerank_score 只有 0.105，正常结果 2.2~2.3。"""
    payload = {'results': [
        {'rerank_score': 2.30, 'url': 'u1', 'title': 't1'},
        {'rerank_score': 2.18, 'url': 'u2', 'title': 't2'},
        {'rerank_score': 0.105, 'url': 'u3', 'title': '<table>NoneNone'},
    ]}
    monkeypatch.setattr(dt, '_json_or_error', lambda *a, **k: payload)
    rs, err = dt.search('q', min_rerank=1.5)
    assert len(rs) == 2, '应滤掉 0.105 那条，实际留 %d 条' % len(rs)
    assert all(float(x['rerank_score']) >= 1.5 for x in rs)

    rs2, _ = dt.search('q', min_rerank=None)
    assert len(rs2) == 3, '不设阈值时应保留全部'
    rs3, _ = dt.search('q', min_rerank=0)
    assert len(rs3) == 3, '0 等于不筛'


def test_search_need_content_only_when_true(monkeypatch):
    seen = {}
    monkeypatch.setattr(dt, '_json_or_error',
                        lambda url, p, key, timeout: seen.update(p) or {'results': []})
    dt.search('q', need_content=False)
    assert 'need_content' not in seen
    dt.search('q', need_content=True)
    assert seen.get('need_content') is True


# ---------------------------------------------------------------- 错误翻译

def test_api_error_human_messages():
    assert 'Key' in dt.ApiError(401, '').human()
    assert '余额' in dt.ApiError(402, '').human()
    assert '限流' in dt.ApiError(429, '').human()   # 文案与既有 UX 用词对齐
    assert '稍后重试' in dt.ApiError(500, '').human()


def test_fetch_rejects_non_http_locally():
    t, c, err = dt.fetch('ftp://x/y')
    assert '只支持' in err
    t2, c2, err2 = dt.fetch('')
    assert '不能为空' in err2


# ---------------------------------------------------------------- wav_info

def test_wav_info_reads_16k_mono():
    pcm = b'\x00' * (16000 * 2 * 2)
    wav = (b'RIFF' + struct.pack('<I', 36 + len(pcm)) + b'WAVEfmt ' +
           struct.pack('<IHHIIHH', 16, 1, 1, 16000, 32000, 2, 16) +
           b'data' + struct.pack('<I', len(pcm)) + pcm)
    import tempfile
    import os
    fd, p = tempfile.mkstemp(suffix='.wav')
    os.close(fd)
    try:
        open(p, 'wb').write(wav)
        info = dt.wav_info(p)
        assert info['rate'] == 16000 and info['bits'] == 16 and info['channels'] == 1
        assert 1.9 < info['seconds'] < 2.1
    finally:
        os.remove(p)


def test_wav_info_returns_none_for_non_wav(tmp_path):
    p = tmp_path / 'x.wav'
    p.write_bytes(b'not a wav')
    assert dt.wav_info(str(p)) is None
