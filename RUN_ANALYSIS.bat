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
echo input\YYYYMM 폴더에 해당 월 원본 12개를 넣어 주세요.
echo 최신 YYYYMM 폴더와 공식표 제목을 기준으로 분석월을 자동 선택합니다.
echo 기존처럼 input 폴더 바로 아래에 파일을 넣는 방식도 계속 사용할 수 있습니다.
echo.

set "PYTHONPATH=%CD%\src"
".venv\Scripts\python.exe" -m sales_report --input "%CD%\input" --output "%CD%\output" --month auto
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
