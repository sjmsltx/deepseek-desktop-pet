# -*- coding: utf-8 -*-
"""recycle_box.py — 送回收站（**只走回收站，绝不直接删**）

为什么单独一个模块
------------------
这是桌宠里唯一会「动用户真实文件」的地方。把它隔离成小文件，
便于单独审计与测试，也让 review 时一眼能看完整个破坏性面。

⛔ 本模块**只允许**出现 SHFileOperationW + FOF_ALLOWUNDO 这一种删除方式。
   禁止 os.remove / os.unlink / shutil.rmtree / send2trash
   —— 有测试（test_no_direct_delete_in_recycle_module）逐个字符串盯着。

API 选型依据（2026-11-01 用临时文件实测，不是查文档推的）
----------------------------------------------------------
    ctypes + SHFileOperationW + FOF_ALLOWUNDO
        → rc=0，文件从原位置消失，回收站条目 +1，
          且能在 $Recycle.Bin\\<SID>\\ 下找到原内容（$R 前缀文件）
    **同一个 API 但不加 FOF_ALLOWUNDO**（对照实验）
        → rc=0，文件被**永久删除**，回收站条目不变
        ⇒ 这条对照证明「进回收站」确实是 ALLOWUNDO 带来的，
          不是我的测量方法看不出「删了」和「回收了」的差别
    不存在的路径 → rc=2（有错误码，不是静默成功）
    send2trash → 本机未安装，且桌宠是打包分发，不能让用户装依赖 ⇒ 不采用

安全边界
--------
1. 只处理**文件**，不处理文件夹（Owner 原话是「文件」；保守解释）
2. 拒绝系统目录 / 程序目录 / 桌宠自身目录（防自毁、防搞坏系统）
3. 拒绝网络路径（UNC）—— 回收站对 UNC 的行为不一致，不值得冒险
4. 每次调用把**实际做了什么**返回给调用方，由调用方写审计
"""
import ctypes
import ctypes.wintypes as wt
import logging
import os

_log = logging.getLogger('pet.recycle')

#: SHFileOperation 的 wFunc
FO_DELETE = 3
#: 进回收站（不加它 = 永久删除，实测已验证）
FOF_ALLOWUNDO = 0x0040
FOF_NOCONFIRMATION = 0x0010
FOF_SILENT = 0x0004
FOF_NOERRORUI = 0x0400

#: 绝对不许动的目录（小写、绝对路径）。命中即拒。
_PROTECTED = (
    r'c:\windows',
    r'c:\program files',
    r'c:\program files (x86)',
    r'c:\programdata',
    r'c:\$recycle.bin',
    r'c:\system volume information',
)


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ('hwnd', wt.HWND),
        ('wFunc', wt.UINT),
        ('pFrom', wt.LPCWSTR),
        ('pTo', wt.LPCWSTR),
        ('fFlags', ctypes.c_uint16),
        ('fAnyOperationsAborted', wt.BOOL),
        ('hNameMappings', ctypes.c_void_p),
        ('lpszProgressTitle', wt.LPCWSTR),
    ]


def _api():
    """返回 SHFileOperationW（带 argtypes）；不可用时返回 None"""
    try:
        fn = ctypes.windll.shell32.SHFileOperationW
        fn.argtypes = [ctypes.POINTER(_SHFILEOPSTRUCTW)]
        fn.restype = ctypes.c_int
        return fn
    except Exception as exc:
        _log.warning('SHFileOperationW 不可用：%s', exc)
        return None


def recycle_available():
    """本机能不能送回收站（非 Windows / API 缺失 → False）"""
    return _api() is not None


def human_size(n):
    """人类可读的大小（确认框里要让人知道要动多大）"""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return '?'
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024 or unit == 'TB':
            return ('%d %s' % (n, unit)) if unit == 'B' else ('%.1f %s' % (n, unit))
        n /= 1024.0
    return '%.1f TB' % n


def _own_dir():
    return os.path.dirname(os.path.abspath(__file__))


def refuse_reason(path):
    """判断这个路径为什么不能送回收站。可以送 → 返回 ''。

    所有理由都要能说给用户听（确认框和气泡会用到），
    不要返回 'invalid' 这种没法解释的码。
    """
    try:
        p = os.path.abspath(str(path))
    except Exception as exc:
        _log.warning('路径无法解析（%r），按拒绝处理：%s', path, exc)
        return '路径无法解析'

    if not os.path.exists(p):
        return '文件不存在'

    if os.path.isdir(p):
        # Owner 原话是「文件」；文件夹体积/语义都不适合「吃掉」
        return '文件夹不处理（只吃文件）'

    # 网络路径：回收站对 UNC 的行为不一致，不值得冒险
    if p.startswith('\\\\'):
        return '网络路径不处理'

    low = p.lower()
    for bad in _PROTECTED:
        if low == bad or low.startswith(bad + os.sep):
            return '系统目录不处理'

    own = _own_dir().lower()
    if low == own or low.startswith(own + os.sep):
        return '桌宠自己的目录不处理（防自毁）'

    return ''


def recycle_paths(paths, confirm_all=None):
    """把若干**文件**送进回收站。

    Args:
        paths: 路径列表
        confirm_all: 可选回调 (list_of_paths) -> bool。
                     在**所有规则检查通过之后、真正动手之前**调用一次 ——
                     整批只确认一次（3 个文件弹 3 个框是在折磨用户）。
                     本函数不做 UI，弹窗由调用方负责。

    Returns:
        (ok, err)
            ok:  [(path, 'recycle')]
            err: [(path, 拒绝或失败原因)]
        两个列表分开返回 —— 调用方要能把「被规则拒绝」和「API 失败」区分开。
    """
    ok, err = [], []
    if not paths:
        return ok, err

    fn = _api()
    if fn is None:
        for p in paths:
            err.append((p, '本机不支持回收站 API'))
        return ok, err

    # ---- 第一步：规则过滤（不通过的直接记原因，不进确认）----
    valid = []
    for p in paths:
        why = refuse_reason(p)
        if why:
            err.append((p, why))
        else:
            valid.append(p)
    if not valid:
        return ok, err

    # ---- 第二步：整批确认一次 ----
    if confirm_all is not None:
        try:
            agreed = bool(confirm_all(list(valid)))
        except Exception as exc:
            _log.warning('确认回调出错，按取消处理：%s', exc)
            agreed = False
        if not agreed:
            for p in valid:
                err.append((p, '用户取消'))
            return ok, err

    # ---- 第三步：逐个送回收站 ----
    for p in valid:
        # pFrom 必须双 null 结尾（多路径时这块最容易写错）
        buf = ctypes.create_unicode_buffer(str(p) + '\0\0')
        op = _SHFILEOPSTRUCTW()
        op.hwnd = None
        op.wFunc = FO_DELETE
        op.pFrom = ctypes.cast(buf, wt.LPCWSTR)
        op.pTo = None
        op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
        op.fAnyOperationsAborted = False
        try:
            rc = fn(ctypes.byref(op))
        except Exception as exc:
            _log.warning('SHFileOperationW 调用异常（%s）：%s', p, exc)
            err.append((p, '调用异常：%s' % exc))
            continue

        if rc != 0:
            # 常见码：2 = 文件不存在 / 0x7C = 路径无效
            err.append((p, 'API 返回错误码 %d' % rc))
            continue
        if op.fAnyOperationsAborted:
            err.append((p, '操作被中止'))
            continue
        if os.path.exists(str(p)):
            # 极端情况：返回 0 但文件还在 —— 不当作成功，免得用户以为已经回收
            err.append((p, '调用成功但文件仍在原处'))
            continue

        ok.append((p, 'recycle'))

    return ok, err
