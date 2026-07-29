@echo off
chcp 65001 >nul
setlocal
title Amazon 竞品监控 - 启动中
cd /d "%~dp0"

set "APP_DIR=%~dp0"
set "PY=%APP_DIR%.venv\Scripts\python.exe"

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

echo 正在后台启动程序服务...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$arguments='-m uvicorn app.main:app --host 127.0.0.1 --port 8787'; Start-Process -FilePath $env:PY -ArgumentList $arguments -WorkingDirectory $env:APP_DIR -WindowStyle Hidden -RedirectStandardOutput (Join-Path $env:APP_DIR 'data\server.log') -RedirectStandardError (Join-Path $env:APP_DIR 'data\server-error.log')"
if errorlevel 1 goto :failed

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
echo.
echo 服务启动失败，请运行“故障检查.bat”。
echo 详细错误记录：data\server-error.log
pause
exit /b 1
