@echo off
setlocal
pushd "%~dp0"
set "TEMP=%CD%\.tools\tmp"
set "TMP=%TEMP%"
if not exist "%TEMP%" mkdir "%TEMP%"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" danmu.py --gui %*
) else (
  python danmu.py --gui %*
)
set "TASK_EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %TASK_EXIT_CODE%
