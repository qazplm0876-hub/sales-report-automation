@echo off
setlocal
cd /d "%~dp0"

echo.
echo ============================================
echo   Sales report automation
echo ============================================
echo.
echo Input folder:
echo   data\2026-MM\input
echo.

set /p REPORT_MONTH=Enter report month. Example 6 : 
if "%REPORT_MONTH%"=="" (
  echo Month was not entered. Stopping.
  pause
  exit /b 1
)

set "REPORT_MONTH_PADDED=%REPORT_MONTH%"
if "%REPORT_MONTH:~1,1%"=="" set "REPORT_MONTH_PADDED=0%REPORT_MONTH%"

set "LOCAL_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "BASE_PY="
set "BASE_PY_ARG="

if exist "%LOCAL_PY%" set "BASE_PY=%LOCAL_PY%"

if not defined BASE_PY (
  where py >nul 2>nul
  if not errorlevel 1 (
    set "BASE_PY=py"
    set "BASE_PY_ARG=-3"
  )
)

if not defined BASE_PY (
  where python >nul 2>nul
  if not errorlevel 1 set "BASE_PY=python"
)

if not defined BASE_PY (
  echo.
  echo Python was not found. Please install Python 3 and run again.
  pause
  exit /b 1
)

if not exist "%VENV_PY%" (
  echo Preparing the report environment for the first run...
  "%BASE_PY%" %BASE_PY_ARG% -m venv "%~dp0.venv"
  if errorlevel 1 (
    echo Failed to create the Python environment.
    pause
    exit /b 1
  )
)

"%VENV_PY%" -c "import pandas, openpyxl, xlrd, reportlab" >nul 2>nul
if errorlevel 1 (
  echo Installing required packages. Internet access is needed only for this step...
  "%VENV_PY%" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
  if errorlevel 1 (
    echo Failed to install required packages.
    pause
    exit /b 1
  )
)

"%VENV_PY%" monthly_report_final.py --month %REPORT_MONTH%

if errorlevel 1 (
  echo.
  echo Failed. Please check the message above.
  pause
  exit /b 1
)

echo.
echo Done. Check this output folder:
echo   data\2026-%REPORT_MONTH_PADDED%\output
pause
