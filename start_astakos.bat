@echo off
chcp 65001 >nul
title Astakos AI Agent
cls
echo.
echo  ================================
echo   Astakos AI Agent 🦞 Launcher
echo  ================================
echo.
echo  [1] Web Server (uvicorn)
echo  [2] Telegram Bot
echo  [3] Both
echo.
set /p choice=" Choice (1/2/3): "

set "RELOAD_ARGS=--reload --reload-dir api --reload-dir core --reload-dir tools --reload-dir memory --reload-dir services --reload-dir clients --reload-include prompts.md"
set "SERVER_ARGS=--no-access-log"

if "%choice%"=="1" goto web
if "%choice%"=="2" goto telegram
if "%choice%"=="3" goto both

:web
echo.
echo  Starting Web Server...
cd /d C:\astakos_v2
call venv\Scripts\activate
uvicorn api.server:server %SERVER_ARGS% %RELOAD_ARGS%
goto end

:telegram
echo.
echo  Starting Telegram Bot...
cd /d C:\astakos_v2
call venv\Scripts\activate
python run_telegram.py
goto end

:both
echo.
echo  Starting both services...
cd /d C:\astakos_v2
call venv\Scripts\activate
start "Astakos Web Server" cmd /k "cd /d C:\astakos_v2 && call venv\Scripts\activate && uvicorn api.server:server %SERVER_ARGS% %RELOAD_ARGS%"
timeout /t 3 /nobreak >nul
python run_telegram.py
goto end

:end
pause
