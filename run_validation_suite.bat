@echo off
setlocal

set "PROJECT_DIR=%~dp0"
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
echo [1/4] Running SCLAS self-check
%PYTHON_CMD% "%PROJECT_DIR%code\sclas_self_check.py"
if errorlevel 1 goto :failed

echo.
echo [2/4] Saving acceptance gate report
%PYTHON_CMD% "%PROJECT_DIR%code\sclas_acceptance_gate.py" --save-report --save-markdown
if errorlevel 1 goto :failed

echo.
echo [3/4] Saving handoff snapshot
%PYTHON_CMD% "%PROJECT_DIR%code\sclas_handoff_snapshot.py" --save-report --save-markdown
if errorlevel 1 goto :failed

echo.
echo [4/4] Saving next Codex prompt
%PYTHON_CMD% "%PROJECT_DIR%code\sclas_next_prompt.py" --save
if errorlevel 1 goto :failed

echo.
echo Validation suite complete.
echo Generated local reports are intentionally ignored by git.
endlocal
exit /b 0

:failed
set "EXIT_CODE=%ERRORLEVEL%"
echo.
echo Validation suite failed with exit code %EXIT_CODE%.
endlocal
exit /b %EXIT_CODE%
