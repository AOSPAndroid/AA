@echo off
setlocal
rem Kept in windows\; the AA files are one folder up.
for %%I in ("%~dp0..") do set "AA_ROOT=%%~fI\"
rem Python finds Atlas's modules in the AA folder from any working folder.
set "PYTHONPATH=%AA_ROOT%"
call "%~dp0Python_Settings.bat"
if errorlevel 1 (pause & exit /b 1)
echo Opening Atlas Admin, Demo and hosted Preview.
echo Starting configured Live Inbox collectors under the normal mail account.
"%PY%" -m backend.launch.edition_launcher both all %*
if errorlevel 1 (pause & exit /b 1)
