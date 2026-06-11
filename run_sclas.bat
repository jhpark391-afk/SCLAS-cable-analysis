@echo off
setlocal

set "PROJECT_DIR=%~dp0"
set "APP_ENTRY=%PROJECT_DIR%code\sclas_remote_gui.py"
set "PYTHON_EXE="

if exist "%PROJECT_DIR%.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%PROJECT_DIR%.venv\Scripts\python.exe"
    goto :run
)

for %%I in ("%PROJECT_DIR%..") do set "DOCUMENTS_DIR=%%~fI"
set "WINDOWS_READY_PY=%DOCUMENTS_DIR%\SCLAS-cable-analysis-windows-ready-20260611\.venv\Scripts\python.exe"
if exist "%WINDOWS_READY_PY%" (
    set "PYTHON_EXE=%WINDOWS_READY_PY%"
    goto :run
)

where py >nul 2>nul
if not errorlevel 1 (
    py -3 "%APP_ENTRY%"
    goto :done
)

where python >nul 2>nul
if not errorlevel 1 (
    python "%APP_ENTRY%"
    goto :done
)

echo ERROR: Python was not found.
echo Looked for:
echo   %PROJECT_DIR%.venv\Scripts\python.exe
echo   %WINDOWS_READY_PY%
echo   py.exe or python.exe on PATH
echo.
echo Run setup_windows.bat first, or install Python and make sure py.exe or python.exe is on PATH.
exit /b 1

:run
echo Starting SCLAS with "%PYTHON_EXE%"
"%PYTHON_EXE%" "%APP_ENTRY%"

:done
set "EXIT_CODE=%ERRORLEVEL%"
endlocal
exit /b %EXIT_CODE%
