@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    py -3.12 -m venv .venv
    if errorlevel 1 goto failed
)
.venv\Scripts\python.exe -m pip install -e .
if errorlevel 1 goto failed
echo Sprite Pilot dependencies installed. Run start_spritepilot.bat
exit /b 0
:failed
echo Installation failed. Install Python 3.12 x64 with the Python Launcher and retry.
pause
exit /b 1
