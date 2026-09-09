@echo off
chcp 65001 >nul
set "PYTHON_EXE=C:\Users\15693\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "GUI_FILE=%~dp0settings_gui.py"
if not exist "%PYTHON_EXE%" (
  echo 未找到系统运行环境，请联系 Codex 重新配置。
  pause
  exit /b 1
)
if not exist "%GUI_FILE%" (
  echo 未找到配置窗口文件。请不要单独下载这个 CMD 文件，请运行项目文件夹中的版本。
  pause
  exit /b 1
)
"%PYTHON_EXE%" "%GUI_FILE%"
if errorlevel 1 (
  echo.
  echo 配置窗口启动失败，请将上面的错误截图发给 Codex。
  pause
)
