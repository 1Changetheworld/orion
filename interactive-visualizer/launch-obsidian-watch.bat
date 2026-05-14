@echo off
REM Auto-export the brain as an Obsidian vault, re-render on every change.
REM Open the target folder in Obsidian (Start -> Open folder as vault).
set HERE=%~dp0
pushd "%HERE%\.."
python orion_obsidian_export.py --out "%USERPROFILE%\Desktop\orion-vault" --watch
popd
