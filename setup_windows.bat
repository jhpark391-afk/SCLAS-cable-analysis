@echo off
setlocal

set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"
set "VENV_PYTHON=.venv\Scripts\python.exe"

if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" -c "import sys" >nul 2>nul
    if errorlevel 1 (
        echo ERROR: Existing .venv Python could not start.
        echo Rename or delete the .venv folder, install Python 3, then run setup_windows.bat again.
        exit /b 1
    )
) else (
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3 -m venv .venv
    ) else (
        where python >nul 2>nul
        if not errorlevel 1 (
            python -m venv .venv
        ) else (
            echo ERROR: Python was not found.
            echo Install Python 3 for Windows, or enable the Python workload in Visual Studio.
            exit /b 1
        )
    )
    if errorlevel 1 exit /b %ERRORLEVEL%
)

"%VENV_PYTHON%" -m pip install --upgrade pip
if errorlevel 1 exit /b %ERRORLEVEL%
"%VENV_PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 exit /b %ERRORLEVEL%

echo.
echo SCLAS Windows environment is ready.
echo Run run_sclas.bat to start the GUI.
endlocal
