@echo off
chcp 65001 >nul
cd /d "%~dp0.."
set "PYEXE="
if exist "%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe" set "PYEXE=%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe"
if not defined PYEXE for %%P in (python.exe) do set "PYEXE=%%~$PATH:P"
if not defined PYEXE set "PYEXE=python"
set "LOG=%TEMP%\collab\relay.jsonl"
if not exist "%TEMP%\collab" mkdir "%TEMP%\collab"
echo 正在启动协作台（演示 provider，不发真实请求）...
"%PYEXE%" collab\relay_server.py --log "%LOG%" --port 8792 --enable-actions --demo-provider --issue-title "把桌宠的 DSH 面板做成什么样" --open
pause
