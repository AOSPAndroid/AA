@echo off
rem Double-click to join a downloaded model's parts into its GGUF file. Starts nothing else.
title Join model
cd /d "%~dp0"
set "PY="
rem Standard Python installation on managed PCs; prefer it over PATH aliases.
if exist "C:\devhome\tools\python3.12\current\python.exe" set "PY="C:\devhome\tools\python3.12\current\python.exe""
if not defined PY (
  where py >nul 2>nul && set "PY=py -3"
)
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY for /d %%D in ("C:\devhome\tools\python3*") do if exist "%%D\current\python.exe" set "PY="%%D\current\python.exe""
if not defined PY for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%D\python.exe" set "PY="%%D\python.exe""
if not defined PY (
  echo Python was not found. Run start.py with the full path to python.exe, for example:
  echo   C:\path\to\python.exe join_model.py
  pause
  exit /b 1
)
%PY% join_model.py %*
pause
