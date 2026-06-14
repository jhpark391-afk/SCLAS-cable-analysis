@echo off
setlocal

set "PROJECT_DIR=%~dp0"
set "GATE_ENTRY=%PROJECT_DIR%code\sclas_acceptance_gate.py"
set "GATE_ARGS=--save-report --save-markdown"

if exist "%PROJECT_DIR%.venv\Scripts\python.exe" (
    "%PROJECT_DIR%.venv\Scripts\python.exe" "%GATE_ENTRY%" %GATE_ARGS%
    goto :done
)

where py >nul 2>nul
if not errorlevel 1 (
    py -3 "%GATE_ENTRY%" %GATE_ARGS%
    goto :done
)

where python >nul 2>nul
if not errorlevel 1 (
    python "%GATE_ENTRY%" %GATE_ARGS%
    goto :done
)

echo ERROR: Python was not found.
echo Run setup_windows.bat first, or install Python and make sure py.exe or python.exe is on PATH.
exit /b 1

:done
set "EXIT_CODE=%ERRORLEVEL%"
if "%EXIT_CODE%"=="0" (
    echo.
    echo Acceptance gate report saved in the latest job folder.
)
endlocal
exit /b %EXIT_CODE%
