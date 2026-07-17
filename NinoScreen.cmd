@echo off
setlocal
set "NINO_ROOT=%~dp0"
if "%NINO_ROOT:~-1%"=="\" set "NINO_ROOT=%NINO_ROOT:~0,-1%"
set "NINO_DATA_ROOT=D:\runtime\profiles\nino"
set "NINO_APPDATA_ROOT=%NINO_DATA_ROOT%\appdata"
set "PYTHONUTF8=1"
set "TEMP=D:\temp\nino"
set "TMP=D:\temp\nino"
set "APPDATA=%NINO_APPDATA_ROOT%\Roaming"
set "LOCALAPPDATA=%NINO_APPDATA_ROOT%\Local"
if not exist "%NINO_DATA_ROOT%" mkdir "%NINO_DATA_ROOT%"
if not exist "%TEMP%" mkdir "%TEMP%"
if not exist "%APPDATA%" mkdir "%APPDATA%"
if not exist "%LOCALAPPDATA%" mkdir "%LOCALAPPDATA%"
"%NINO_ROOT%\.venv\Scripts\python.exe" "%NINO_ROOT%\main.py"
set "NINO_EXIT=%ERRORLEVEL%"
endlocal & exit /b %NINO_EXIT%
