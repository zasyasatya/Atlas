@echo off
REM ATLAS launcher for Windows. Double-click this file.
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 goto run
where py >nul 2>nul
if %errorlevel%==0 (
  py run.py %*
  goto end
)
echo Python 3.10+ is required but was not found.
echo Install it from https://python.org/downloads ^(tick "Add Python to PATH"^).
pause
exit /b 1
:run
python run.py %*
:end
if errorlevel 1 pause
