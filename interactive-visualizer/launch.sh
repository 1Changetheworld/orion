#!/usr/bin/env bash
# Interactive Visualizer launcher (macOS / Linux)
# Opens Orion's neural network at http://localhost:5556
HERE="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$HERE"
exec python3 dashboard_server.py "$@"
