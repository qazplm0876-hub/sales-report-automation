@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo 최초 실행환경이 없어 설치를 먼저 진행합니다.
    call INSTALL.bat
    if errorlevel 1 exit /b 1
)

".venv\Scripts\python.exe" -c "import openpyxl, yaml" >nul 2>nul
if errorlevel 1 (
    echo 필요한 패키지가 없거나 설치가 완료되지 않아 자동 설치를 진행합니다.
    call INSTALL.bat
    if errorlevel 1 exit /b 1
)

echo.
echo ============================================================
echo   월간 매출실적 분석
echo ============================================================
echo input 폴더에 공식표 1개, 누계파일 2개, 인수처 파일 12개를 넣어 주세요.
echo 25_1.xlsx 형식의 전년 인수처 파일 6개는 매달 그대로 보관해도 됩니다.
echo 월을 비워두면 공식 실적표 제목에서 자동으로 찾습니다.
echo.
set /p REPORT_MONTH=분석월 입력 [예: 202607, 자동은 Enter]:
if "%REPORT_MONTH%"=="" set "REPORT_MONTH=auto"

set "PYTHONPATH=%CD%\src"
".venv\Scripts\python.exe" -m sales_report --input "%CD%\input" --output "%CD%\output" --month "%REPORT_MONTH%"
if errorlevel 1 goto :error

echo.
echo 분석이 완료되었습니다. output 폴더를 엽니다.
start "" "%CD%\output"
pause
exit /b 0

:error
echo.
echo 분석이 중단되었습니다. 위 오류 메시지와 logs 폴더를 확인해 주세요.
pause
exit /b 1
