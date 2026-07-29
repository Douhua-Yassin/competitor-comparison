@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title Amazon 竞品监控 - 启动中
cd /d "%~dp0"

set "APP_DIR=%~dp0"
set "PY=%APP_DIR%.venv\Scripts\python.exe"
set "PID_FILE=%APP_DIR%data\server.pid"

if not exist "%PY%" (
  echo 尚未完成首次安装，请先双击“首次安装.bat”。
  pause
  exit /b 1
)

powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8787/api/status -TimeoutSec 1; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; exit 1" >nul 2>&1
if not errorlevel 1 goto :ready

if not exist "data" mkdir "data"
del /q "data\server.log" >nul 2>&1
del /q "data\server-error.log" >nul 2>&1
del /q "%PID_FILE%" >nul 2>&1

echo 正在后台启动程序服务...
set "APP_PY=%PY%"
set "APP_ROOT=%APP_DIR%"
for /f "usebackq delims=" %%p in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$arguments='-m uvicorn app.main:app --host 127.0.0.1 --port 8787'; $p=Start-Process -FilePath $env:APP_PY -ArgumentList $arguments -WorkingDirectory $env:APP_ROOT -WindowStyle Hidden -RedirectStandardOutput (Join-Path $env:APP_ROOT 'data\server.log') -RedirectStandardError (Join-Path $env:APP_ROOT 'data\server-error.log') -PassThru; $p.Id"`) do set "SERVER_PID=%%p"

if not defined SERVER_PID goto :failed
echo !SERVER_PID!>"%PID_FILE%"

for /l %%i in (1,1,60) do (
  powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8787/api/status -TimeoutSec 1; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; exit 1" >nul 2>&1
  if not errorlevel 1 goto :ready
  timeout /t 1 /nobreak >nul
)

goto :failed

:ready
start "" "http://127.0.0.1:8787"
exit /b 0

:failed
if defined SERVER_PID taskkill /PID !SERVER_PID! /F >nul 2>&1
del /q "%PID_FILE%" >nul 2>&1
echo.
echo 服务启动失败，请运行“故障检查.bat”。
echo 详细错误记录：data\server-error.log
pause
exit /b 1
