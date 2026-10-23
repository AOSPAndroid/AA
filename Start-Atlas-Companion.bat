@echo off
setlocal
rem Starts the Atlas Companion in your normal account (tray icon, no window).
rem Atlas Admin keeps running elevated as usual; the Companion connects to it on this PC.
net session >nul 2>&1
if not errorlevel 1 (
  echo This window is elevated. Start the Atlas Companion as yourself, not "Run as administrator".
  pause
  exit /b 1
)
call "%~dp0Python_Settings.bat"
if errorlevel 1 (pause & exit /b 1)
set "PYW=%PY:python.exe=pythonw.exe%"
if not exist "%PYW%" set "PYW=%PY%"
start "" "%PYW%" "%~dp0atlas_companion.py"
echo Atlas Companion started: look for its icon in the notification area.
