@echo off
setlocal
call "%~dp0Python_Settings.bat"
if errorlevel 1 (pause & exit /b 1)
"%PY%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (echo Dependency installation failed. & pause & exit /b 1)
echo Dependencies installed for %PY%.
pause
