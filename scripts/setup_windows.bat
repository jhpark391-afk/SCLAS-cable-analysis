@echo off
setlocal

set "PROJECT_DIR=%~dp0..\"
cd /d "%PROJECT_DIR%"
set "VENV_PYTHON=.venv\Scripts\python.exe"
set "CODEX_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "PYTHON_FOR_VENV="
set "RECREATE_VENV=0"

if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" -c "import sys" >nul 2>nul
    if errorlevel 1 (
        echo Existing .venv Python could not start; it will be recreated.
        set "RECREATE_VENV=1"
    ) else (
        goto :install_requirements
    )
)

where py >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_FOR_VENV=py -3"
    goto :create_venv
)

where python >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_FOR_VENV=python"
    goto :create_venv
)

if exist "%CODEX_PYTHON%" (
    "%CODEX_PYTHON%" -c "import sys" >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_FOR_VENV=%CODEX_PYTHON%"
        goto :create_venv
    )
)

echo ERROR: Python was not found.
echo Install Python 3 for Windows, enable the Python workload in Visual Studio, or run from Codex with the bundled runtime available.
exit /b 1

:create_venv
if "%RECREATE_VENV%"=="1" (
    %PYTHON_FOR_VENV% -m venv --clear .venv
) else (
    %PYTHON_FOR_VENV% -m venv .venv
)
if errorlevel 1 exit /b %ERRORLEVEL%

:install_requirements
"%VENV_PYTHON%" -m pip install --upgrade pip
if errorlevel 1 exit /b %ERRORLEVEL%
"%VENV_PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 exit /b %ERRORLEVEL%

echo.
echo SCLAS Windows environment is ready.
echo Run run_sclas.bat to start the GUI.
endlocal
