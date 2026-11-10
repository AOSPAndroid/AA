@echo off
rem Compatibility shortcut. AA owns all startup/shutdown.
call "%~dp0Start AA.bat" %*
exit /b %errorlevel%
