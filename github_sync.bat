@echo off
rem GitHubSync launcher: sync the directory where this bat lives.
rem Mode 1: main.py exists here (repo root), run python -m main directly.
rem Mode 2: bat copied elsewhere (portable), use installed githubsync command.
rem Mode 3: neither, hint to pip install -e . first, exit code 3.
set "GITHUBSYNC_DIR=%~dp0"
powershell -NoProfile -Command "$dir = $env:GITHUBSYNC_DIR; $py = if (Get-Command python -ErrorAction SilentlyContinue) { 'python' } else { 'py' }; if (Test-Path (Join-Path $dir 'main.py')) { Set-Location $dir; & $py -m main } elseif (Get-Command githubsync -ErrorAction SilentlyContinue) { Set-Location $dir; githubsync } else { Write-Host 'GitHubSync: main.py not found and githubsync command not installed. For portable mode run pip install -e . first, or put this bat back in the GitHubSync repo root.'; exit 3 }; exit $LASTEXITCODE"
exit /b %errorlevel%
