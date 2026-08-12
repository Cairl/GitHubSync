@echo off
rem GitHubSync launcher.
rem Repo root (main.py beside the bat): write GITHUBSYNC_REPO to this dir, then run.
rem Copied elsewhere (portable): call the existing GITHUBSYNC_REPO env var; error if unset.
set "GITHUBSYNC_DIR=%~dp0"
if exist "%GITHUBSYNC_DIR%main.py" (
    set "GITHUBSYNC_REPO=%GITHUBSYNC_DIR%"
) else if not defined GITHUBSYNC_REPO (
    echo GitHubSync: GITHUBSYNC_REPO is not set. Run this bat from the repo root, or set GITHUBSYNC_REPO to the repo directory.
    exit /b 3
)
powershell -NoProfile -Command "$dir = $env:GITHUBSYNC_REPO; $py = if (Get-Command python -ErrorAction SilentlyContinue) { 'python' } else { 'py' }; if (Test-Path (Join-Path $dir 'main.py')) { Set-Location $dir; & $py -m main; exit $LASTEXITCODE } else { Write-Host ('GitHubSync: main.py not found in ' + $dir + '. Set GITHUBSYNC_REPO to the GitHubSync repo directory.'); exit 3 }"
exit /b %errorlevel%
