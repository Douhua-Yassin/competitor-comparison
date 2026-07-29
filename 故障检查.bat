@echo off
chcp 65001 >nul
setlocal
title Amazon 竞品监控 - 故障检查
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"

echo ===== Amazon 竞品监控故障检查 =====
echo.
echo [1/9] Python 与虚拟环境
if exist "%PY%" ("%PY%" --version) else echo 未找到 .venv，请先运行“首次安装.bat”。
echo.
echo [2/9] Python 依赖
if exist "%PY%" "%PY%" -c "import fastapi,uvicorn,jinja2,openpyxl,playwright,bs4; print('依赖导入正常')"
echo.
echo [3/9] 产品输入表
if exist "产品输入表.xlsx" (echo 产品输入表.xlsx 存在) else echo 缺少 产品输入表.xlsx
echo.
echo [4/9] SQLite 数据库
if exist "data\monitor.db" (echo data\monitor.db 存在) else echo 数据库尚未生成，首次启动后会创建。
echo.
echo [5/9] Google Chrome
if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" (echo Chrome 存在：%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe) else echo 未在用户目录找到 Chrome。
echo.
echo [6/9] Chrome Default 配置
if exist "%LOCALAPPDATA%\Google\Chrome\User Data\Default" (echo Default 配置存在) else echo 未找到 Chrome Default 配置。
echo.
echo [7/9] 插件浏览器 9222 端口
powershell -NoProfile -Command "try { $v=Invoke-RestMethod http://127.0.0.1:9222/json/version -TimeoutSec 2; if ($v.Browser -match 'Chrome|Chromium' -and $v.webSocketDebuggerUrl) { Write-Host ('9222 正常：' + $v.Browser) } else { Write-Host '9222 有响应，但不是有效 Chrome 调试接口。' } } catch { Write-Host '9222 未启动，请先运行“启动插件浏览器.bat”。' }"
echo.
echo [8/9] Web 服务 8787 端口
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8787/api/status -TimeoutSec 2; Write-Host ('8787 正常：HTTP ' + $r.StatusCode) } catch { Write-Host '8787 未启动。'; if (Test-Path 'data\server-error.log') { Write-Host '可查看：data\server-error.log' } }"
echo.
echo [9/9] 后台服务 PID
if exist "data\server.pid" (echo server.pid：& type "data\server.pid") else echo 未找到 data\server.pid。
echo.
echo 检查结束。本文件不会抓取商品，也不会修改数据库。
pause
endlocal
