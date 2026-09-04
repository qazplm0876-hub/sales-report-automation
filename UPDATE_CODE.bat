@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where git >nul 2>nul
if errorlevel 1 (
    echo Git이 설치되어 있지 않습니다. GitHub Desktop에서 Fetch/Pull을 사용해 주세요.
    pause
    exit /b 1
)

git pull --ff-only
if errorlevel 1 (
    echo 자동 업데이트에 실패했습니다. 로컬 코드 변경사항 또는 로그인 상태를 확인해 주세요.
    pause
    exit /b 1
)

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :dependency_error
)

echo 최신 코드로 업데이트되었습니다.
pause
exit /b 0

:dependency_error
echo 패키지 업데이트에 실패했습니다. 회사 보안망 또는 Python 환경을 확인해 주세요.
pause
exit /b 1
