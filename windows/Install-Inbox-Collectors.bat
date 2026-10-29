@echo off
setlocal
rem Kept in windows\; the AA files are one folder up.
for %%I in ("%~dp0..") do set "AA_ROOT=%%~fI\"
rem Run once in the normal Outlook/Teams account. Optional first argument: approved signed MSIX.
call "%~dp0Python_Settings.bat"
if errorlevel 1 goto failed
"%PY%" -m pip install -r "%AA_ROOT%requirements-outlook.txt"
if errorlevel 1 goto failed
if "%~1"=="" (
  powershell.exe -NoProfile -File "%~dp0Install-Notification-Listener.ps1"
) else (
  powershell.exe -NoProfile -File "%~dp0Install-Notification-Listener.ps1" -PackagePath "%~1"
)
if errorlevel 1 goto notifications
echo Collectors installed. Open Atlas Admin, Live Inbox, then Connect collectors.
pause
exit /b 0
:notifications
rem Teams notifications are optional: without a package, the email collector alone is a success.
if not "%~1"=="" goto failed
echo.
echo The email collector is ready. Teams notifications were skipped, as explained above: they need
echo your organisation's signed Atlas.NotificationListener.msix. Run this file again with its path later.
echo Next: open Atlas Admin, Live Inbox, then Connect collectors.
pause
exit /b 0
:failed
echo Collector installation needs attention. Read the error above; see docs\inbox-integration.md.
pause
exit /b 1
