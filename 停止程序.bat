@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title Amazon 竞品监控 - 停止程序
cd /d "%~dp0"

set "APP_DIR=%~dp0"
set "PID_FILE=%APP_DIR%data\server.pid"

if not exist "%PID_FILE%" (
  call :notify "没有找到本程序的 server.pid。监控程序可能已经停止；如网页仍可访问，请运行故障检查。"
  exit /b 0
)

set /p SERVER_PID=<"%PID_FILE%"
for /f "delims=0123456789" %%a in ("!SERVER_PID!") do set "INVALID_PID=1"
if defined INVALID_PID (
  echo server.pid 内容无效：!SERVER_PID!
  pause
  exit /b 1
)

set "TARGET_PID=!SERVER_PID!"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$pidValue=[int]$env:TARGET_PID; $process=Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $pidValue); if (-not $process) { exit 2 }; $expected=(Join-Path $env:APP_DIR '.venv').TrimEnd('\'); if ($process.CommandLine -notmatch 'uvicorn\s+app\.main:app') { exit 3 }; if ($process.ExecutablePath -and -not $process.ExecutablePath.StartsWith($expected,[System.StringComparison]::OrdinalIgnoreCase)) { exit 4 }; Stop-Process -Id $pidValue -Force; exit 0" >nul 2>&1
set "STOP_RESULT=!errorlevel!"

if "!STOP_RESULT!"=="0" (
  del /q "%PID_FILE%" >nul 2>&1
  call :notify "监控程序已经停止。Chrome 和卖家精灵仍保持开启。"
  exit /b 0
)

if "!STOP_RESULT!"=="2" (
  del /q "%PID_FILE%" >nul 2>&1
  call :notify "记录的服务进程已经不存在，server.pid 已清理。"
  exit /b 0
)

if "!STOP_RESULT!"=="3" (
  echo 拒绝停止：PID !SERVER_PID! 的命令行不属于本监控程序。
  pause
  exit /b 1
)

if "!STOP_RESULT!"=="4" (
  echo 拒绝停止：PID !SERVER_PID! 不属于当前项目的 .venv。
  pause
  exit /b 1
)

echo 无法停止程序服务，进程号：!SERVER_PID!
pause
exit /b 1

:notify
powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.Windows.Forms; [void][System.Windows.Forms.MessageBox]::Show('%~1','Amazon 竞品监控',[System.Windows.Forms.MessageBoxButtons]::OK,[System.Windows.Forms.MessageBoxIcon]::Information)"
if errorlevel 1 (
  echo %~1
  pause
)
exit /b 0
