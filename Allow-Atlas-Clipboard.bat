@echo off
setlocal
rem Lets Atlas Admin (http://127.0.0.1:8770) read the clipboard in Edge and Chrome without asking.
rem Double-click it as yourself (the account you browse with). Add "remove" to undo: Allow-Atlas-Clipboard.bat remove
if /i "%~1"=="remove" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\allow_clipboard.ps1" -Remove
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\allow_clipboard.ps1"
)
echo.
pause
