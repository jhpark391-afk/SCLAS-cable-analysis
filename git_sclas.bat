@echo off
setlocal

set "PROJECT_DIR=%~dp0"
for %%I in ("%PROJECT_DIR%.") do set "SAFE_PROJECT_DIR=%%~fI"
set "GIT_EXE="

if exist "%ProgramFiles%\Git\cmd\git.exe" (
    set "GIT_EXE=%ProgramFiles%\Git\cmd\git.exe"
    goto :run
)

if exist "%ProgramFiles%\Microsoft Visual Studio\18\Community\Common7\IDE\CommonExtensions\Microsoft\TeamFoundation\Team Explorer\Git\cmd\git.exe" (
    set "GIT_EXE=%ProgramFiles%\Microsoft Visual Studio\18\Community\Common7\IDE\CommonExtensions\Microsoft\TeamFoundation\Team Explorer\Git\cmd\git.exe"
    goto :run
)

if exist "%ProgramFiles%\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\TeamFoundation\Team Explorer\Git\cmd\git.exe" (
    set "GIT_EXE=%ProgramFiles%\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\TeamFoundation\Team Explorer\Git\cmd\git.exe"
    goto :run
)

echo ERROR: Git was not found.
echo Install Git for Windows or the Visual Studio Git tools, then rerun this command.
exit /b 1

:run
cd /d "%PROJECT_DIR%"
"%GIT_EXE%" -c "safe.directory=%SAFE_PROJECT_DIR%" %*
set "EXIT_CODE=%ERRORLEVEL%"
endlocal
exit /b %EXIT_CODE%
