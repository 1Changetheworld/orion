@echo off
REM ================================================================
REM   Wake Orion on this Windows machine
REM   Double-click this file. No code-signing -- this is open source.
REM   First run on a new machine shows a SmartScreen warning; click
REM   "More info" then "Run anyway." Trusted forever after that.
REM
REM   What this does:
REM   - If the drive already has an Orion brain (you've used Orion
REM     before), this just wires THIS machine to wake him here.
REM     ~30 seconds, no questions asked.
REM   - If the drive has no brain (first-ever Orion), runs the
REM     conversational setup so he can introduce himself.
REM ================================================================

setlocal

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

echo.
echo ================================================================
echo    Waking Orion on this Windows machine...
echo    Source: %SCRIPT_DIR%
echo ================================================================
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%\install.ps1"

set EXITCODE=%ERRORLEVEL%

echo.
if %EXITCODE%==0 (
    echo [OK] Orion is awake here.
) else (
    echo [WARN] Wake exited with code %EXITCODE%.
)
echo.
echo Press any key to close this window.
pause >nul

endlocal
exit /b %EXITCODE%
