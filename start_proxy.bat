@echo off
REM ====================================================================
REM  ORION LITELLM PROXY LAUNCHER
REM  Double-click or run: start_proxy.bat
REM
REM  Opens a new persistent terminal window that runs the proxy on :4000.
REM  The proxy stays alive as long as that window is open.
REM  Close the window to stop the proxy. Do not close the one you
REM  launched FROM — only the new "Orion Proxy" window it opens.
REM ====================================================================

set "REPO_DIR=%~dp0"
cd /d "%REPO_DIR%"

REM Spawn a titled, detached window so this proxy outlives the caller.
start "Orion Proxy :4000" cmd /k "title Orion Proxy :4000 & set PYTHONIOENCODING=utf-8 & litellm --config orion_litellm_config.yaml --port 4000"

echo.
echo   Orion LiteLLM proxy launching in new window...
echo   Title:    Orion Proxy :4000
echo   Endpoint: http://localhost:4000/v1
echo   Master key: sk-orion-local-dev  (see orion_litellm_config.yaml)
echo.
echo   Close the proxy window to stop. You can close this launcher window.
echo.
