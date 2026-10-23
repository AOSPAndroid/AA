@echo off
setlocal
call "%~dp0Python_Settings.bat"
if errorlevel 1 (pause & exit /b 1)
echo Opening Atlas Admin, Demo and hosted Preview.
echo Starting configured Live Inbox collectors under the normal mail account.
"%PY%" "%~dp0edition_launcher.py" both all %*
if errorlevel 1 (pause & exit /b 1)
