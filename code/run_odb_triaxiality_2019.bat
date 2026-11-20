@echo off
setlocal
set "HELIX_TRIAX_SCRIPT_DIR=%~dp0"
set "ABAQUS_CMD=C:\SIMULIA\Commands\abq2019.bat"
if not exist "%ABAQUS_CMD%" set "ABAQUS_CMD=abq2019"
call "%ABAQUS_CMD%" cae noGUI="%~dp0odb_triaxiality_2019.py" -- %*
set "RESULT=%ERRORLEVEL%"
echo.
echo Finished. Check the console and outputs\odb_triaxiality.
pause
exit /b %RESULT%
