@echo off
REM Interactive Visualizer launcher (Windows)
REM Opens Orion's neural network at http://localhost:5556
set HERE=%~dp0
pushd "%HERE%"
python dashboard_server.py %*
popd
