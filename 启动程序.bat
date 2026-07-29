@echo off
setlocal
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo 尚未完成首次安装，请先双击“首次安装.bat”。
  pause
  exit /b 1
)
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8787/api/status -TimeoutSec 1; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; exit 1"
if not errorlevel 1 goto :ready
start "Amazon 竞品价格监控" cmd /k .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8787
for /l %%i in (1,1,60) do (
  powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8787/api/status -TimeoutSec 1; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; exit 1"
  if not errorlevel 1 goto :ready
  timeout /t 1 /nobreak >nul
)
echo 服务启动失败，请运行“故障检查.bat”。
pause
exit /b 1
:ready
start "" http://127.0.0.1:8787
exit /b 0
