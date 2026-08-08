@echo off
set "PROJECT_DIR=S:\GitHubSync"
set "SYNC_TARGET=%~dp0"
set "PYTHONPATH=%PROJECT_DIR%"
python -m src "%SYNC_TARGET:~0,-1%"
