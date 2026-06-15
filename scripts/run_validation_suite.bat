@echo off
setlocal

set "PROJECT_DIR=%~dp0..\"
set "VENV_PYTHON=%PROJECT_DIR%.venv\Scripts\python.exe"

if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" -c "import sys" >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_CMD=%VENV_PYTHON%"
        goto :run
    )
)

where py >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
    goto :run
)

where python >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=python"
    goto :run
)

echo ERROR: Python was not found.
echo Run setup_windows.bat first, or install Python and make sure py.exe or python.exe is on PATH.
exit /b 1

:run
%PYTHON_CMD% "%PROJECT_DIR%code\sclas_validation_suite.py" --save-report --save-markdown
if errorlevel 1 goto :failed

echo.
echo Validation suite complete.
echo Generated local reports are intentionally ignored by git:
echo   %PROJECT_DIR%validation_suite_report.json
echo   %PROJECT_DIR%validation_suite_report.md
endlocal
exit /b 0

:failed
set "EXIT_CODE=%ERRORLEVEL%"
echo.
echo Validation suite failed with exit code %EXIT_CODE%.
endlocal
exit /b %EXIT_CODE%
