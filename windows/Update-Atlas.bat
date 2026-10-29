@echo off
setlocal
rem Kept in windows\; the AA files are one folder up.
for %%I in ("%~dp0..") do set "AA_ROOT=%%~fI\"
if exist "%AA_ROOT%Start AA.bat" (
  echo This is AA. Download the AA update and follow README.md:
  echo https://github.com/AOSPAndroid/AA/releases/download/aa-windows/aa-windows.zip
  if not "%ATLAS_UPDATE_NO_PAUSE%"=="1" pause
  exit /b 1
)
echo Updating Atlas from AOSPAndroid/Atlas ^(main^).
call "%~dp0Python_Settings.bat"
if errorlevel 1 (
  set "ATLAS_UPDATE_RESULT=1"
  goto finish
)
set "PYTHONPATH=%AA_ROOT%"
"%PY%" -m backend.launch.update_atlas %*
set "ATLAS_UPDATE_RESULT=%ERRORLEVEL%"
:finish
echo.
if "%ATLAS_UPDATE_RESULT%"=="0" (
  echo Atlas update command finished. Check the result above.
) else (
  echo Atlas update command failed. Read the message above before trying again.
)
if not "%ATLAS_UPDATE_NO_PAUSE%"=="1" pause
exit /b %ATLAS_UPDATE_RESULT%
