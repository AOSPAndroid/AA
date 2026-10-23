@echo off
setlocal
rem Run once as yourself (your normal Outlook account, NOT "Run as administrator").
rem Installs pywin32 for this account and can start the Atlas Companion when you sign in.
net session >nul 2>&1
if not errorlevel 1 (
  echo This window is elevated. Close it and double-click Install-Atlas-Companion.bat as yourself.
  pause
  exit /b 1
)
call "%~dp0Python_Settings.bat"
if errorlevel 1 goto failed
"%PY%" -m pip install --user -r "%~dp0requirements-outlook.txt"
if errorlevel 1 goto failed
echo.
choice /c YN /m "Start the Atlas Companion automatically when you sign in"
if errorlevel 2 goto start
powershell.exe -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\Atlas Companion.lnk');$s.TargetPath='%~dp0Start-Atlas-Companion.bat';$s.WorkingDirectory='%~dp0';$s.WindowStyle=7;$s.Description='Atlas Companion: clipboard and Outlook for Atlas';$s.Save()"
if errorlevel 1 goto failed
echo Added to your Startup folder. Remove "Atlas Companion" there to undo.
:start
call "%~dp0Start-Atlas-Companion.bat"
exit /b 0
:failed
echo Companion installation needs attention. Read the error above; see docs\companion.md.
pause
exit /b 1
