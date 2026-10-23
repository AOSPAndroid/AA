@echo off
setlocal
call "%~dp0Python_Settings.bat"
if errorlevel 1 (pause & exit /b 1)
echo Starting Atlas and configured Live Inbox collectors.
"%PY%" "%~dp0launcher.py" run %*
if errorlevel 1 (pause & exit /b 1)
