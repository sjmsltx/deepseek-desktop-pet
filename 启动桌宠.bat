@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 优先使用独立 Python（NuGet 版常见位置），找不到则用 PATH 里的 pythonw
set "PYW=%LOCALAPPDATA%\Python\pythoncore-3.14-64\pythonw.exe"
rem 2026-10-31：某些调用环境里 %LOCALAPPDATA% 是空的（实测 AutoClaw 的 shell 就是），
rem 那样第一行会拼成 "\Python\...\pythonw.exe" 直接找不到。用 USERPROFILE 兜一层。
if not exist "%PYW%" set "PYW=%USERPROFILE%\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"

rem 2026-10-31（PC-268 的教训）：清掉 PYTHONUSERBASE。
rem 它会把 %APPDATA%\...\toolchain\python 塞进 sys.path 的**前面**，
rem 于是同一个 import 可能来自另一个环境 —— 268 那次「所有声线固定为一个」
rem 就是因为运行时加载的 edge_tts 与打包产物不一致，查错方向耗了整轮。
rem 桌宠只该用自己那套 Python 的包，环境变量一概不继承。
set "PYTHONUSERBASE="

start "" "%PYW%" desktop_pet.py
exit
