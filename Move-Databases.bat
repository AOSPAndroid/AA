@echo off
setlocal
rem Moves the Atlas databases to F:\Atlas\DB, or to a folder given as the first argument.
call "%~dp0Python_Settings.bat"
if errorlevel 1 (pause & exit /b 1)
echo Moving the Atlas databases. Run Stop-All-Atlas.bat first if Atlas is open.
"%PY%" "%~dp0move_databases.py" %*
set "ATLAS_MOVE_RESULT=%ERRORLEVEL%"
pause
exit /b %ATLAS_MOVE_RESULT%
