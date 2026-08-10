@echo off
rem GitHubSync 启动器：切换到脚本所在目录并启动交互模式（同步该目录）。
rem 内部使用 PowerShell 定位目录并调用当前入口 main.py（v3.0+，替代旧 python -m src）。
powershell -NoProfile -Command "Set-Location $args[0]; python -m main" -args "%~dp0"
