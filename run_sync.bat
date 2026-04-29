@echo off
set "DIR=%~dp0"
python "S:\Github Repositories\GitHubSync\github_sync.py" "%DIR:~0,-1%"
cmd /k
