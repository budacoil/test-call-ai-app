@echo off
setlocal
cd /d "%~dp0"
call install_windows.bat
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m pip install "pyinstaller>=6"
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onedir --windowed --name SpritePilot --collect-submodules keyring.backends --add-data "spritepilot\assets;spritepilot\assets" --add-data "spritepilot\NOTICE.txt;spritepilot" --add-data "LICENSE;." spritepilot_entry.py
if errorlevel 1 exit /b 1
echo Build complete: dist\SpritePilot\SpritePilot.exe
