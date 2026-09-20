# -*- coding: utf-8 -*-
"""
技能包（skill pack）规范与安装器 —— v6.67 / Batch 3-1
============================================================
定位：**在现有 plugin_manager 之上补三件事**，不另起一套插件系统（复用 > 创造）。

现有系统已具备：plugins/<name>/plugin.json（元数据）+ plugin.py（实现）、五类
tool/menu/rules/theme/skill、加载与分发、JSON/ast/危险关键词三道闸、install/uninstall 工具通道。

本模块补的三件事：
  ① **权限声明**（manifest.permissions：类别 → 人类可读理由）—— 安装时确认、未确认不启用
  ② **打包与校验**（目录 / zip / GitHub 三种来源；schema 校验 + 目录穿越防护 + 体积/文件数上限 + 哈希登记）
  ③ **可管理**（启用/禁用、来源与版本登记 _registry.json、卸载进停放区而不是直接删）

清单文件沿用 `plugin.json`（不迁移、不换名），新增字段全部可选 —— v1 插件照旧可用。

权限分级（安全模型的关键）：
  - FOREVER_FORBIDDEN：无论如何都拒绝（eval/exec/os.system/winreg/ctypes.windll/pyautogui…）
  - PERMISSION_GATED：代码里出现才需要声明对应权限（subprocess/os.remove/urllib 等）
  - 声明了 ≠ 放行：安装时列出让使用者确认；写类操作运行时仍可二次确认（由调用方决定）
"""
import ast
import hashlib
import json
import os
import re
import shutil
import time
import zipfile

MANIFEST_NAME = 'plugin.json'
REGISTRY_NAME = '_registry.json'
PARK_DIR = '_uninstalled'          # 卸载的包移到这里，而不是 rmtree 直接删除
PARK_KEEP = 5                      # 停放区保留最近 N 个
MAX_ZIP_BYTES = 5 * 1024 * 1024    # 单个技能包上限 5 MB
MAX_FILES = 200                    # 包内文件数上限
ALLOWED_EXTS = ('.py', '.json', '.md', '.txt', '.html', '.css', '.png', '.jpg', '.jpeg',
                '.svg', '.csv', '.tsv', '.yaml', '.yml')
NAME_RE = re.compile(r'[A-Za-z0-9_-]{1,32}')

# ---- 永不放行：破坏性 / 自修改 / 绕过沙箱 ----
FOREVER_FORBIDDEN = [
    'os.system', 'eval(', 'exec(', 'compile(', '__import__',
    'winreg', 'ctypes.windll', 'SendKeys', 'pyautogui', 'shutil.rmtree',
    'os.kill', 'ctypes.CDLL', 'pickle.loads', 'marshal.loads',
]
# ---- 需要声明权限才允许出现（类别 → 关键词）----
PERMISSION_GATED = {
    'process': ['subprocess', 'os.popen', 'os.startfile', 'os.exec', 'os.spawn'],
    'files.write': ['os.remove', 'os.unlink', 'os.rmdir', 'os.replace', 'shutil.move', 'shutil.copy'],
    'network': ['urllib.request', 'requests.get', 'requests.post', 'http.client', 'socket.socket'],
}
# v6.69：v2 技能包（非 builtin）**不允许直接 import 网络库**，必须走 pet_net 统一入口
# —— 否否则出网白名单管不住（同进程拦不了 import）。
DIRECT_NET_PATTERNS = ('urllib.request', 'requests.get', 'requests.post', 'requests.Session',
                       'http.client', 'socket.socket', 'aiohttp', 'httpx')

# ---- v6.71：文件读写 API 也必须声明权限（关键词判据里没有 open()，实测零权限包能任意读写文件）----
# 这些用 AST 精确识别（见 file_api_permissions），不用字符串匹配
FILE_WRITE_APIS = {
    'os.remove', 'os.unlink', 'os.rmdir', 'os.rename', 'os.replace', 'os.makedirs',
    'os.mkdir', 'os.removedirs', 'os.truncate', 'os.chmod', 'os.symlink', 'os.link',
    'shutil.move', 'shutil.copy', 'shutil.copy2', 'shutil.copyfile', 'shutil.copytree',
    'shutil.rmtree', 'tempfile.mkstemp', 'tempfile.mkdtemp',
}
FILE_READ_APIS = {'os.read', 'io.open'}
# 只按**方法名后缀**判定这几个：Path.write_text() 之类。
# 注意不能收 replace/rename/chmod —— str.replace、DataFrame.rename 会同名误报。
FILE_WRITE_METHODS = ('write_text', 'write_bytes', 'writelines', 'unlink', 'rmdir', 'mkdir', 'touch',
                      'to_csv', 'to_excel', 'to_json', 'to_pickle', 'to_parquet',
                      'savefig', 'imwrite', 'imsave')
FILE_READ_METHODS = ('read_text', 'read_bytes', 'readlines',
                     'read_csv', 'read_excel', 'read_json', 'read_pickle', 'read_parquet', 'imread')

# ---- 权限类别词表（类别 → (显示名, 说明)）----
PERMISSIONS = {
    'files.read': ('读文件', '读取你电脑上的文件（技能只应读你指定的目录）'),
    'files.write': ('写/删文件', '创建、修改或删除文件（含把结果写到 输出/ 目录）'),
    'office.com': ('驱动办公软件', '通过 WPS / Microsoft Office 的 COM 接口操作表格与文档'),
    'network': ('联网', '访问网络（下载数据、调用外部服务）'),
    'process': ('启动其他程序', '运行外部命令或程序'),
    'audio': ('声音/麦克风', '播放语音或使用麦克风'),
    'clipboard': ('剪贴板', '读写你的剪贴板'),
    'ai.calls': ('调用模型', '调用 AI 模型（会产生费用）'),
}
REQUIRED_FIELDS = ('type',)
KNOWN_TYPES = ('tool', 'menu', 'rules', 'theme', 'skill')


# ----------------------------------------------------------------- 校验

def validate_manifest(meta, name_hint=None):
    """校验并规范化 manifest。返回 (ok, msg, normalized_meta)

    兼容 v1：旧插件只有 name/type/entry 也能过；新字段（permissions 等）全是可选。
    """
    if not isinstance(meta, dict):
        return False, 'manifest 必须是 JSON 对象', None
    meta = dict(meta)
    name = str(meta.get('name') or name_hint or '').strip()
    if not NAME_RE.fullmatch(name):
        return False, '技能包名只能含字母/数字/下划线/连字符（≤32 字符）', None
    meta['name'] = name
    for f in REQUIRED_FIELDS:
        if not meta.get(f):
            return False, 'manifest 缺少必填字段 %s（可选值：%s）' % (f, '/'.join(KNOWN_TYPES)), None
    if meta['type'] not in KNOWN_TYPES:
        return False, '未知类型 %s（可选：%s）' % (meta['type'], '/'.join(KNOWN_TYPES)), None
    perms = meta.get('permissions')
    if perms is not None and not isinstance(perms, dict):
        return False, 'permissions 必须是对象：{"权限类别": "申请理由"}', None
    for cat in (perms or {}):
        if cat not in PERMISSIONS:
            return False, '未知权限类别「%s」（可选：%s）' % (cat, '、'.join(PERMISSIONS)), None
    entry = meta.get('entry')
    if entry:
        entry = str(entry).strip()
        if os.path.isabs(entry) or '..' in entry.replace('\\', '/').split('/'):
            return False, 'entry 只能是包内相对路径，不允许 ../ 或绝对路径', None
        if not entry.lower().endswith('.py'):
            return False, 'entry 只允许 .py 文件', None
        meta['entry'] = entry
    for key, maxlen in (('description', 500), ('title', 60), ('author', 60),
                        ('version', 32), ('homepage', 200), ('license', 40),
                        ('min_pet_version', 32)):
        if meta.get(key) is not None:
            meta[key] = str(meta[key])[:maxlen]
    # builtin=true → 随程序一起发布的官方包（由作者授予所声明权限，不需要现场确认）
    if meta.get('builtin') is not None:
        meta['builtin'] = bool(meta['builtin'])
    meta.setdefault('version', '1.0.0')
    meta.setdefault('title', name)
    meta.setdefault('enabled', True)
    return True, '', meta


def _dotted_name(node):
    """把 ast.Call 的 func 还原成点号名（open / os.remove / p.write_text）；认不出来返回 ''"""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return ''
    parts.append(node.id)
    return '.'.join(reversed(parts))


def file_api_permissions(src):
    """静态判定：这段代码用到了哪些文件读写能力 → {'files.read'} / {'files.write'}

    为什么要有这个（v6.71）：关键词判据 PERMISSION_GATED 里没有 open()，
    实测「声明零权限」的技能包可以直接读 config.json（里面有使用者的 API key）、
    还能覆盖程序目录里的文件。这里改用 AST 精确识别，并且：
      · open() 按 mode 区分读/写（'w'/'a'/'x'/'+' → 写）
      · Path 上的 write_text/read_text 之类按方法名后缀判定
      · 不收 replace/rename/chmod —— str.replace 之类同名方法会误报
    """
    needs = set()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return needs
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = _dotted_name(func)
        # 接收者本身是表达式时（如 Path('a').write_text）dotted 名解析不出来，
        # 这时只用方法名（attr）去判：否则这类写法会漏掉。
        attr = func.attr if isinstance(func, ast.Attribute) else ''
        if not name and not attr:
            continue
        base = attr or name.rsplit('.', 1)[-1]
        if name == 'open' or base == 'open':
            mode = ''
            if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                mode = str(node.args[1].value)
            for kw in node.keywords:
                if kw.arg == 'mode' and isinstance(kw.value, ast.Constant):
                    mode = str(kw.value.value)
            needs.add('files.write' if any(c in mode for c in 'wax+') else 'files.read')
        elif name in FILE_WRITE_APIS:
            needs.add('files.write')
        elif name in FILE_READ_APIS:
            needs.add('files.read')
        elif base in FILE_WRITE_METHODS:
            needs.add('files.write')
        elif base in FILE_READ_METHODS:
            needs.add('files.read')
    return needs


def scan_code(src, declared=None, strict=True, builtin=False):
    """静态扫描入口代码。返回 (ok, msg, needed_permissions)

    strict=True（manifest_version ≥ 2）：永禁关键词 + 分级关键词需声明权限 + 文件 API 需声明权限
    strict=False（v1 老插件）：只拦永禁，不做权限分级 —— 保证已有插件不被新规误伤
    builtin=True（随程序自带的官方包）：允许直连网络库（出网白名单依然在运行时生效）
    """
    declared = set(declared or [])
    try:
        ast.parse(src)
    except SyntaxError as e:
        return False, 'Python 语法错误：%s' % e, set()
    for pat in FOREVER_FORBIDDEN:
        if pat in src:
            return False, '代码含永禁操作「%s」，任何权限都不放行' % pat, set()
    needed = set()
    for cat, pats in PERMISSION_GATED.items():
        for pat in pats:
            if pat in src:
                needed.add(cat)
                break
    if not strict:
        return True, '', needed          # v1 老插件：只拦永禁
    # v6.71：文件读写 API 也要声明权限（关键词判据漏了 open()）
    fneed = file_api_permissions(src)
    if 'files.write' in fneed:
        needed.add('files.write')        # 写/覆盖 → 必须声明 files.write
    if 'files.read' in fneed and not ({'files.read', 'files.write'} & declared):
        needed.add('files.read')         # 只读 → 声明 files.read 或 files.write 都能过
    missing = needed - declared
    if missing:
        return False, ('代码用到了 %s，但 manifest 没声明权限：%s'
                       % ('、'.join(sorted(missing)),
                          '；'.join('%s（%s）' % (c, PERMISSIONS[c][0]) for c in sorted(missing)))), needed
    # 出网必须走统一入口，否则白名单无效（v6.69）
    if 'network' in declared and not builtin:
        for pat in DIRECT_NET_PATTERNS:
            if pat in src:
                return False, ('不要直接 import 网络库（%s）——请改用 pet_net：\n'
                               '    import pet_net\n'
                               "    data, err = pet_net.http_get('https://…')\n"
                               '这样出网白名单才管得住。' % pat), needed
    return True, '', needed


def check_dir_name(rel):
    """zip 内路径安全校验：禁止绝对路径、../、盘符"""
    if not rel or rel.startswith('/') or rel.startswith('\\'):
        return False
    if re.match(r'^[A-Za-z]:', rel):
        return False
    parts = [p for p in rel.replace('\\', '/').split('/') if p not in ('', '.')]
    return '..' not in parts


# ----------------------------------------------------------------- 哈希 / 登记

def dir_hash(root):
    """对包内文件内容算稳定哈希（用于登记来源，便于发现包被改过）"""
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in sorted(dirnames) if not d.startswith('__')]
        for fn in sorted(filenames):
            if fn.endswith('.pyc'):
                continue
            fp = os.path.join(dirpath, fn)
            rel = os.path.relpath(fp, root).replace('\\', '/')
            h.update(rel.encode('utf-8'))
            try:
                with open(fp, 'rb') as f:
                    h.update(f.read())
            except Exception:
                pass
    return h.hexdigest()[:16]


def read_registry(plugins_dir):
    fp = os.path.join(plugins_dir, REGISTRY_NAME)
    try:
        with open(fp, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_registry(plugins_dir, data):
    fp = os.path.join(plugins_dir, REGISTRY_NAME)
    try:
        with open(fp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def _register(plugins_dir, name, info):
    reg = read_registry(plugins_dir)
    reg[name] = info
    write_registry(plugins_dir, reg)


# ----------------------------------------------------------------- 安装

def _install_tree(src_dir, plugins_dir, meta, granted=None, source='dir'):
    """把已校验好的包内容装进 plugins/<name>/，写登记，返回 (ok, msg)"""
    name = meta['name']
    dst = os.path.join(plugins_dir, name)
    declared = sorted((meta.get('permissions') or {}).keys())
    granted = sorted(set(granted or []))
    pending = [c for c in declared if c not in granted]
    meta = dict(meta)
    if pending:
        # 未确认权限 → 先落地但禁用，确认后再启用（绝不默认放行）
        meta['enabled'] = False
    try:
        if os.path.isdir(dst):
            shutil.rmtree(dst)          # 覆盖安装：先清旧的
        shutil.copytree(src_dir, dst)
        with open(os.path.join(dst, MANIFEST_NAME), 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception as e:
        return False, '写入失败：%s' % e
    _register(plugins_dir, name, {
        'version': meta.get('version', '1.0.0'),
        'source': source,
        'installed_at': int(time.time()),
        'hash': dir_hash(dst),
        'declared': declared,
        'granted': granted,
        'pending': pending,
        'enabled': bool(meta.get('enabled', True)),
    })
    if pending:
        return True, ('技能包 %s 已装入，但需要你确认权限才启用：%s（确认后启用）'
                      % (name, '、'.join('%s %s' % (c, PERMISSIONS[c][0]) for c in pending)))
    return True, '技能包 %s 已安装并启用' % name


def install_from_dir(src_dir, plugins_dir, granted=None, source='dir'):
    """从本地目录安装（目录里必须有 plugin.json）"""
    src_dir = os.path.abspath(src_dir)
    mpath = os.path.join(src_dir, MANIFEST_NAME)
    if not os.path.isfile(mpath):
        return False, '目录里没有 %s' % MANIFEST_NAME, None
    try:
        with open(mpath, 'r', encoding='utf-8-sig') as f:
            meta = json.load(f)
    except Exception as e:
        return False, '%s 不是合法 JSON：%s' % (MANIFEST_NAME, e), None
    ok, msg, meta = validate_manifest(meta, name_hint=os.path.basename(src_dir))
    if not ok:
        return False, msg, None
    if meta.get('entry'):
        epath = os.path.join(src_dir, meta['entry'])
        if not os.path.isfile(epath):
            return False, '声明的入口文件不存在：%s' % meta['entry'], None
        with open(epath, 'r', encoding='utf-8') as f:
            src = f.read()
        ok, msg, _ = scan_code(src, (meta.get('permissions') or {}).keys(),
                               builtin=bool(meta.get('builtin')))
        if not ok:
            return False, msg, None
    os.makedirs(plugins_dir, exist_ok=True)
    ok, msg = _install_tree(src_dir, plugins_dir, meta, granted, source)
    return ok, msg, meta['name']


def _extract_zip(zf, tmp):
    """安全解压：路径穿越 / 文件数 / 体积三重防护"""
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > MAX_FILES:
        return '包内文件数 %d 超过上限 %d' % (len(infos), MAX_FILES)
    total = 0
    for i in infos:
        if not check_dir_name(i.filename):
            return '包内含非法路径：%s' % i.filename
        if os.path.splitext(i.filename)[1].lower() not in ALLOWED_EXTS:
            return '包内含不允许的文件类型：%s' % i.filename
        total += i.file_size
    if total > MAX_ZIP_BYTES:
        return '解包后体积 %.1f MB 超过上限 %.1f MB' % (total / 1048576, MAX_ZIP_BYTES / 1048576)
    zf.extractall(tmp)
    return ''


def _find_pack_root(tmp):
    """zip 里可能多包一层目录（GitHub 的 owner-repo-ref/），自动找到含 manifest 的那层"""
    if os.path.isfile(os.path.join(tmp, MANIFEST_NAME)):
        return tmp
    for entry in sorted(os.listdir(tmp)):
        sub = os.path.join(tmp, entry)
        if os.path.isdir(sub) and os.path.isfile(os.path.join(sub, MANIFEST_NAME)):
            return sub
    return None


def install_from_zip(zip_path, plugins_dir, granted=None, source='zip', tmp_root=None):
    """从本地 zip 安装"""
    if not os.path.isfile(zip_path):
        return False, '找不到 zip：%s' % zip_path, None
    if os.path.getsize(zip_path) > MAX_ZIP_BYTES:
        return False, 'zip 超过 %d MB 上限' % (MAX_ZIP_BYTES // 1048576), None
    tmp_root = tmp_root or os.path.join(plugins_dir, '_tmp')
    tmp = os.path.join(tmp_root, 'unzip_%d' % int(time.time() * 1000))
    try:
        os.makedirs(tmp, exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            err = _extract_zip(zf, tmp)
            if err:
                return False, err, None
        root = _find_pack_root(tmp)
        if root is None:
            return False, '包里没有 %s（技能包根目录应放清单文件）' % MANIFEST_NAME, None
        ok, msg, name = install_from_dir(root, plugins_dir, granted, source)
        return ok, msg, name
    except zipfile.BadZipFile:
        return False, '不是合法的 zip 文件', None
    except Exception as e:
        return False, '安装失败：%s' % e, None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def github_zip_url(repo, ref=None, subdir=None):
    """owner/repo（或完整 URL）→ codeload zip 地址（纯函数，便于测试）"""
    repo = str(repo or '').strip()
    m = re.search(r'github\.com/([^/]+)/([^/#?]+)', repo)
    if m:
        owner, name = m.group(1), m.group(2)
    else:
        parts = repo.strip('/').split('/')
        if len(parts) < 2:
            return None
        owner, name = parts[0], parts[1]
    name = re.sub(r'\.git$', '', name)
    ref = ref or 'main'
    return 'https://codeload.github.com/%s/%s/zip/refs/heads/%s' % (owner, name, ref)


def install_from_github(repo, plugins_dir, ref=None, granted=None, fetch=None, subdir=None):
    """从 GitHub 仓库安装。fetch 可注入（测试用），默认 urllib 下载到临时文件。"""
    url = github_zip_url(repo, ref, subdir)
    if not url:
        return False, '看不懂的仓库地址（应为 owner/repo 或 GitHub URL）', None
    tmp_root = os.path.join(plugins_dir, '_tmp')
    os.makedirs(tmp_root, exist_ok=True)
    zpath = os.path.join(tmp_root, 'dl_%d.zip' % int(time.time() * 1000))
    try:
        if fetch is None:
            import urllib.request
            with urllib.request.urlopen(url, timeout=30) as r:
                data = r.read(MAX_ZIP_BYTES + 1)
        else:
            data = fetch(url)
        if not data:
            return False, '下载失败（空内容）', None
        if len(data) > MAX_ZIP_BYTES:
            return False, '下载内容超过 %d MB 上限' % (MAX_ZIP_BYTES // 1048576), None
        with open(zpath, 'wb') as f:
            f.write(data)
        ok, msg, name = install_from_zip(zpath, plugins_dir, granted, source='github:%s' % url)
        if ok and subdir:
            pass
        return ok, msg, name
    except Exception as e:
        return False, '下载/安装失败：%s' % e, None
    finally:
        try:
            os.remove(zpath)
        except Exception:
            pass


# ----------------------------------------------------------------- 管理

def set_enabled(plugins_dir, name, flag):
    """启用/禁用（改 manifest + 登记；调用方负责热加载 scan()）"""
    pdir = os.path.join(plugins_dir, str(name))
    mpath = os.path.join(pdir, MANIFEST_NAME)
    if not os.path.isfile(mpath):
        return False, '技能包 %s 不存在' % name
    reg = read_registry(plugins_dir).get(str(name)) or {}
    pending = list(reg.get('pending') or [])
    if flag and pending:
        return False, ('还不能启用：需要先确认权限 —— %s'
                       % '、'.join('%s %s' % (c, PERMISSIONS.get(c, ('', ''))[0]) for c in pending))
    try:
        with open(mpath, 'r', encoding='utf-8-sig') as f:
            meta = json.load(f)
        meta['enabled'] = bool(flag)
        with open(mpath, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception as e:
        return False, '写入失败：%s' % e
    reg['enabled'] = bool(flag)
    _register(plugins_dir, str(name), reg)
    return True, '技能包 %s 已%s' % (name, '启用' if flag else '禁用')


def grant_permissions(plugins_dir, name, granted):
    """确认权限：登记授权列表；若声明的权限都确认了，则自动解除 pending（需调用方再启用）"""
    name = str(name)
    reg = read_registry(plugins_dir).get(name)
    if not reg:
        return False, '技能包 %s 不在登记表里' % name
    have = set(reg.get('granted') or [])
    have |= {c for c in (granted or []) if c in PERMISSIONS}
    declared = set(reg.get('declared') or [])
    reg['granted'] = sorted(have)
    reg['pending'] = sorted(declared - have)
    _register(plugins_dir, name, reg)
    if reg['pending']:
        return True, '已确认部分权限，还需确认：%s' % '、'.join(reg['pending'])
    return True, '权限已全部确认，可以启用 %s 了' % name


def uninstall(plugins_dir, name, keep=PARK_KEEP):
    """卸载 = 移进停放区（可恢复），而不是直接删除"""
    name = str(name)
    src = os.path.join(plugins_dir, name)
    if not os.path.isdir(src):
        return False, '技能包 %s 不存在' % name
    park = os.path.join(plugins_dir, PARK_DIR)
    os.makedirs(park, exist_ok=True)
    dst = os.path.join(park, '%s-%s' % (name, time.strftime('%Y%m%d-%H%M%S')))
    try:
        shutil.move(src, dst)
    except Exception as e:
        return False, '卸载失败：%s' % e
    reg = read_registry(plugins_dir)
    reg.pop(name, None)
    write_registry(plugins_dir, reg)
    # 停放区只留最近 keep 个
    try:
        items = sorted([d for d in os.listdir(park) if os.path.isdir(os.path.join(park, d))])
        for old in items[:-keep] if len(items) > keep else []:
            shutil.rmtree(os.path.join(park, old), ignore_errors=True)
    except Exception:
        pass
    return True, '技能包 %s 已卸载（可在 plugins\\%s 找回）' % (name, PARK_DIR)


def list_packs(plugins_dir):
    """列出技能包（含登记信息、权限状态）—— 给管理界面用"""
    out, reg = [], read_registry(plugins_dir)
    if not os.path.isdir(plugins_dir):
        return out
    for entry in sorted(os.listdir(plugins_dir)):
        if entry.startswith('_'):
            continue
        pdir = os.path.join(plugins_dir, entry)
        mpath = os.path.join(pdir, MANIFEST_NAME)
        if not os.path.isfile(mpath):
            continue
        try:
            with open(mpath, 'r', encoding='utf-8-sig') as f:
                meta = json.load(f)
        except Exception:
            continue
        r = reg.get(entry) or {}
        declared = sorted((meta.get('permissions') or {}).keys())
        granted = sorted(r.get('granted') or [])
        pending = sorted(r.get('pending') or [])
        if not r and declared and not meta.get('builtin'):
            pending = declared          # 手工塞进来、没登记的：也得先确认
        # ★ 有效状态：待确认权限的包**根本没加载**，不能按清单里的 enabled=true 报“启用”
        want_on = bool(meta.get('enabled', True))
        state = '待确认权限' if pending else ('启用' if want_on else '已禁用')
        out.append({
            'name': entry,
            'title': meta.get('title') or entry,
            'type': meta.get('type'),
            'version': r.get('version') or meta.get('version', '1.0.0'),
            'source': r.get('source') or ('builtin' if meta.get('builtin') else 'manual'),
            'enabled': want_on and not pending,
            'state': state,
            'declared': declared,
            'granted': granted,
            'pending': pending,
            'hash': r.get('hash', ''),
            'installed_at': r.get('installed_at'),
            'permissions_text': '；'.join('%s（%s）' % (PERMISSIONS[c][0], (meta.get('permissions') or {}).get(c, ''))
                                          for c in declared) or '未声明特殊权限',
        })
    return out


def permissions_card(plugins_dir, name):
    """安装前给使用者看的权限卡片文本（AI 通道与管理界面共用）"""
    mpath = os.path.join(plugins_dir, str(name), MANIFEST_NAME)
    if not os.path.isfile(mpath):
        return ''
    try:
        with open(mpath, 'r', encoding='utf-8-sig') as f:
            meta = json.load(f)
    except Exception:
        return ''
    perms = meta.get('permissions') or {}
    lines = ['技能包 %s（%s）申请以下权限：' % (meta.get('title') or name, meta.get('version', '')),
             '来源：%s' % meta.get('author', '未知'),
             '说明：%s' % (meta.get('description', '') or '—')]
    if not perms:
        lines.append('· 未声明特殊权限（仍受永禁规则约束）')
    for cat, why in perms.items():
        label, desc = PERMISSIONS.get(cat, (cat, ''))
        lines.append('· %s —— %s【%s】' % (label, why or desc, cat))
    lines.append('确认后才会启用；随时可在设置里禁用或卸载。')
    return '\n'.join(lines)
