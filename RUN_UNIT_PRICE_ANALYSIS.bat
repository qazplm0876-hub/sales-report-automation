@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    call INSTALL.bat
    if errorlevel 1 exit /b 1
)

echo.
echo ============================================================
echo   제품판매단가 원인탐색 통합파일 생성
echo ============================================================
echo 1. unit_price_template.xlsx : 기존 1~N월 통합파일 (최초 1회만 준비)
echo 2. unit_price_input : 전년·당해 누계 Raw 2개
echo 3. 실행 결과는 unit_price_output에 저장됩니다.
echo.

set "PYTHONPATH=%CD%\src"
".venv\Scripts\python.exe" -m sales_report.unit_price --input "%CD%\unit_price_input" --template "%CD%\unit_price_template.xlsx" --output "%CD%\unit_price_output"
if errorlevel 1 goto :error

start "" "%CD%\unit_price_output"
pause
exit /b 0

:error
echo.
echo 생성이 중단되었습니다. 누계 Raw 2개와 템플릿 파일을 확인해 주세요.
pause
exit /b 1
