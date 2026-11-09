@echo off
setlocal
cd /d "%~dp0"
if not exist .venv (
    python -m venv .venv || exit /b 1
    .venv\Scripts\pip install -r requirements.txt || exit /b 1
)
.venv\Scripts\pip install -q pyarmor || exit /b 1
if exist build_obf rmdir /s /q build_obf
.venv\Scripts\pyarmor gen -O build_obf\src src\main.py src\config.py src\vision.py src\controller.py src\state_machine.py src\anti_afk.py src\mode_b.py || exit /b 1
.venv\Scripts\pyinstaller --noconsole --onefile --name pk-auto ^
  --paths build_obf\src ^
  --hidden-import pyarmor_runtime_000000 ^
  --hidden-import config --hidden-import anti_afk --hidden-import controller ^
  --hidden-import state_machine --hidden-import vision --hidden-import mode_b --hidden-import math ^
  --hidden-import cv2 --hidden-import numpy ^
  --hidden-import tkinter --hidden-import tkinter.ttk ^
  --hidden-import queue --hidden-import threading --hidden-import dataclasses ^
  --hidden-import random --hidden-import typing --hidden-import ctypes --hidden-import enum ^
  --collect-submodules mss --collect-submodules keyboard ^
  --collect-submodules pydirectinput --collect-submodules PIL ^
  --add-data "%~dp0assets;assets_default" ^
  --distpath dist_protected --workpath build_obf\work --specpath build_obf ^
  build_obf\src\main.py || exit /b 1
(
echo pk-auto
echo ========
echo pk-auto.exe works on its own - no other files are needed.
echo Run pk-auto.exe, open the game lobby, press Start. Press F8 anytime to stop.
echo Choose your game language in the "Game language" box ^(Japanese, English,
echo Spanish, Portuguese, Russian; the last three are beta and look at the button
echo shape only, so they need no translation^).
echo Optional: an "assets" folder next to pk-auto.exe with your own button PNGs
echo overrides the built-in ones ^(play_btn, continue_btn, skip_btn,
echo return_lobby_btn, claim_btn, popup_btn^). English images end with _en
echo ^(play_btn_en.png, ...^).
echo Mode A = normal loop ^(Continue / Skip / Return to Lobby^). Mode B = wait on the
echo pre-match island ^(default 90 s^), then Esc, the hamburger tab, "Return to Lobby",
echo and queue again. Switch any time in the window; B works in every game language.
echo.
echo Warning: automation may violate the game's terms of service and anti-cheat
echo rules. Use at your own risk.
) > dist_protected\README.txt
rmdir /s /q build_obf
