@echo off
setlocal
cd /d "%~dp0"
set PY=.venv\Scripts\python.exe
if not exist "%PY%" set PY=py
echo [1/4] Python 版本
%PY% --version || goto :failed
echo [2/4] requirements 导入检查
%PY% -c "import fastapi,uvicorn,jinja2,openpyxl,playwright,bs4; print('依赖导入正常')" || goto :failed
echo [3/4] 数据库初始化检查
%PY% -c "from app.main import init_db; init_db(); print('数据库初始化正常')" || goto :failed
echo [4/4] 8787 端口占用检查
netstat -ano | findstr ":8787 .*LISTENING" && (echo 警告：8787 端口已被占用) || echo 8787 端口可用
echo 检查完成。
pause
goto :end
:failed
echo 检查失败。
pause
:end
endlocal
