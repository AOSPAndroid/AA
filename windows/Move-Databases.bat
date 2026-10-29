@echo off
setlocal
rem Kept in windows\; the AA files are one folder up.
for %%I in ("%~dp0..") do set "AA_ROOT=%%~fI\"
rem Moves the Atlas databases to F:\Atlas\DB, or to a folder given as the first argument.
rem Python finds Atlas's modules in the AA folder from any working folder.
set "PYTHONPATH=%AA_ROOT%"
call "%~dp0Python_Settings.bat"
if errorlevel 1 (pause & exit /b 1)
echo Moving the Atlas databases. Run Stop-All-Atlas.bat first if Atlas is open.
"%PY%" -m backend.directory.move_databases %*
set "ATLAS_MOVE_RESULT=%ERRORLEVEL%"
pause
exit /b %ATLAS_MOVE_RESULT%
