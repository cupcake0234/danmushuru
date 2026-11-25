@echo off
setlocal
pushd "%~dp0"
set "TEMP=%CD%\.tools\tmp"
set "TMP=%TEMP%"
set "PIP_CACHE_DIR=%CD%\.tools\cache\pip"
set "UV_CACHE_DIR=%CD%\.tools\cache\uv"
set "PYINSTALLER_CONFIG_DIR=%CD%\.tools\cache"
if not exist "%TEMP%" mkdir "%TEMP%"
set "TASK_APP_NAME=DanmuLive"
if not "%~1"=="" set "TASK_APP_NAME=%~1"
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
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --windowed --name "%TASK_APP_NAME%" --distpath ".tools\portable-dist" --workpath ".tools\pyinstaller-build" --specpath ".tools" --add-data "%CD%\web_actions;web_actions" --add-data "%CD%\browser_extension_ready;browser_extension_ready" --collect-all dashscope --collect-all pywinauto --collect-all sherpa_onnx windows_app.py
set "TASK_EXIT_CODE=%ERRORLEVEL%"
if not "%TASK_EXIT_CODE%"=="0" goto done
if "%~2"=="--stage-only" goto done
xcopy /E /I /Y ".tools\portable-dist\%TASK_APP_NAME%\*" "dist\" >nul
if errorlevel 1 (
  set "TASK_EXIT_CODE=1"
  goto done
)
if "%TASK_EXIT_CODE%"=="0" copy /Y "config.local.example.json" "dist\config.local.example.json" >nul
if "%TASK_EXIT_CODE%"=="0" xcopy /E /I /Y "browser_extension_ready" "dist\browser_extension_ready" >nul
:done
popd
exit /b %TASK_EXIT_CODE%
