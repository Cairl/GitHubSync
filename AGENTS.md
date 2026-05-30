# AGENTS.md

## Project Overview

GitHubSync 是一个 Windows 终端 TUI 工具，将本地目录同步到 GitHub 仓库。基于 `git` 和 `gh` CLI 实现全部操作，使用 Rich 库渲染 TUI 界面。

- **语言**: Python 3.12+
- **平台**: Windows only（依赖 `msvcrt`、`shutil.get_terminal_size` 等）
- **外部依赖**: `git` CLI、`gh` CLI（GitHub 官方命令行工具）
- **Python 依赖**: `rich>=13.0`（通过 requirements.txt 管理）

## 项目结构

```
GitHubSync/
├── src/                  # 源码包
│   ├── __init__.py       # 包标识
│   ├── __main__.py       # 入口：python -m src [目录]
│   ├── config.py         # 常量：Rich Style 主题、键盘码、布局参数
│   ├── utils.py          # 工具函数：run_command、get_key、get_display_width
│   ├── git_manager.py    # GitManager 类：Git 操作管理
│   └── app.py            # App 类：Rich Live 驱动的 TUI 应用
├── run_sync.bat          # 启动器脚本，固定指向项目路径，同步 bat 所在目录
├── requirements.txt      # Python 依赖
├── AGENTS.md             # 本文件
├── AGENTS.py             # 示例/测试用的同步目标文件
└── changelog.md          # Changelog 说明（存在时自动发布 GitHub Release）
```

### 代码架构

```
config.py — 常量层
├── STYLE_*              # Rich Style 对象（Catppuccin Mocha 配色）
├── LEVEL_STYLES/LABELS  # 日志级别样式和中文标签
├── KEY_*                # 键盘扫描码常量
└── *_HEIGHT/TIMEOUT     # 布局和超时参数

utils.py — 工具函数层
├── enable_vt100()       # 启用 Windows VT100 终端处理
├── get_display_width()  # CJK 字符宽度计算（中文占 2，英文占 1）
├── run_command()        # 子进程执行封装（捕获 stdout/stderr）
├── get_key()            # 非阻塞按键读取（msvcrt）
└── get_input_with_default() # 带预填充文本的输入框

git_manager.py — Git 逻辑层
└── GitManager
    ├── log()            # 结构化日志：(timestamp, level, message) 元组
    ├── get_status()     # 获取仓库状态（分支、远程地址）
    ├── init_repo()      # 初始化 Git 仓库
    ├── configure_remote()  # 自动配置远程仓库（基于 GitHub 用户名 + 目录名）
    ├── sync()           # 核心同步流程：扫描→暂存→提交→推送
    ├── create_github_repo() # 创建 GitHub 仓库（浏览器 + 轮询检测）
    ├── force_push()     # 强制推送（含错误解析）
    ├── publish_release() # 发布 GitHub Release
    └── _parse_push_error() # 推送错误中文翻译

app.py — TUI 应用层
└── App
    ├── build_main_box() # 构建统一圆角框（状态 + 倒计时 + 文件列表）
    ├── build_log_text() # 构建日志文本（无边框）
    ├── build_screen()   # 组合完整屏幕（Group）
    ├── handle_key()     # 按键分发
    ├── refresh_file_list() # 扫描目录生成文件列表
    ├── execute_action() # 执行删除/推送操作
    └── run()            # 主循环（Rich Live + msvcrt 按键 + 60s 倒计时）
```

## Setup Commands

```bash
# 安装依赖
pip install -r requirements.txt

# 安装 gh CLI（GitHub 官方工具）
winget install --id GitHub.cli

# 登录 GitHub
gh auth login

# 运行同步工具（同步当前目录）
python -m src

# 运行同步工具（同步指定目录）
python -m src "C:\path\to\project"
```

> **注意**：如果 `python` 命令不可用，尝试使用 Windows Python 启动器 `py`：
> ```bash
> py -m src
> py -m src "C:\path\to\project"
> ```

## Development Workflow

```bash
# 语法检查（在项目根目录执行）
python -c "import py_compile; py_compile.compile('src/app.py', doraise=True)"

# 运行应用（同步当前工作目录）
python -m src
```

## Keyboard Shortcuts

| 按键 | 功能 |
|---|---|
| `↑` `↓` | 切换选中文件 |
| `←` `→` | 切换焦点（文件名 / 操作按钮） |
| `Enter` | 执行操作（焦点在操作按钮时）或切换到操作按钮（焦点在文件名时） |
| `Esc` / `Q` | 取消确认对话框 |
| `O` | 在浏览器中打开远程仓库 |

- 60 秒无操作自动退出
- 操作执行后有 1 秒冷却期，防止误触

## Troubleshooting

### 常见问题

- **`python` 命令找不到**：使用 `py` 代替 `python`，或在系统 PATH 中添加 Python 安装路径
- **`rich` 模块找不到**：运行 `pip install -r requirements.txt` 安装依赖
- **`gh` 命令找不到**：运行 `winget install --id GitHub.cli` 安装 GitHub CLI
- **推送失败（认证错误）**：运行 `gh auth login` 重新登录 GitHub
- **推送失败（仓库不存在）**：工具会自动打开浏览器创建仓库，完成后自动检测并继续同步
- **终端显示乱码**：确保使用 Windows Terminal 或支持 VT100 的终端，CMD 原生终端可能不完全支持 ANSI 转义序列

### 调试技巧

- 应用启动后立即显示菜单，同步过程日志实时显示在底部
- 日志区域显示最近的操作记录（同步、推送、删除等），按时间倒序
- 状态面板显示当前分支、远程仓库地址（可点击跳转）、最新 Release 版本
- 文件列表中带 `(已忽略)` 标签的表示已被 `.gitignore` 排除，不会被同步

## Testing Instructions

- 项目当前无自动化测试套件
- 手动验证：在测试目录中运行 `python -m src`，观察同步行为
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
- 常量: `UPPER_SNAKE_CASE`（`STYLE_RED`, `KEY_ENTER`, `IDLE_TIMEOUT`）
- 私有方法: 前缀 `_`（`_parse_push_error`, `_refresh_caches`）

### 格式约定
- 中文注释和文档字符串
- 颜色使用 `config.py` 中的 Rich `Style` 对象，禁止硬编码 ANSI 转义序列
- TUI 边框使用 Unicode 圆角字符：`╭╮╰╯│─`
- 模块间使用相对导入（`from .config import ...`）

### TUI 渲染规则
- 使用 Rich `Live` 组件进行全屏渲染，`refresh_per_second=4`
- 屏幕由 `Group` 组合：`build_main_box()`（统一圆角框）+ `build_log_text()`（无边框日志）
- 圆角框宽度固定 60 字符，内部包含状态行、倒计时条、文件列表
- 文件列表 padding 通过 `get_display_width(line.plain)` 直接测量行宽，确保右边框对齐
- 文件名等宽填充至 `max_name_width`，使操作文字垂直对齐
- 滚动指示器 `...` 在文件列表超出可见区域时显示
- 超链接使用 Rich `Style(link=url)` 替代手写 OSC 8 序列

### 渲染性能
- **禁止在渲染路径中执行子进程调用**。`build_screen()` 只读取缓存，不调用 `git` 或 `gh`
- 状态和 Release 信息缓存在 `App._cached_status` 和 `App._cached_release` 中
- 缓存在初始同步完成后和每次操作（删除/推送）完成后通过 `_refresh_caches()` 刷新
- 使用 `object()` 哨兵值（`_cache_miss_sentinel`）区分"未缓存"和"缓存值为 None"
- GitManager 的 `on_log` 回调在 Live 上下文中触发 `live.update()` 实现实时更新

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
# 1. 更新 changelog.md 写入版本说明
# 2. 运行同步工具，自动检测 changelog.md 并通过 gh release create 发布 GitHub Release
python -m src
```

- 无构建步骤，直接运行 `python -m src`
- `run_sync.bat` 固定指向项目源码路径（`PROJECT_DIR`），可复制到任意目录使用
- bat 所在目录即为同步目标（`%~dp0`），通过 `PYTHONPATH` 设置源码路径
- `.gitignore` 默认包含 `run_sync.bat`，避免启动器被意外提交

## Pull Request Guidelines

- 提交前运行语法检查确保无错误
- 更新 `changelog.md` 记录本次变更，格式遵循 `cairl-changelog-management` 规范
- 更新 `AGENTS.md` 与 `changelog.md` 保持同步（内容彼此独立，但需同步维护）
- 提交信息使用中文，简要描述变更内容

## Changelog 管理

- `changelog.md` 仅保留本次更新的变更内容，不记录历史版本
- 存在旧内容时直接覆盖，而非追加
- 分类顺序固定为 **添加 → 修复 → 优化**，无内容的分类整体省略
- 条目格式：`- **功能名**: 描述`
- 更新 `AGENTS.md` 时必须同步更新 `changelog.md`，反之亦然
