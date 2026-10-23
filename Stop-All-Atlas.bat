@echo off
setlocal
call "%~dp0Python_Settings.bat"
if errorlevel 1 (pause & exit /b 1)
echo Stopping all local Atlas servers. Finish active jobs first.
echo Configured Live Inbox collectors receive a graceful stop request.
echo Hosted Preview stays online and browser tabs remain open.
"%PY%" "%~dp0launcher.py" stop
if errorlevel 1 (pause & exit /b 1)
