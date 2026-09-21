# -*- coding: utf-8 -*-
"""便携包 staging —— 把「运行期需要、但 PyInstaller 不会自动带」的东西拷进出包目录

为什么必须有这一步（2026-09-20 实测）：
    只跑 PyInstaller 得到的包缺 assets / 插件 / ps1 辅助脚本 / 说明文件，
    双击运行会出现「没有立绘、没有技能、语音与 OCR 不可用」。
    代码里素材路径是写死的：BASE_DIR/assets/live2d/mao/... —— 而 spec 里 datas=[]，
    所以 assets 必须靠本脚本拷到 exe 旁边。

用法：
    python tools/stage_portable.py <包目录>
    # 例：python tools/stage_portable.py release_build\\dist\\DeepSeekPet

自动行为：
    ① 先清除本地运行期/私密文件（logs / memories.json / models.json / config.json 等）
       —— 发出去的包绝不能带作者的运行记录与记忆
    ② 拷 assets/（含 live2d 模型）与 plugins/（只带技能包本体，跳过 _registry/_uninstalled/_tmp）
    ③ 拷 4 个 .ps1 辅助脚本 + 使用说明.txt + config.example.json + models.json.example
    ④ 打出自检：包内文件数/体积 + 运行期残留是否清零
"""
import os
import shutil
import sys

# 项目根 = tools/ 的上一级（路径自适应，换机器/换盘都能跑）
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DIRS = ['assets']
FILES = ['ocr_helper.ps1', 'tts_helper.ps1', 'asr_helper.ps1', 'office_probe.ps1',
         '使用说明.txt', 'config.example.json', 'models.json.example']
PLUGIN_SKIP = ('_registry.json', '_uninstalled', '_tmp', '__pycache__')
# 本地运行期数据（隐私）：绝不随包发出
RUNTIME_JUNK = ('logs', 'memories.json', 'models.json', 'config.json',
                'files_cache.json', 'holidays_cache.json')


def stage(dst_root, log=print):
    os.makedirs(dst_root, exist_ok=True)

    for junk in RUNTIME_JUNK:
        p = os.path.join(dst_root, junk)
        if os.path.isdir(p):
            shutil.rmtree(p)
            log('  ⌫ 清除运行期目录 %s' % junk)
        elif os.path.isfile(p):
            os.remove(p)
            log('  ⌫ 清除运行期文件 %s（含使用者数据，不能随包发）' % junk)

    for d in DIRS:
        src, dst = os.path.join(ROOT, d), os.path.join(dst_root, d)
        if not os.path.isdir(src):
            log('  ✗ 缺目录 %s（源：%s）' % (d, src))
            continue
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        log('  ✓ %-14s %d 文件' % (d, sum(len(fs) for _, _, fs in os.walk(dst))))

    src_plugins = os.path.join(ROOT, 'plugins')
    dst_plugins = os.path.join(dst_root, 'plugins')
    if os.path.isdir(src_plugins):
        os.makedirs(dst_plugins, exist_ok=True)
        for name in sorted(os.listdir(src_plugins)):
            if name in PLUGIN_SKIP or name.startswith('_'):
                continue
            s, d = os.path.join(src_plugins, name), os.path.join(dst_plugins, name)
            if os.path.isdir(s):
                if os.path.isdir(d):
                    shutil.rmtree(d)
                shutil.copytree(s, d, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
                log('  ✓ plugins/%-16s' % name)

    for f in FILES:
        src = os.path.join(ROOT, f)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(dst_root, f))
            log('  ✓ %s' % f)
        else:
            log('  ✗ %s 在项目根找不到（自检会因此不通过）' % f)

    # ★ qt.conf —— 2026-09-21 实测教训（便携包立绘一片空白的根因）
    #   本包布局是「exe 在根、依赖在 _internal/」，打包后的 exe 里 Qt 找不到插件目录
    #   （_internal/PySide6/plugins）→ imageformats/qjpeg.dll 不加载 → 立绘 jpg 被
    #   QPixmap 静默解码成 null → 宠物窗口只有透明白底（v2.9.0 发布包同样如此，
    #   开发版因为能直接找到 site-packages 里的插件所以正常）。
    #   实测：只放这一个 qt.conf，立绘即恢复（宠物区域彩色像素 0% → 62~85%）。
    qt_conf = os.path.join(dst_root, 'qt.conf')
    with open(qt_conf, 'w', encoding='ascii', newline='\n') as fh:
        fh.write('[Paths]\nPrefix = _internal\nPlugins = PySide6/plugins\n')
    log('  ✓ qt.conf（Qt 插件路径；缺它立绘不显示）')


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    target = sys.argv[1]
    print('staging → %s' % target)
    stage(target)
    total = sum(len(fs) for _, _, fs in os.walk(target))
    size = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(target) for f in fs)
    left = [j for j in RUNTIME_JUNK if os.path.exists(os.path.join(target, j))]
    print('包内合计 : %d 文件 / %.1f MB' % (total, size / 1048576))
    print('运行期残留自检 :', left or '无 ✓（可发）')
    return 1 if left else 0


if __name__ == '__main__':
    sys.exit(main())
