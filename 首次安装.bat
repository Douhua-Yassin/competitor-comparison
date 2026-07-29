@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 正在创建 Python 虚拟环境...
  py -m venv .venv
  if errorlevel 1 goto :failed
)
echo 正在安装依赖...
.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto :failed
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :failed
echo.
echo 首次安装完成。
pause
goto :end
:failed
echo.
echo 首次安装失败，请阅读上方错误。
pause
:end
endlocal
