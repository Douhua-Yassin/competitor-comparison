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

call :check_cdp
if not errorlevel 1 (
  call :notify "插件浏览器已经启动，9222 端口可用。请保持 Chrome 开启。"
  exit /b 0
)

netstat -ano | findstr ":9222 .*LISTENING" >nul
if not errorlevel 1 (
  echo 9222 端口已被占用，但响应的不是有效 Chrome 调试接口。
  echo 请关闭占用 9222 的程序后重试。
  pause
  exit /b 1
)

tasklist /FI "IMAGENAME eq chrome.exe" | find /I "chrome.exe" >nul
if not errorlevel 1 (
  echo 请先保存工作并完全退出所有 Chrome，再重新运行本文件。
  echo 当前 Chrome 没有开启 9222，无法临时追加调试端口。
  pause
  exit /b 1
)

echo 正在使用 Default 登录配置启动 Chrome...
start "" "%CHROME%" --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\Google\Chrome\User Data" --profile-directory=Default

for /l %%i in (1,1,20) do (
  call :check_cdp
  if not errorlevel 1 (
    call :notify "插件浏览器启动成功。请保持 Chrome 开启。"
    exit /b 0
  )
  timeout /t 1 /nobreak >nul
)

echo Chrome 已打开，但 9222 端口没有返回有效的 Chrome 调试信息。
echo 请运行“故障检查.bat”。
pause
exit /b 1

:check_cdp
powershell -NoProfile -Command "try { $v=Invoke-RestMethod http://127.0.0.1:9222/json/version -TimeoutSec 1; if ($v.Browser -match 'Chrome|Chromium' -and $v.webSocketDebuggerUrl) { exit 0 }; exit 1 } catch { exit 1 }" >nul 2>&1
exit /b %errorlevel%

:notify
powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.Windows.Forms; [void][System.Windows.Forms.MessageBox]::Show('%~1','Amazon 竞品监控',[System.Windows.Forms.MessageBoxButtons]::OK,[System.Windows.Forms.MessageBoxIcon]::Information)"
if errorlevel 1 (
  echo %~1
  pause
)
exit /b 0
