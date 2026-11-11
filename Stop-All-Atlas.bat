@echo off
rem Compatibility shortcut. AA owns all startup/shutdown.
call "%~dp0Stop AA.bat" %*
exit /b %errorlevel%
