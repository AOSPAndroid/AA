@echo off
setlocal
rem Kept in windows\; the AA files are one folder up.
for %%I in ("%~dp0..") do set "AA_ROOT=%%~fI\"
call "%~dp0Python_Settings.bat"
if errorlevel 1 (pause & exit /b 1)
"%PY%" -m pip install -r "%AA_ROOT%requirements.txt"
if errorlevel 1 (echo Dependency installation failed. & pause & exit /b 1)
echo Dependencies installed for %PY%.
pause
