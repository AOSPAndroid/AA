@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
if not defined WMI_PYTHON if exist "C:\devhome\tools\python3.12\current\python.exe" set "WMI_PYTHON=C:\devhome\tools\python3.12\current\python.exe"
call Python_Settings.bat
if errorlevel 1 (
    pause
    exit /b 1
)
"%PY%" "%~dp0aa_launcher.py" stop %*
set "AA_EXIT=%ERRORLEVEL%"
if not "%AA_EXIT%"=="0" pause
exit /b %AA_EXIT%
