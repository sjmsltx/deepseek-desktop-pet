# -*- coding: utf-8 -*-
"""把 staging 后的包目录压成 zip（并用 Python zipfile 保证中文文件名正确）

为什么不用 tar / Compress-Archive：
    2026-09-20 实测，用 tar 压包会把中文名（使用说明.txt）写成坏编码，
    解压出来是乱码文件名；Python zipfile 写入 UTF-8 标志位，解压正常。
    （tar 的坑已写进 README 打包章节，属于发版流程必须记住的一条。）

用法：
    python tools/zip_portable.py <包目录> [输出 zip 路径]
    # 例：python tools/zip_portable.py release_build\\dist\\DeepSeekPet release_build\\DeepSeekPet_v2.9.1_portable.zip

zip 内结构：顶层为包目录名（DeepSeekPet/…），解压即得可直接运行的文件夹。
"""
import os
import sys
import zipfile


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    src = sys.argv[1].rstrip('\\/')
    if not os.path.isdir(src):
        print('✗ 不是目录: %s' % src)
        return 2
    root_name = os.path.basename(src)
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.path.dirname(src), root_name + '.zip')
    n = 0
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for dp, dn, fn in os.walk(src):
            dn[:] = [d for d in dn if d not in ('__pycache__', '.pytest_cache')]
            for f in fn:
                p = os.path.join(dp, f)
                arc = os.path.join(root_name, os.path.relpath(p, src)).replace('\\', '/')
                z.write(p, arc)
                n += 1
    size = os.path.getsize(out)
    print('✓ 已压包 %s' % out)
    print('  条目 %d · %d 字节 · %.1f MB' % (n, size, size / 1048576))
    # 中文名自检：确认写进去的中文条目能被正确读回
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
    zh = [x for x in names if any(ord(c) > 127 for c in x)]
    print('  中文名条目 %d 个，示例：%s' % (len(zh), zh[:3]))
    bad = [x for x in zh if '\ufffd' in x]
    print('  编码自检：' + ('✓ 正常' if not bad else '✗ 有乱码 %s' % bad[:3]))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
