@echo off
rem Optional: set WMI_PYTHON to a full Python 3.12+ path before launching.
if not defined WMI_PYTHON if exist "C:\devhome\tools\python3.12\current\python.exe" set "WMI_PYTHON=C:\devhome\tools\python3.12\current\python.exe"
set "PY=%WMI_PYTHON%"
if defined PY goto check
for /f "delims=" %%P in ('py -3.12 -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%P"
:check
if defined PY if exist "%PY%" exit /b 0
echo Python 3.12 not found. Install Python 3.12 or set WMI_PYTHON to its full path.
exit /b 1
