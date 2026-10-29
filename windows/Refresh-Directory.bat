@echo off
setlocal
rem Kept in windows\; the AA files are one folder up.
for %%I in ("%~dp0..") do set "AA_ROOT=%%~fI\"
rem Python finds Atlas's modules in the AA folder from any working folder.
set "PYTHONPATH=%AA_ROOT%"
call "%~dp0Python_Settings.bat"
if errorlevel 1 (pause & exit /b 1)
echo Finish all installation and queue jobs before continuing.
echo This refresh updates the full Europe directory and preserves the Paris map.
pause
"%PY%" -m backend.launch.launcher stop
if errorlevel 1 (pause & exit /b 1)
rem Drop one workbook, or the users and devices exports together.
if "%~1"=="" (
  "%PY%" -m backend.directory.refresh_directory
) else if "%~2"=="" (
  "%PY%" -m backend.directory.refresh_directory --source "%~1"
) else (
  "%PY%" -m backend.directory.refresh_directory --source "%~1" --devices "%~2"
)
if errorlevel 1 (pause & exit /b 1)
echo Refresh command finished. Check the result above; cancelled runs do not change the database.
pause
