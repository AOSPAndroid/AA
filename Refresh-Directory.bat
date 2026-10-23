@echo off
setlocal
call "%~dp0Python_Settings.bat"
if errorlevel 1 (pause & exit /b 1)
echo Finish all installation and queue jobs before continuing.
echo This refresh updates the full Europe directory and preserves the Paris map.
pause
"%PY%" "%~dp0launcher.py" stop
if errorlevel 1 (pause & exit /b 1)
rem Drop one workbook, or the users and devices exports together.
if "%~1"=="" (
  "%PY%" "%~dp0refresh_directory.py"
) else if "%~2"=="" (
  "%PY%" "%~dp0refresh_directory.py" --source "%~1"
) else (
  "%PY%" "%~dp0refresh_directory.py" --source "%~1" --devices "%~2"
)
if errorlevel 1 (pause & exit /b 1)
echo Refresh command finished. Check the result above; cancelled runs do not change the database.
pause
