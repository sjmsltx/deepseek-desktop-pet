# -*- coding: utf-8 -*-
"""官方技能包：文件整理（file_organize）
=============================================
设计原则（为什么这样做）：
- **先预览、后执行**：run 必须显式带 confirm=true —— 动用户真实文件是不可逆操作，
  不给"看一眼就动手"的机会最稳。
- **只在指定目录内操作**：不动目录以外的任何东西，不做递归删除。
- **重复文件只报告不删除**：删除交给用户自己决定（避免"善意删掉别人的东西"）。
"""
import hashlib
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

MAX_SCAN = 3000
TYPE_DIRS = {
    '图片': ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tif', '.tiff', '.svg'),
    '文档': ('.doc', '.docx', '.pdf', '.txt', '.md', '.rtf', '.odt', '.wps'),
    '表格': ('.xls', '.xlsx', '.csv', '.et', '.tsv'),
    '演示': ('.ppt', '.pptx', '.dps'),
    '音视频': ('.mp3', '.wav', '.mp4', '.mkv', '.avi', '.mov', '.flac', '.m4a'),
    '压缩包': ('.zip', '.rar', '.7z', '.tar', '.gz'),
    '程序': ('.exe', '.msi', '.bat', '.ps1', '.py', '.js', '.jar'),
}


def _resolve(src):
    s = str(src or '').strip().strip('"')
    if not s:
        return ''
    return s if os.path.isabs(s) else os.path.join(BASE, s)


def _scan(src):
    """列目录顶层文件（不递归），跳过已归类的子文件夹"""
    out = []
    for name in sorted(os.listdir(src)):
        p = os.path.join(src, name)
        if os.path.isfile(p) and not name.startswith('.'):
            out.append(p)
        if len(out) >= MAX_SCAN:
            break
    return out


def _bucket(path, by='type'):
    ext = os.path.splitext(path)[1].lower()
    if by == 'date':
        try:
            return time.strftime('%Y-%m', time.localtime(os.path.getmtime(path)))
        except Exception:
            return '未知日期'
    for name, exts in TYPE_DIRS.items():
        if ext in exts:
            return name
    return '其他'


def organize_files(args):
    args = args or {}
    action = str(args.get('action') or 'preview').strip().lower()
    src = _resolve(args.get('src'))
    if not src or not os.path.isdir(src):
        return '请给一个存在的文件夹路径（src）。'
    files = _scan(src)
    if not files:
        return '这个文件夹顶层没有文件可整理（子文件夹不动）。'

    by = str(args.get('by') or 'type').strip().lower()
    by = 'date' if by.startswith('date') else 'type'

    if action in ('preview', 'run'):
        plan = {}
        for f in files:
            plan.setdefault(_bucket(f, by), []).append(os.path.basename(f))
        lines = ['%s（共 %d 个文件）：' % ('整理计划' if action == 'preview' else '整理结果', len(files))]
        for k in sorted(plan):
            lines.append('  %s/ ← %d 个：%s%s'
                         % (k, len(plan[k]), '、'.join(plan[k][:6]),
                            ' …' if len(plan[k]) > 6 else ''))
        if action == 'preview':
            lines.append('（预览不改动任何文件；确认后我再用 confirm=true 执行）')
            return '\n'.join(lines)
        if not args.get('confirm'):
            return ('要真动文件必须显式确认：请用户同意后，再带 confirm=true 调用。\n'
                    '当前是预览：\n' + '\n'.join(lines[1:]))
        moved, failed = 0, 0
        for k, names in plan.items():
            d = os.path.join(src, k)
            try:
                os.makedirs(d, exist_ok=True)
            except Exception:
                failed += len(names)
                continue
            for n in names:
                try:
                    os.rename(os.path.join(src, n), os.path.join(d, n))
                    moved += 1
                except Exception:
                    failed += 1
        lines.append('已移动 %d 个%s' % (moved, ('，%d 个失败（可能被占用）' % failed) if failed else ''))
        return '\n'.join(lines)

    if action == 'dupes':
        seen, dupes = {}, []
        for f in files:
            try:
                h = hashlib.md5()
                with open(f, 'rb') as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b''):
                        h.update(chunk)
                d = h.hexdigest()
                if d in seen:
                    dupes.append((os.path.basename(seen[d]), os.path.basename(f)))
                else:
                    seen[d] = f
            except Exception:
                continue
        if not dupes:
            return '没有发现内容相同的重复文件（按 MD5 比对，共查 %d 个）。' % len(files)
        lines = ['发现 %d 组重复（按内容 MD5 比对，**没有删除任何东西**）：' % len(dupes)]
        for a, b in dupes[:20]:
            lines.append('  %s  ==  %s' % (a, b))
        lines.append('要删哪个由你决定；我可以用命令删指定文件。')
        return '\n'.join(lines)

    if action == 'rename':
        prefix = str(args.get('prefix') or '').strip()
        if not prefix:
            return '请给 rename 的前缀（prefix）。'
        if not args.get('confirm'):
            return '重命名会改动文件名，需要用户同意后带 confirm=true 再执行。'
        made, failed = 0, 0
        for i, f in enumerate(files, 1):
            ext = os.path.splitext(f)[1]
            dst = os.path.join(os.path.dirname(f), '%s_%03d%s' % (prefix, i, ext))
            if os.path.abspath(dst) == os.path.abspath(f):
                continue
            try:
                os.rename(f, dst)
                made += 1
            except Exception:
                failed += 1
        return '已重命名 %d 个%s' % (made, ('，%d 个失败' % failed) if failed else '')

    return '未知 action：%s（可用：preview / run / dupes / rename）' % action
