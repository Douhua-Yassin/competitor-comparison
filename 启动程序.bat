@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title Amazon 竞品监控 - 启动中
cd /d "%~dp0"

set "APP_DIR=%~dp0"
set "PY=%APP_DIR%.venv\Scripts\python.exe"
set "PID_FILE=%APP_DIR%data\server.pid"
set "APP_PY=%PY%"
set "APP_ROOT=%APP_DIR%"
set "APP_PID_FILE=%PID_FILE%"

if not exist "%PY%" (
  echo 尚未完成首次安装，请先双击“首次安装.bat”。
  if defined CI exit /b 1
  pause
  exit /b 1
)

call :check_server
if not errorlevel 1 goto :ready

if not exist "data" mkdir "data"
del /q "data\server.log" >nul 2>&1
del /q "data\server-error.log" >nul 2>&1
del /q "%PID_FILE%" >nul 2>&1

set "NO_PROXY=127.0.0.1,localhost"
set "no_proxy=127.0.0.1,localhost"
echo 正在后台启动程序服务...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$arguments='-m uvicorn app.main:app --host 127.0.0.1 --port 8787'; $p=Start-Process -FilePath $env:APP_PY -ArgumentList $arguments -WorkingDirectory $env:APP_ROOT -WindowStyle Hidden -RedirectStandardOutput (Join-Path $env:APP_ROOT 'data\server.log') -RedirectStandardError (Join-Path $env:APP_ROOT 'data\server-error.log') -PassThru; [System.IO.File]::WriteAllText($env:APP_PID_FILE,[string]$p.Id,[System.Text.Encoding]::ASCII)"
if errorlevel 1 goto :failed

for /l %%i in (1,1,45) do (
  call :check_server
  if not errorlevel 1 goto :ready
  if %%i==10 echo 服务仍在启动，请稍候...
  if %%i==25 echo 正在等待首次数据库初始化完成...
  timeout /t 1 /nobreak >nul
)

goto :failed

:check_server
curl.exe --silent --fail --noproxy "*" --max-time 2 http://127.0.0.1:8787/api/status >nul 2>&1
exit /b %errorlevel%

:ready
if defined CI exit /b 0
start "" "http://127.0.0.1:8787"
exit /b 0

:failed
echo.
echo 服务在 45 秒内没有准备完成。
echo 详细错误记录：data\server-error.log
if exist "data\server-error.log" (
  echo.
  echo ===== 最近的错误 =====
  powershell -NoProfile -Command "Get-Content -LiteralPath 'data\server-error.log' -Tail 20"
)
echo.
echo 请运行“故障检查.bat”，不要关闭 Chrome。
if defined CI exit /b 1
pause
exit /b 1
