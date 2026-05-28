@echo off
set "DIR=%~dp0"
python -m github_sync "%DIR:~0,-1%"
