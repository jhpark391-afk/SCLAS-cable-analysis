@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_BIN=python"
if exist "..\90_env\venv\Scripts\python.exe" set "PYTHON_BIN=..\90_env\venv\Scripts\python.exe"

"%PYTHON_BIN%" code\sclas_research_report.py --save-report --save-markdown %*
exit /b %ERRORLEVEL%
