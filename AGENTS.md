# AGENTS.md

## Project Overview

GitHubSync 是一个 Windows 终端 TUI 工具，将本地目录同步到 GitHub 仓库。单文件 Python 应用，无需 GUI 依赖，基于 `git` 和 `gh` CLI 实现全部操作。

- **语言**: Python 3.12+
- **平台**: Windows only（依赖 `msvcrt`、`shutil.get_terminal_size` 等）
- **外部依赖**: `git` CLI、`gh` CLI（GitHub 官方命令行工具）
- **Python 依赖**: 仅标准库，无 pip 依赖

## 项目结构

```
GitHubSync/
├── github_sync.py    # 单文件应用（~1150 行），包含全部逻辑
├── run_sync.bat      # 启动器脚本，将自身所在目录作为同步目标
├── AGENTS.md         # 本文件
├── AGENTS.py         # 示例/测试用的同步目标文件
└── release.md        # Release 说明模板（存在时自动发布 GitHub Release）
```

### 代码架构

```
工具函数层
├── get_display_width()    # CJK 字符宽度计算（中文占 2，英文占 1）
├── strip_ansi()           # 移除 ANSI 转义序列（CSI + OSC 超链接）
├── wrap_ansi_line()       # ANSI 感知的文本折行（保留颜色码）
└── get_input_with_default() # 带预填充文本的输入框

TUI 框架层
├── Colors                 # Catppuccin 风格颜色常量（真彩色 ANSI）
├── Keys                   # 键盘扫描码常量
├── init_console()         # 启用 VT100 终端处理
└── get_key()              # 非阻塞按键读取

Git 逻辑层
├── run_command()          # 子进程执行封装（捕获 stdout/stderr）
└── GitManager             # Git 操作管理
    ├── get_status()       # 获取仓库状态（分支、远程地址）
    ├── init_repo()        # 初始化 Git 仓库
    ├── sync()             # 核心同步流程：扫描→暂存→提交→推送
    ├── force_push()       # 强制推送（含错误解析）
    ├── publish_release()  # 发布 GitHub Release
    └── _parse_push_error() # 推送错误中文翻译

TUI 应用层
└── App                    # TUI 应用主类
    ├── get_render_lines() # 构建渲染行列表（状态面板 + 文件列表 + 日志）
    ├── render()           # 增量渲染（仅更新变化行）
    ├── refresh_file_list()# 扫描目录生成文件菜单
    ├── delete_selected()  # 删除/推送选中文件
    └── run()              # 主循环（按键处理 + 60s 倒计时）
```

## Setup Commands

```bash
# 安装 gh CLI（GitHub 官方工具）
winget install --id GitHub.cli

# 登录 GitHub
gh auth login

# 运行同步工具（同步当前目录）
python github_sync.py

# 运行同步工具（同步指定目录）
python github_sync.py "C:\path\to\project"
```

## Development Workflow

```bash
# 语法检查
python -c "import py_compile; py_compile.compile(r's:\Github Repositories\GitHubSync\github_sync.py', doraise=True)"

# 运行应用（同步当前工作目录）
python github_sync.py
```

### 调试技巧

- 应用启动后自动执行同步，可在同步完成后观察 TUI 状态面板
- 日志区域显示最近的操作记录（同步、推送、删除等）
- 按 `↑` `↓` 切换文件，按 `Tab` 切换文件名/操作高亮，按 `Enter` 执行
- 60 秒无操作自动退出

## Testing Instructions

- 项目当前无自动化测试套件
- 手动验证：在测试目录中运行 `python github_sync.py`，观察同步行为
- 验证关注点：
  - 首次运行应自动初始化 Git 仓库并创建 `.gitignore`
  - 文件列表正确显示目录内容
  - 删除/推送操作正确执行
  - 错误信息正确显示中文翻译
  - 60 秒倒计时自动退出

## Code Style

### 命名规范
- 类名: `PascalCase`（`GitManager`, `App`）
- 函数/方法: `snake_case`（`get_display_width`, `refresh_file_list`）
- 常量: `UPPER_SNAKE_CASE`（`Colors.RESET`, `Keys.ENTER`）
- 私有方法: 前缀 `_`（`_parse_push_error`, `_refresh_caches`）

### 格式约定
- 中文注释和文档字符串
- ANSI 颜色码使用 `Colors` 类常量，禁止硬编码转义序列
- TUI 边框使用 Unicode 圆角字符：`╭╮╰╯│─`
- 文件内分区使用 `# ─── 分区名 ───────` 分隔

### TUI 渲染规则
- 使用绝对光标定位（`\033[{row};1H`）进行增量渲染
- 每行以 `\033[K` 清除行尾，避免残留
- 文件列表行宽计算：`fixed_width + max_cn_width`，`fixed_width` 在 `refresh_file_list()` 中预计算
  - `fixed_width` 必须包含所有固定字符（`│`、空格、action 文字宽度、action 后空格、tag 宽度）
  - `max_cn_width` 为所有文件名中的最大宽度，动态补充 padding 差异
  - 选中状态下的行宽变化通过调整 `visible_len` 补偿，确保右边框对齐
- 滚动指示器 `...` 填充宽度 = `box_width - 8 - 1`（8 为指示器可见宽度）
- ANSI 超链接使用 OSC 8 格式：`\033]8;;url\033\\text\033]8;;\033\\`

### 渲染性能
- **禁止在渲染路径中执行子进程调用**。`get_render_lines()` 只读取缓存，不调用 `git` 或 `gh`
- 状态和 Release 信息缓存在 `App._cached_status` 和 `App._cached_release` 中
- 缓存在初始同步完成后和每次操作（删除/推送）完成后通过 `_refresh_caches()` 刷新
- 使用 `object()` 哨兵值（`_cache_miss_sentinel`）区分"未缓存"和"缓存值为 None"，避免 `None` 既是合法返回值又是未缓存标记的问题

### 错误处理
- 子进程错误通过 `run_command()` 统一捕获，合并 stdout 和 stderr 返回
- `GitManager._parse_push_error()` 将 Git 推送错误翻译为中文提示，大小写不敏感匹配关键词：
  - `recv failure` / `connection` / `failed to connect` → 网络连接失败
  - `could not resolve host` → DNS 解析失败
  - `timeout` → 连接超时
  - `authentication failed` / `403` → 认证失败
  - `repository not found` / `404` → 仓库不存在
  - `rejected` + `non-fast-forward` → 推送被拒绝
  - `schannel` / `certificate` / `ssl` → SSL 证书验证失败
  - `everything up-to-date` → 无需推送
- 无法识别的错误回退显示原始英文信息
- Release 发布失败不阻塞同步主流程

## Build and Deployment

```bash
# 发布新版本流程
# 1. 更新 release.md 写入版本说明
# 2. 运行同步工具，自动检测 release.md 并通过 gh release create 发布 GitHub Release
python github_sync.py
```

- 无构建步骤，直接运行 Python 脚本
- `run_sync.bat` 可作为独立启动器分发到任意目录，自动以 bat 所在目录作为同步目标
- `.gitignore` 默认包含 `run_sync.bat`，避免启动器被意外提交