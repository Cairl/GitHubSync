@echo off
rem GitHubSync launcher (pure batch, zero PowerShell).
rem Home (GitHubSync repo root beside this bat, detected by main.py + cli\parser.py + core\protocols.py):
rem   silently persist GITHUBSYNC_REPO to the user environment (setx, skip if unchanged), then sync this dir.
rem Portable copy elsewhere: read GITHUBSYNC_REPO (user registry as fallback) to locate the code,
rem   then sync this bat's own directory.
setlocal
set "BAT_DIR=%~dp0"
set "SYNC_DIR=%BAT_DIR:~0,-1%"

rem -- Home detection: all three marker files present --
if not exist "%BAT_DIR%main.py" goto :portable
if not exist "%BAT_DIR%cli\parser.py" goto :portable
if not exist "%BAT_DIR%core\protocols.py" goto :portable
set "CODE_DIR=%BAT_DIR%"
rem Persist to user env only when changed (avoid WM_SETTINGCHANGE broadcast every run)
set "REG_VAL="
for /f "tokens=2,*" %%a in ('reg query "HKCU\Environment" /v GITHUBSYNC_REPO 2^>nul') do set "REG_VAL=%%b"
if /i not "%REG_VAL%"=="%SYNC_DIR%" setx GITHUBSYNC_REPO "%SYNC_DIR%" >nul
goto :run

:portable
if not defined GITHUBSYNC_REPO (
    for /f "tokens=2,*" %%a in ('reg query "HKCU\Environment" /v GITHUBSYNC_REPO 2^>nul') do set "GITHUBSYNC_REPO=%%b"
)
if not defined GITHUBSYNC_REPO (
    echo GitHubSync: GITHUBSYNC_REPO is not set. Run this bat from the repo root, or set GITHUBSYNC_REPO to the GitHubSync repo directory. 1>&2
    exit /b 3
)
set "CODE_DIR=%GITHUBSYNC_REPO%"
if not "%CODE_DIR:~-1%"=="\" set "CODE_DIR=%CODE_DIR%\"

:run
if not exist "%CODE_DIR%main.py" (
    echo GitHubSync: main.py not found in %CODE_DIR%. Set GITHUBSYNC_REPO to the GitHubSync repo directory. 1>&2
    exit /b 3
)
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (
    where py >nul 2>nul && set "PY=py"
)
if not defined PY (
    echo GitHubSync: Python not found. Install Python 3.12+ ^(or the py launcher^) and retry. 1>&2
    exit /b 3
)
cd /d "%CODE_DIR%"
%PY% -m main "%SYNC_DIR%"
exit /b %errorlevel%
