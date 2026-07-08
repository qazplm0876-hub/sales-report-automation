@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ============================================
echo   매출실적분석 보고서 자동 생성
echo ============================================
echo.
echo 자료 위치:
echo   data\2026-월\input
echo.

set /p REPORT_MONTH=보고서 대상 월을 입력하세요. 예: 6 :
if "%REPORT_MONTH%"=="" (
  echo 월을 입력하지 않아 실행을 중단합니다.
  pause
  exit /b 1
)

set "REPORT_MONTH_PADDED=%REPORT_MONTH%"
if "%REPORT_MONTH:~1,1%"=="" set "REPORT_MONTH_PADDED=0%REPORT_MONTH%"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 monthly_report_final.py --month %REPORT_MONTH%
) else (
  python monthly_report_final.py --month %REPORT_MONTH%
)

echo.
echo 작업이 끝났습니다. 결과는 data\2026-%REPORT_MONTH_PADDED%\output 폴더를 확인하세요.
pause
