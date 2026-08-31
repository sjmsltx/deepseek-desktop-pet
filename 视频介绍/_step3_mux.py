# -*- coding: utf-8 -*-
"""step3: 每段视频+语音 mux → concat 完整视频"""
import glob
import os
import subprocess

import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()
OUT = r'E:\ai工作站\desktop-pet\视频介绍'
SEGS = [
    ('seg_01.mp4', '01_开场.mp3'),
    ('seg_02.mp4', '02_项目.mp3'),
    ('seg_03.mp4', '03_双角色.mp3'),
    ('seg_04.mp4', '04_工具.mp3'),
    ('seg_05.mp4', '05_养成.mp3'),
    ('seg_06.mp4', '06_记忆.mp3'),
    ('seg_07.mp4', '07_结尾.mp3'),
]

muxed = []
for vid, aud in SEGS:
    out = os.path.join(OUT, 'mux_' + vid)
    cmd = [FF, '-y', '-hide_banner',
           '-i', os.path.join(OUT, vid), '-i', os.path.join(OUT, aud),
           '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k', '-shortest', out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f'FAIL {vid}: {r.stderr[-300:]}')
        raise SystemExit(1)
    muxed.append(out)
    print(f'mux {vid} + {aud} OK')

# concat 列表
lst = os.path.join(OUT, 'concat.txt')
with open(lst, 'w', encoding='utf-8') as f:
    for m in muxed:
        f.write(f"file '{m}'\n")

final = os.path.join(OUT, 'desktop-pet-介绍视频.mp4')
cmd = [FF, '-y', '-hide_banner', '-f', 'concat', '-safe', '0', '-i', lst,
       '-c:v', 'libx264', '-crf', '20', '-preset', 'medium',
       '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', final]
r = subprocess.run(cmd, capture_output=True, text=True)
if r.returncode != 0:
    print(f'FAIL concat: {r.stderr[-400:]}')
    raise SystemExit(1)

size = os.path.getsize(final) / 1024 / 1024
print(f'✅ 完整视频: {final} ({size:.1f} MB)')
