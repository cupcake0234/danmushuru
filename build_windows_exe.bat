@echo off
setlocal
pushd "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv\Scripts\python.exe
  popd
  exit /b 1
)
".venv\Scripts\python.exe" scripts\build_browser_extension.py
if errorlevel 1 (
  popd
  exit /b 1
)
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name DanmuLive --workpath ".tools\pyinstaller-build" --specpath ".tools" --add-data "%CD%\web_actions;web_actions" --add-data "%CD%\browser_extension_ready;browser_extension_ready" --add-data "%CD%\assets;assets" --collect-all dashscope --collect-all pywinauto windows_app.py
set "TASK_EXIT_CODE=%ERRORLEVEL%"
if "%TASK_EXIT_CODE%"=="0" copy /Y "config.local.example.json" "dist\config.local.example.json" >nul
if "%TASK_EXIT_CODE%"=="0" if exist "config.local.json" copy /Y "config.local.json" "dist\config.local.json" >nul
if "%TASK_EXIT_CODE%"=="0" xcopy /E /I /Y "browser_extension_ready" "dist\browser_extension_ready" >nul
popd
exit /b %TASK_EXIT_CODE%
