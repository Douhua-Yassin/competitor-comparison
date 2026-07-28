@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 正在创建 Python 虚拟环境...
  py -m venv .venv
  if errorlevel 1 goto :failed
)
echo 正在安装/检查依赖...
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :failed
echo 正在检查 Playwright Chromium...
.venv\Scripts\python.exe -m playwright install chromium
if errorlevel 1 goto :failed
start "" /b cmd /c "timeout /t 2 /nobreak ^>nul ^& start http://127.0.0.1:8787"
echo 正在启动程序。请勿关闭此窗口；关闭窗口将停止服务。
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8787
goto :end
:failed
echo.
echo 启动失败。请阅读上方错误信息。
pause
:end
endlocal
