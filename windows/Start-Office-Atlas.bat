@echo off
setlocal
rem Kept in windows\; the AA files are one folder up.
for %%I in ("%~dp0..") do set "AA_ROOT=%%~fI\"
rem Python finds Atlas's modules in the AA folder from any working folder.
set "PYTHONPATH=%AA_ROOT%"
call "%~dp0Python_Settings.bat"
if errorlevel 1 (pause & exit /b 1)
echo Starting Atlas and configured Live Inbox collectors.
"%PY%" -m backend.launch.launcher run %*
if errorlevel 1 (pause & exit /b 1)
