@echo off
setlocal

set "PROJECT_DIR=%~dp0..\"
set "VENV_PYTHON=%PROJECT_DIR%.venv\Scripts\python.exe"

if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" -c "import sys" >nul 2>nul
    if not errorlevel 1 (
        "%VENV_PYTHON%" "%PROJECT_DIR%code\sclas_self_check.py"
        goto :done
    )
)

where py >nul 2>nul
if not errorlevel 1 (
    py -3 "%PROJECT_DIR%code\sclas_self_check.py"
    goto :done
)

where python >nul 2>nul
if not errorlevel 1 (
    python "%PROJECT_DIR%code\sclas_self_check.py"
    goto :done
)

echo ERROR: Python was not found.
echo Run setup_windows.bat first, or install Python and make sure py.exe or python.exe is on PATH.
exit /b 1

:done
set "EXIT_CODE=%ERRORLEVEL%"
endlocal
exit /b %EXIT_CODE%
