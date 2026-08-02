@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem 优先使用独立 Python（NuGet 版常见位置），找不到则用 PATH 里的 pythonw
set "PYW=%LOCALAPPDATA%\Python\pythoncore-3.14-64\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"
start "" "%PYW%" desktop_pet.py
exit
