# GitHubSync

Windows 终端 TUI 工具，将本地目录同步到 GitHub 仓库。

## 项目结构

- `github_sync.py` — 单文件应用，包含 TUI 框架、Git 操作逻辑、文件管理
- `run_sync.bat` — 启动器脚本，将自身所在目录作为目标路径传入 github_sync.py
- `tests/` — 单元测试

## 核心流程

1. 启动时自动执行 `sync()`：扫描文件 → 暂存 → 提交 → 推送
2. 推送成功后自动检测 `release.md`，若存在则发布 GitHub Release
3. TUI 界面支持文件列表浏览、删除/推送操作、60 秒倒计时自动退出

## 关键设计

- 基于 `gh` CLI 操作 GitHub（检测仓库、发布 Release）
- Release 发布失败不阻塞同步主流程
- 首次提交遇到 `Author identity unknown` 时自动配置 Git 身份
- 无命令行参数时默认同步当前工作目录，无需 GUI 依赖

## 变更记录

### 2026-04-30

- 新增 `run_sync.bat` 启动器脚本，支持将 bat 所在目录自动作为同步目标
- 默认 `.gitignore` 新增 `run_sync.bat`，避免启动器被意外提交到用户仓库
- 移除 `run_sync.bat` 末尾的 `cmd /k`，脚本执行完毕后自动关闭窗口
