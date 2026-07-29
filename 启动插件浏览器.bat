@echo off
chcp 65001 >nul
setlocal
title Amazon 竞品监控 - 插件浏览器

set "CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"

if not exist "%CHROME%" (
  echo 未找到 Google Chrome。
  pause
  exit /b 1
)

netstat -ano | findstr ":9222 .*LISTENING" >nul
if not errorlevel 1 (
  call :notify "插件浏览器已经启动，9222 端口可用。请保持 Chrome 开启。"
  exit /b 0
)

tasklist /FI "IMAGENAME eq chrome.exe" | find /I "chrome.exe" >nul
if not errorlevel 1 (
  echo 请先保存工作并完全退出所有 Chrome，再重新运行本文件。
  echo 当前 Chrome 没有开启 9222，无法临时追加调试端口。
  pause
  exit /b 1
)

echo 正在使用 Default 登录配置启动 Chrome...
start "" "%CHROME%" --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\Google\Chrome\User Data" --profile-directory=Default

for /l %%i in (1,1,20) do (
  powershell -NoProfile -Command "try { Invoke-RestMethod http://127.0.0.1:9222/json/version -TimeoutSec 1 ^| Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
  if not errorlevel 1 (
    call :notify "插件浏览器启动成功。请保持 Chrome 开启。"
    exit /b 0
  )
  timeout /t 1 /nobreak >nul
)

echo Chrome 已打开，但 9222 端口没有响应。
echo 请运行“故障检查.bat”。
pause
exit /b 1

:notify
powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('%~1','Amazon 竞品监控',[System.Windows.Forms.MessageBoxButtons]::OK,[System.Windows.Forms.MessageBoxIcon]::Information) ^| Out-Null"
if errorlevel 1 (
  echo %~1
  pause
)
exit /b 0
