@echo off
setlocal

set "PROJECT_DIR=%~dp0..\"
set "VENV_PYTHON=%PROJECT_DIR%.venv\Scripts\python.exe"
set "CODEX_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" -c "import sys" >nul 2>nul
    if not errorlevel 1 (
        "%VENV_PYTHON%" "%PROJECT_DIR%code\sclas_self_check.py"
        goto :done
    )
)

if exist "%CODEX_PYTHON%" (
    "%CODEX_PYTHON%" -c "import sys" >nul 2>nul
    if not errorlevel 1 (
        "%CODEX_PYTHON%" "%PROJECT_DIR%code\sclas_self_check.py"
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
echo Run setup_windows.bat first, install Python, or run from Codex with the bundled runtime available.
exit /b 1

:done
set "EXIT_CODE=%ERRORLEVEL%"
endlocal
exit /b %EXIT_CODE%
