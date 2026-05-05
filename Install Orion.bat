@echo off
REM ================================================================
REM   ORION installer for Windows
REM   Double-click this file. No code-signing -- this is open source.
REM   SmartScreen may warn once on first run; click "More info" then
REM   "Run anyway." After that it's trusted on this machine forever.
REM ================================================================

setlocal

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

echo.
echo ================================================================
echo    ORION -- portable AI memory
echo    Installing on this Windows machine...
echo    Source: %SCRIPT_DIR%
echo ================================================================
echo.

REM Run the PowerShell installer. -NoProfile speeds startup; -ExecutionPolicy
REM Bypass means we don't need a signed cert. This is the documented entry
REM point in install.ps1 line 17.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%\install.ps1"

set EXITCODE=%ERRORLEVEL%

echo.
if %EXITCODE%==0 (
    echo [OK] Install completed.
) else (
    echo [WARN] Install exited with code %EXITCODE%.
)
echo.
echo Press any key to close this window.
pause >nul

endlocal
exit /b %EXITCODE%
