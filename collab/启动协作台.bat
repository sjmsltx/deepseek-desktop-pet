@echo off
chcp 65001 >nul
cd /d "%~dp0.."
set "PYEXE="
if exist "%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe" set "PYEXE=%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe"
if not defined PYEXE set "PYEXE=python"
if not exist "%TEMP%\collab" mkdir "%TEMP%\collab"
echo 正在启动协作台（演示 provider，不发真实请求；标题不含空格以免参数被拆）...
"%PYEXE%" -u collab\relay_server.py --log "%TEMP%\collab\relay.jsonl" --port 8792 --enable-actions --demo-provider --issue-title DSH面板 --open
pause
