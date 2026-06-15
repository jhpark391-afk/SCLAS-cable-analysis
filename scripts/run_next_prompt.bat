@echo off
setlocal

set "PROJECT_DIR=%~dp0..\"
set "PROMPT_ENTRY=%PROJECT_DIR%code\sclas_next_prompt.py"
set "PROMPT_ARGS=--save"

if exist "%PROJECT_DIR%.venv\Scripts\python.exe" (
    "%PROJECT_DIR%.venv\Scripts\python.exe" "%PROMPT_ENTRY%" %PROMPT_ARGS%
    goto :done
)

where py >nul 2>nul
if not errorlevel 1 (
    py -3 "%PROMPT_ENTRY%" %PROMPT_ARGS%
    goto :done
)

where python >nul 2>nul
if not errorlevel 1 (
    python "%PROMPT_ENTRY%" %PROMPT_ARGS%
    goto :done
)

echo ERROR: Python was not found.
echo Run setup_windows.bat first, or install Python and make sure py.exe or python.exe is on PATH.
exit /b 1

:done
set "EXIT_CODE=%ERRORLEVEL%"
if "%EXIT_CODE%"=="0" (
    echo.
    echo Next Codex prompt saved:
    echo   %PROJECT_DIR%NEXT_CODEX_PROMPT.md
)
endlocal
exit /b %EXIT_CODE%
