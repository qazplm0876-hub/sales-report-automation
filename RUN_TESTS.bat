@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo 먼저 INSTALL.bat을 실행해 주세요.
    pause
    exit /b 1
)

set "PYTHONPATH=%CD%\src"
".venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 (
    echo.
    echo 테스트가 실패했습니다.
    pause
    exit /b 1
)

echo.
echo 모든 테스트가 통과했습니다.
pause
