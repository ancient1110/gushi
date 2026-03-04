@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [INFO] 未检测到虚拟环境，正在创建 .venv ...
  py -3 -m venv .venv 2>nul || python -m venv .venv
)

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] 无法创建虚拟环境，请先安装 Python 3。
  pause
  exit /b 1
)

echo [INFO] 正在安装/更新依赖...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] 依赖安装失败，请检查网络或代理设置。
  pause
  exit /b 1
)

echo [INFO] 启动图形界面...
".venv\Scripts\python.exe" launch_gui.py

pause
endlocal
