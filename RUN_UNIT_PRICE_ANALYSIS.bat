@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo Running from: %CD%
if not exist ".git" (
    echo [WARNING] This folder is not linked to GitHub Desktop.
    echo Open Repository ^> Show in Explorer in GitHub Desktop and run this file there.
    echo.
)

if not exist ".venv\Scripts\python.exe" (
    call INSTALL.bat
    if errorlevel 1 exit /b 1
)

echo.
echo ============================================================
echo   Unit price root-cause workbook generator
echo ============================================================
echo 1. unit_price_template.xlsx : workbook template
echo 2. unit_price_input : two cumulative Raw workbooks
echo 3. Output folder : unit_price_output
echo.

set "PYTHONPATH=%CD%\src"
".venv\Scripts\python.exe" -m sales_report.unit_price --input "%CD%\unit_price_input" --template "%CD%\unit_price_template.xlsx" --output "%CD%\unit_price_output"
if errorlevel 1 goto :error

set "LATEST_FILE="
for /f "usebackq delims=" %%F in (`powershell -NoProfile -Command "Get-ChildItem -LiteralPath '%CD%\unit_price_output' -Filter '*.xlsx' ^| Sort-Object LastWriteTime -Descending ^| Select-Object -First 1 -ExpandProperty FullName"`) do set "LATEST_FILE=%%F"

if defined LATEST_FILE (
    echo Opening latest workbook: %LATEST_FILE%
    start "" "%LATEST_FILE%"
) else (
    echo No workbook found. Opening output folder.
    start "" "%CD%\unit_price_output"
)
pause
exit /b 0

:error
echo.
echo Generation failed. Check the two cumulative Raw files and template workbook.
pause
exit /b 1
