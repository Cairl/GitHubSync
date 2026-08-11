@echo off
rem GitHubSync 启动器：切换到脚本所在目录并启动交互模式（同步该目录）。
rem 内部使用 PowerShell 定位目录并调用当前入口 main.py（v3.0+，替代旧 python -m src）。
rem 目录经环境变量中转，规避 -Command 字符串模式 $args 无效与尾部反斜杠转义问题。
set "GITHUBSYNC_DIR=%~dp0"
powershell -NoProfile -Command "Set-Location $env:GITHUBSYNC_DIR; if (Get-Command python -ErrorAction SilentlyContinue) { python -m main } else { py -m main }; exit $LASTEXITCODE"
exit /b %errorlevel%
