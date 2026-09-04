@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo [1/3] Python 확인 중...
where py >nul 2>nul
if not errorlevel 1 goto :use_py_launcher

where python >nul 2>nul
if errorlevel 1 goto :python_not_found
set "PY_CMD=python"
goto :python_ready

:use_py_launcher
set "PY_CMD=py -3"

:python_ready

echo [2/3] 전용 실행환경 생성 중...
if not exist ".venv\Scripts\python.exe" (
    %PY_CMD% -m venv .venv
    if errorlevel 1 goto :error
)

echo [3/3] 필요한 패키지 설치 중...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo.
echo 설치가 완료되었습니다. 다음부터 RUN_ANALYSIS.bat만 실행하면 됩니다.
pause
exit /b 0

:error
echo.
echo 설치 중 오류가 발생했습니다. 회사 보안망에서 패키지 다운로드가 차단되었는지 확인해 주세요.
pause
exit /b 1

:python_not_found
echo.
echo Python 3이 설치되어 있지 않습니다.
echo https://www.python.org/downloads/windows/ 에서 설치한 뒤 다시 실행해 주세요.
echo 설치 화면에서 반드시 "Add python.exe to PATH"를 선택해야 합니다.
pause
exit /b 1
