@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo 실행 폴더: %CD%
if not exist ".git" (
    echo [주의] 이 폴더는 GitHub Desktop과 연결된 저장소가 아닙니다.
    echo GitHub Desktop의 Repository ^> Show in Explorer로 연 폴더에서 실행해 주세요.
    echo.
)

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

set "LATEST_FILE="
for /f "usebackq delims=" %%F in (`powershell -NoProfile -Command "Get-ChildItem -LiteralPath '%CD%\unit_price_output' -Filter '*.xlsx' ^| Sort-Object LastWriteTime -Descending ^| Select-Object -First 1 -ExpandProperty FullName"`) do set "LATEST_FILE=%%F"

if defined LATEST_FILE (
    echo 최신 결과파일을 엽니다: %LATEST_FILE%
    start "" "%LATEST_FILE%"
) else (
    echo 결과파일을 찾지 못해 출력 폴더를 엽니다.
    start "" "%CD%\unit_price_output"
)
pause
exit /b 0

:error
echo.
echo 생성이 중단되었습니다. 누계 Raw 2개와 템플릿 파일을 확인해 주세요.
pause
exit /b 1
