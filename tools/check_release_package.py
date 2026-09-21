# -*- coding: utf-8 -*-
"""发布包完整性检查器 —— 把「压缩/打包时不能丢任何东西」钉成机器校验

用法：
    python tools/check_release_package.py <zip 或 dist 目录>
    # 例：python tools/check_release_package.py release_build\\dist\\DeepSeekPet
    #     python tools/check_release_package.py release_build\\DeepSeekPet_v2.9.1_portable.zip

校验三类：
    ① 必须有的运行时资产（与开发目录动态对齐：assets 子目录、plugins 包数）
    ② 必需 Qt 运行时（含图片格式插件，qwebp.dll 必须在——立绘/图片靠它）
    ③ 禁止入包的东西（本地运行状态 / 密钥 / 缓存 / __pycache__）

退出码：0 = 全部通过；1 = 有缺项
"""
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

REQ_FILES = ['ocr_helper.ps1', 'asr_helper.ps1', 'tts_helper.ps1', 'office_probe.ps1',
             '使用说明.txt', 'config.example.json',
             # ★ 2026-09-21 回归护栏（实测教训）：缺 qt.conf 时打包后的 Qt 找不到插件目录
             # （_internal/PySide6/plugins），imageformats/qjpeg.dll 不加载 → 立绘 jpg 被
             # QPixmap 静默解码成 null → 宠物窗口只有透明白底（v2.9.0 发布包实测就是空白，
             # 开发版能直达 site-packages 插件所以看不出来）。
             'qt.conf']
REQ_DIRS = ['assets', 'plugins']
REQ_QT = ['PySide6/QtCore.pyd', 'PySide6/QtWidgets.pyd', 'PySide6/QtGui.pyd',
          'PySide6/QtOpenGLWidgets.pyd', 'shiboken6',
          'PySide6/plugins/platforms', 'PySide6/plugins/imageformats']
REQ_IMAGEFORMAT = 'qwebp.dll'
REQ_IMAGEFORMAT_JPG = 'qjpeg.dll'   # 立绘是 jpg，必须能解（配合 qt.conf）
FORBID = ['logs/', 'memories.json', 'models.json', 'config.json', 'files_cache.json',
          'plugins/_registry.json', 'plugins/_uninstalled', 'plugins/_tmp',
          '__pycache__', '.pytest_cache', '.git/']


def load_source(target):
    """归一化条目集合：抹掉 zip 根目录与 PyInstaller 的 _internal/ 前缀"""
    if target.lower().endswith('.zip'):
        with zipfile.ZipFile(target) as z:
            raw = [n.replace('\\', '/') for n in z.namelist()]
        root = raw[0].split('/')[0] + '/' if raw and '/' in raw[0] else ''
        is_zip = True
    else:
        raw = []
        for dp, dn, fn in os.walk(target):
            for d in dn:
                raw.append(os.path.relpath(os.path.join(dp, d), target).replace('\\', '/') + '/')
            for f in fn:
                raw.append(os.path.relpath(os.path.join(dp, f), target).replace('\\', '/'))
        root, is_zip = '', False
    norm = set()
    for n in raw:
        a = n[len(root):] if (root and n.startswith(root)) else n
        norm.add(a.rstrip('/'))
        if a.startswith('_internal/'):
            norm.add(a[len('_internal/'):].rstrip('/'))
    return norm, is_zip


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    target = sys.argv[1]
    if not os.path.exists(target):
        print('✗ 找不到:', target)
        return 2
    entries, is_zip = load_source(target)

    def has(path):
        p = path.rstrip('/')
        if p in entries:
            return True
        return any(e == p or e.startswith(p + '/') for e in entries)

    ok_all = True
    print('检查目标：%s' % target)
    print('  %s  归一化条目 %d' % ('(zip)' if is_zip else '(目录)', len(entries)))

    print('\n① 必须有的运行时资产')
    for f in REQ_FILES:
        ok = has(f)
        ok_all &= ok
        print('  [%s] %s' % ('✓' if ok else '✗', f))
    dev_assets = os.path.join(ROOT, 'assets')
    dev_subs = sorted(d for d in os.listdir(dev_assets)) if os.path.isdir(dev_assets) else []
    for sub in dev_subs:
        ok = has('assets/%s/' % sub)
        ok_all &= ok
        print('  [%s] assets/%s/   （开发目录有，包里必须有）' % ('✓' if ok else '✗', sub))
    ok = has('assets/live2d/mao/Mao.model3.json')
    ok_all &= ok
    print('  [%s] assets/live2d/mao/Mao.model3.json  （Live2D 模型）' % ('✓' if ok else '✗'))
    dev_plugins = os.path.join(ROOT, 'plugins')
    dev_pkgs = sorted(d for d in os.listdir(dev_plugins)
                      if os.path.isdir(os.path.join(dev_plugins, d)) and not d.startswith('_')) \
        if os.path.isdir(dev_plugins) else []
    missing_pkgs = [d for d in dev_pkgs if not has('plugins/%s/' % d)]
    ok_all &= not missing_pkgs
    print('  [%s] plugins/ 共 %d 个插件目录%s'
          % ('✓' if not missing_pkgs else '✗', len(dev_pkgs),
             '' if not missing_pkgs else '  ✗ 缺: %s' % missing_pkgs))

    print('\n② 必需 Qt 运行时')
    for p in REQ_QT:
        ok = has(p)
        ok_all &= ok
        print('  [%s] %s' % ('✓' if ok else '✗', p))
    img_ok = has('PySide6/plugins/imageformats/%s' % REQ_IMAGEFORMAT)
    ok_all &= img_ok
    print('  [%s] imageformats/%s  （webp 立绘/图片必需）' % ('✓' if img_ok else '✗', REQ_IMAGEFORMAT))
    jpg_ok = has('PySide6/plugins/imageformats/%s' % REQ_IMAGEFORMAT_JPG)
    ok_all &= jpg_ok
    print('  [%s] imageformats/%s  （jpg 立绘必需；要和 qt.conf 一起才真正生效）'
          % ('✓' if jpg_ok else '✗', REQ_IMAGEFORMAT_JPG))

    print('\n③ 禁止入包（作者本地状态 / 密钥 / 缓存）')
    bad = []
    for pat in FORBID:
        p = pat.rstrip('/')
        hit = any(e == p or e.startswith(p + '/') or p in e.split('/') for e in entries)
        if hit:
            bad.append(pat)
            ok_all = False
        print('  [%s] %s' % ('✗ 命中' if hit else '✓ 无', pat))
    if bad:
        print('   ⚠️ 需在打包时排除：%s' % bad)

    print('\n' + '=' * 70)
    print('结论：' + ('✅ 通过（东西没丢、也没多带）' if ok_all else '❌ 不通过（见上面 ✗）'))
    return 0 if ok_all else 1


if __name__ == '__main__':
    sys.exit(main())
