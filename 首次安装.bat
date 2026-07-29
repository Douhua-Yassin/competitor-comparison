@echo off
chcp 65001 >nul
setlocal
title Amazon 竞品监控 - 首次安装
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo 正在创建 Python 虚拟环境...
  py -m venv .venv
  if errorlevel 1 goto :failed
)

echo 当前 Python 版本：
.venv\Scripts\python.exe --version
if errorlevel 1 goto :failed

echo.
echo 正在安装程序依赖...
.venv\Scripts\python.exe -m pip install --disable-pip-version-check --no-cache-dir -r requirements.txt
if errorlevel 1 goto :failed

echo.
echo 首次安装完成。
echo 以后日常使用时，只需运行“启动插件浏览器.bat”和“启动程序.bat”。
if defined CI exit /b 0
pause
goto :end

:failed
echo.
echo 首次安装失败，请阅读上方错误信息。
if defined CI exit /b 1
pause

:end
endlocal
