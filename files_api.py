# -*- coding: utf-8 -*-
"""files_api.py — DeepSeek Files API（图片复用，v6.62）
=====================================================

官方：`POST /files`（multipart，purpose=user_data）上传后拿到 `file-api-…` 的 id，
之后消息里可直接用 `{'type': 'file', 'file_id': …}` 引用，不必每次重发 base64。

实测（2026-09-19）：上传 → 用 file_id 提问 → 模型正确读出了图里的文字；`GET /files/{id}`
可查状态，`DELETE /files/{id}` 可清理，`GET /files` 可列已上传文件。

本模块提供上传/查询/删除 + **本地哈希缓存**：同一张图（内容相同）只上传一次，
重复提问直接复用 file_id。缓存文件与桌宠其它数据同级（files_cache.json）。

失败一律回退：调用方拿到 (None, error) 时改用 base64 直发，不让图片白丢。
"""
import hashlib
import json
import mimetypes
import os
import urllib.error
import urllib.request

from pet_log import get_logger

_log = get_logger('files_api')

MULTIPART_BOUNDARY = '----desktop-pet-upload-2f8c1d'
MAX_UPLOAD_BYTES = 64 * 1024 * 1024      # 官方单文件上限 64 MiB
DEFAULT_EXPIRE_DAYS = 7                  # 官方可设 1h~30d；这里保守取 7 天


def file_sha256(path):
    """文件内容哈希（决定“是否同一张图”）"""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _multipart_body(path):
    """按官方格式拼 multipart 请求体：purpose=user_data + file"""
    name = os.path.basename(path)
    ctype = mimetypes.guess_type(name)[0] or 'application/octet-stream'
    with open(path, 'rb') as f:
        data = f.read()
    parts = [
        ('--%s\r\nContent-Disposition: form-data; name="purpose"\r\n\r\nuser_data\r\n'
         % MULTIPART_BOUNDARY).encode(),
        ('--%s\r\nContent-Disposition: form-data; name="file"; filename="%s"\r\n'
         'Content-Type: %s\r\n\r\n' % (MULTIPART_BOUNDARY, name, ctype)).encode(),
        data,
        ('\r\n--%s--\r\n' % MULTIPART_BOUNDARY).encode(),
    ]
    return b''.join(parts), 'multipart/form-data; boundary=%s' % MULTIPART_BOUNDARY


def upload_file(api_key, path, base_url='', timeout=120):
    """上传单个文件，返回 (file_id, error)"""
    key = (api_key or '').strip()
    if not key:
        return None, '未配置 API Key'
    try:
        size = os.path.getsize(path)
    except Exception as e:
        return None, '文件不可读：%s' % e
    if size > MAX_UPLOAD_BYTES:
        return None, '文件超过官方 64 MiB 上限'
    from api_stats import ApiStats                       # 复用地址归一（避免拼出 404 路径）
    url = ApiStats.normalize_base(base_url) + '/files'
    try:
        body, ctype = _multipart_body(path)
        req = urllib.request.Request(
            url, data=body, method='POST',
            headers={'Authorization': 'Bearer ' + key, 'Content-Type': ctype,
                     'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode('utf-8'))
        fid = (data or {}).get('id')
        return (fid, None) if fid else (None, '响应缺少 id 字段')
    except urllib.error.HTTPError as e:
        return None, 'HTTP %s %s' % (e.code, e.read().decode('utf-8', 'ignore')[:120])
    except Exception as e:
        return None, '%s: %s' % (type(e).__name__, str(e)[:120])


def get_file(api_key, file_id, base_url='', timeout=30):
    """查询上传文件信息，返回 (dict|None, error)"""
    from api_stats import ApiStats
    url = '%s/files/%s' % (ApiStats.normalize_base(base_url), file_id)
    try:
        req = urllib.request.Request(url, headers={
            'Authorization': 'Bearer ' + (api_key or '').strip(), 'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8')), None
    except Exception as e:
        return None, '%s: %s' % (type(e).__name__, str(e)[:120])


def delete_file(api_key, file_id, base_url='', timeout=30):
    """删除上传文件，返回 (是否成功, error)"""
    from api_stats import ApiStats
    url = '%s/files/%s' % (ApiStats.normalize_base(base_url), file_id)
    try:
        req = urllib.request.Request(url, method='DELETE', headers={
            'Authorization': 'Bearer ' + (api_key or '').strip()})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status in (200, 204), None
    except Exception as e:
        return False, '%s: %s' % (type(e).__name__, str(e)[:120])


class FilesCache:
    """本地 file_id 缓存：同一张图只上传一次（按内容哈希）"""

    def __init__(self, path):
        self.path = path
        self.items = {}
        self.load()

    def load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self.items = data
        except Exception as e:
            _log.debug('files 缓存读取失败：%s', e)
            self.items = {}

    def save(self):
        try:
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.items, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
            return True
        except Exception as e:
            _log.debug('files 缓存写入失败：%s', e)
            return False

    def get(self, digest):
        item = self.items.get(digest) or {}
        fid = item.get('file_id')
        return fid or None

    def put(self, digest, file_id, name=''):
        self.items[digest] = {'file_id': file_id, 'name': str(name)[:80]}
        self.save()

    def drop(self, digest):
        if digest in self.items:
            self.items.pop(digest, None)
            self.save()


def ensure_file_id(api_key, path, base_url='', cache=None):
    """确保这张图有可复用的 file_id。返回 (file_id, error)。

    已缓存 → 直接复用；未缓存 → 上传后写缓存。失败返回 (None, error)，调用方回退 base64。
    """
    digest = None
    try:
        digest = file_sha256(path)
        if cache is not None:
            fid = cache.get(digest)
            if fid:
                return fid, None
    except Exception as e:
        _log.debug('哈希失败（改用直接上传）：%s', e)
    fid, err = upload_file(api_key, path, base_url)
    if fid:
        if cache is not None and digest:
            cache.put(digest, fid, os.path.basename(path))
        return fid, None
    return None, err


def build_content_via_files(text, paths, api_key, base_url='', cache=None, max_images=4):
    """用 Files API 构造 user content（与 vision_helper.build_vision_content 同形态）。

    返回 (content, used, errors)：used=0 时调用方回退 base64 直发。
    """
    paths = [p for p in (paths or []) if p and os.path.isfile(str(p))]
    if not paths:
        return text, 0, []
    parts = []
    if text:
        parts.append({'type': 'text', 'text': text})
    used, errors = 0, []
    for p in paths[:max_images]:
        fid, err = ensure_file_id(api_key, p, base_url, cache)
        if fid:
            parts.append({'type': 'file', 'file_id': fid})
            used += 1
        else:
            errors.append('%s：%s' % (os.path.basename(str(p)), err))
    if not used:
        return text, 0, errors
    return parts, used, errors
