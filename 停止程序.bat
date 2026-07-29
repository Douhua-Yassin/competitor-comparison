@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title Amazon 竞品监控 - 停止程序

set "SERVER_PID="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8787 .*LISTENING"') do set "SERVER_PID=%%p"

if not defined SERVER_PID (
  call :notify "监控程序当前没有运行。"
  exit /b 0
)

taskkill /PID !SERVER_PID! /F >nul 2>&1
if errorlevel 1 (
  echo 无法停止程序服务，进程号：!SERVER_PID!
  pause
  exit /b 1
)

call :notify "监控程序已经停止。Chrome 和卖家精灵仍保持开启。"
exit /b 0

:notify
powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('%~1','Amazon 竞品监控',[System.Windows.Forms.MessageBoxButtons]::OK,[System.Windows.Forms.MessageBoxIcon]::Information) ^| Out-Null"
if errorlevel 1 (
  echo %~1
  pause
)
exit /b 0
