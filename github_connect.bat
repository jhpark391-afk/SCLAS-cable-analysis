@echo off
setlocal

set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

call "%PROJECT_DIR%git_sclas.bat" init
if errorlevel 1 exit /b %ERRORLEVEL%

call "%PROJECT_DIR%git_sclas.bat" branch -M main
if errorlevel 1 exit /b %ERRORLEVEL%

call "%PROJECT_DIR%git_sclas.bat" config user.name "jhpark391-afk"
if errorlevel 1 exit /b %ERRORLEVEL%

call "%PROJECT_DIR%git_sclas.bat" config user.email "jhpark391-afk@users.noreply.github.com"
if errorlevel 1 exit /b %ERRORLEVEL%

call "%PROJECT_DIR%git_sclas.bat" remote get-url origin >nul 2>nul
if errorlevel 1 (
    call "%PROJECT_DIR%git_sclas.bat" remote add origin https://github.com/jhpark391-afk/SCLAS-cable-analysis.git
) else (
    call "%PROJECT_DIR%git_sclas.bat" remote set-url origin https://github.com/jhpark391-afk/SCLAS-cable-analysis.git
)
if errorlevel 1 exit /b %ERRORLEVEL%

echo.
echo GitHub remote is connected:
call "%PROJECT_DIR%git_sclas.bat" remote -v
echo.
call "%PROJECT_DIR%git_sclas.bat" status --short --branch

endlocal
