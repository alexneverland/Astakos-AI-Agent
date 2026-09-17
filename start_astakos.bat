@echo off
chcp 65001 >nul
title Astakos AI Agent
cls
echo.
echo  ================================
echo   Astakos AI Agent 🦞 Launcher
echo  ================================
echo.
echo  [1] Full Astakos (Web + selected channel, two safe terminals)
echo  [2] Web Server only
echo  [3] Telegram Bot only (legacy/manual)
echo.
set /p choice=" Choice (1/2/3): "

set "RELOAD_ARGS=--reload --reload-dir api --reload-dir core --reload-dir tools --reload-dir memory --reload-dir services --reload-dir clients --reload-include prompts.md"
set "SERVER_ARGS=--no-access-log"

if "%choice%"=="1" goto full
if "%choice%"=="2" goto web
if "%choice%"=="3" goto telegram

:full
echo.
echo  Starting Web and selected external channel...
cd /d %~dp0
call venv\Scripts\activate
start "Astakos Web Server" cmd /k "cd /d %~dp0 && call venv\Scripts\activate && uvicorn api.server:server --host 0.0.0.0 %SERVER_ARGS% %RELOAD_ARGS%"
timeout /t 3 /nobreak >nul
python run_external.py
goto end

:web
echo.
echo  Starting Web Server only...
cd /d %~dp0
call venv\Scripts\activate
uvicorn api.server:server --host 0.0.0.0 %SERVER_ARGS% %RELOAD_ARGS%
goto end

:telegram
echo.
echo  Starting Telegram Bot...
cd /d %~dp0
call venv\Scripts\activate
python run_telegram.py
goto end

:end
pause
