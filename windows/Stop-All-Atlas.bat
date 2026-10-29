@echo off
setlocal
rem Kept in windows\; the AA files are one folder up.
for %%I in ("%~dp0..") do set "AA_ROOT=%%~fI\"
rem Python finds Atlas's modules in the AA folder from any working folder.
set "PYTHONPATH=%AA_ROOT%"
call "%~dp0Python_Settings.bat"
if errorlevel 1 (pause & exit /b 1)
echo Stopping all local Atlas servers. Finish active jobs first.
echo Configured Live Inbox collectors receive a graceful stop request.
echo Hosted Preview stays online and browser tabs remain open.
"%PY%" -m backend.launch.launcher stop
if errorlevel 1 (pause & exit /b 1)
