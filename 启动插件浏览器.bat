@echo off
setlocal
chcp 65001 >nul
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
  echo ========================================
  echo 插件浏览器已经启动。
  echo 9222 端口可用，可以直接运行监控程序。
  echo ========================================
  pause
  exit /b 0
)
tasklist /FI "IMAGENAME eq chrome.exe" | find /I "chrome.exe" >nul
if not errorlevel 1 (
  echo 请先完全退出当前 Chrome。
  echo 当前 Chrome 没有开启 9222，无法追加调试端口。
  pause
  exit /b 1
)
echo 正在使用 Default 登录配置启动 Chrome...
start "" "%CHROME%" --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\Google\Chrome\User Data" --profile-directory=Default
for /l %%i in (1,1,20) do (
  powershell -NoProfile -Command "try { Invoke-RestMethod http://127.0.0.1:9222/json/version -TimeoutSec 1 ^| Out-Null; exit 0 } catch { exit 1 }"
  if not errorlevel 1 (
    echo 插件浏览器启动成功。
    echo 请保持 Chrome 开启。
    pause
    exit /b 0
  )
  timeout /t 1 /nobreak >nul
)
echo Chrome 已打开，但 9222 端口没有响应。
echo 请运行“故障检查.bat”。
pause
exit /b 1
