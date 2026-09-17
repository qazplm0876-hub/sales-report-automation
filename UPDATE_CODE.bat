@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist ".git" (
    echo This is not a GitHub Desktop repository folder.
    echo Open Repository ^> Show in Explorer in GitHub Desktop and run UPDATE_CODE there.
    pause
    exit /b 1
)

where git >nul 2>nul
if errorlevel 1 (
    echo Git is not installed. Use Fetch/Pull in GitHub Desktop.
    pause
    exit /b 1
)

git pull --ff-only
if errorlevel 1 (
    echo Automatic update failed. Check local changes or GitHub login status.
    pause
    exit /b 1
)

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :dependency_error
)

echo Update completed.
pause
exit /b 0

:dependency_error
echo Package update failed. Check the company network or Python environment.
pause
exit /b 1
