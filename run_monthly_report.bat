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

set "LOCAL_PY=C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if exist "%LOCAL_PY%" (
  "%LOCAL_PY%" monthly_report_final.py --month %REPORT_MONTH%
) else (
  where py >nul 2>nul
  if %errorlevel%==0 (
    py -3 monthly_report_final.py --month %REPORT_MONTH%
  ) else (
    python monthly_report_final.py --month %REPORT_MONTH%
  )
)

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
