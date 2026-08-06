# AGENTS.md

## Project Overview

GitHubSync 是一个 Windows 终端 TUI 工具，将本地目录同步到 GitHub 仓库。基于 `git` 和 `gh` CLI 实现全部操作，使用 Rich 库渲染 TUI 界面。
- 推送模式：上传新文件到 GitHub 或从 GitHub 删除文件
- 恢复模式：浏览 Git 提交历史，选择后回车恢复到指定 commit
- Release 发布：检测到 `changelog.md` 时自动发布 GitHub Release 并删除本地文件
- 自动创建仓库、自动配置远程、冲突时强制推送



- **语言**: Python 3.12+
- **版本**: 2.0.0（定义于 `src/__init__.py`）
- **平台**: Windows only（依赖 `msvcrt`、`shutil.get_terminal_size` 等）
- **外部依赖**: `git` CLI、`gh` CLI（GitHub 官方命令行工具）
- **Python 依赖**: `rich>=13.0`（通过 requirements.txt 管理）

## 项目结构

```
GitHubSync/
├── src/                  # 源码包
│   ├── __init__.py       # 包标识，定义 __version__
│   ├── __main__.py       # 入口：python -m src [目录]
│   ├── config.py         # 常量：Rich Style 主题、键盘码、布局参数
│   ├── utils.py          # 工具函数：run_command、get_key、get_display_width
│   ├── git_manager.py    # GitManager 类：Git 操作管理
│   └── app.py            # App 类：Rich Live 驱动的 TUI 应用
├── sync.bat              # 启动器脚本，固定指向项目路径，同步 bat 所在目录
├── requirements.txt      # Python 依赖
├── AGENTS.md             # 本文件
└── changelog.md          # Changelog 说明（存在时自动发布 GitHub Release）
```

### 代码架构

```
config.py — 常量层
├── STYLE_*              # Rich Style 对象（Catppuccin Mocha 配色）
├── LEVEL_STYLES/LABELS  # 日志级别样式和时态标签（正在/完成/失败/注意）
├── KEY_*                # 键盘扫描码常量
└── *_HEIGHT             # 布局尺寸参数

utils.py — 工具函数层
├── enable_vt100()       # 启用 Windows VT100 终端处理
├── get_display_width()  # CJK 字符宽度计算（中文占 2，英文占 1）
├── run_command()        # 子进程执行封装（捕获 stdout/stderr）
├── get_key()            # 非阻塞按键读取（msvcrt）
└── get_input_with_default() # 带预填充文本的输入框

git_manager.py — Git 逻辑层
└── GitManager
    ├── log()               # 结构化日志：(timestamp, level, message) 元组
    ├── action()            # 上下文管理器：进入时记录"正在"，退出时原地替换为"完成"或"失败"
    ├── get_status()        # 获取仓库状态（分支、远程地址）
    ├── init_repo()         # 初始化 Git 仓库
    ├── create_ignore()     # 创建默认 .gitignore（含 changelog.md）
    ├── _ensure_gitignore_entry() # 确保 .gitignore 包含指定条目
    ├── _exclude_from_index() # 从索引排除文件（已跟踪则 rm --cached，未跟踪则 reset）
    ├── get_github_username() # 获取 GitHub 用户名（gh api → git remote → 邻近仓库）
    ├── get_repo_slug()     # 获取仓库 slug（owner/repo）
    ├── get_latest_release() # 获取最新 Release 信息（标签 + 发布时间）
    ├── get_all_releases()   # 获取所有 Release 标签列表（最多 20 个）
    ├── get_recent_commits() # 获取最近的 Git 提交历史（hash + 时间）
    ├── get_change_count()   # 获取工作区变更文件数（git status --porcelain）
    ├── restore_to_tag()     # 恢复到指定 tag（fetch + reset --hard）
    ├── restore_to_commit()  # 恢复到指定 commit（reset --hard）
    ├── calculate_next_version() # 计算下一版本号（YYwWWa 格式，周内递增字母）
    ├── configure_remote()  # 自动配置远程仓库（基于 GitHub 用户名 + 目录名，无交互）
    ├── sync()              # 核心同步流程：扫描→排除changelog.md→提交→推送→发布Release
    ├── create_github_repo() # 创建 GitHub 仓库（浏览器 + 轮询检测）
    ├── force_push()        # 强制推送（含错误解析）
    ├── publish_release()   # 发布 GitHub Release
    └── _parse_push_error() # 推送错误中文翻译（所有推送失败统一调用）

app.py — TUI 应用层
└── App
    ├── mode                # 当前模式：0=推送模式, 1=恢复模式
    ├── mode_locked         # 模式是否已锁定（回车确认后为 True）
    ├── _on_git_log()       # GitManager 日志回调，触发 Live 更新
    ├── _get_status()       # 获取缓存的状态（懒加载）
    ├── _get_release()      # 获取缓存的 Release 信息（懒加载）
    ├── _get_changes()      # 获取缓存的变更检测结果（懒加载）
    ├── _refresh_caches()   # 刷新状态、Release 和变更缓存
    ├── load_releases()     # 加载 Git 提交历史列表（恢复模式确认后调用）
    ├── do_first_sync()     # 基本初始化（创建 .gitignore、init、配置 remote）
    ├── _init_background()  # 后台线程执行初始化与缓存刷新（不阻塞界面渲染）
    ├── _on_mode_selected() # 模式确认后的初始化（推送模式执行 sync，恢复模式加载提交历史）
    ├── build_main_box()    # 构建左右两栏圆角框（左：模式+状态+日志，右：列表）
    ├── build_screen()      # 组合完整屏幕（Group）
    ├── handle_key()        # 按键分发（根据 mode 分流；锁定后左右键切换操作焦点）
    ├── refresh_file_list() # 扫描目录生成文件列表
    ├── execute_action()    # 推送模式：执行删除/推送操作
    ├── execute_restore()   # 恢复模式：恢复到选中的 commit
    ├── remove_from_github() # 从 GitHub 删除文件（git rm + gitignore + push）
    ├── push_to_github()    # 推送文件到 GitHub（移除 gitignore + add + commit + push）
    ├── add_to_gitignore()  # 添加条目到 .gitignore
    ├── remove_from_gitignore() # 从 .gitignore 移除条目
    ├── confirm_delete()    # 物理删除确认对话框
    ├── open_remote()       # 在浏览器中打开远程仓库
    └── run()               # 主循环（Rich Live + msvcrt 按键，启动即渲染框架，数据后台懒加载）
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
# 语法检查（在项目根目录执行，逐文件检查）
python -c "import py_compile; py_compile.compile('src/app.py', doraise=True)"

# 运行应用（同步当前工作目录）
python -m src
```

## Keyboard Shortcuts

| 按键 | 功能 |
|---|---|
| `↑` `↓` | 切换选中项（文件 / 版本） |
| `←` `→` | 移动模式光标（推送 / 恢复）或切换焦点到操作按钮 |
| `Enter` | 确认模式选择（未锁定时）或执行操作（焦点在操作按钮时） |
| `Esc` | 取消确认对话框 |
| `Q` | 退出程序（任意阶段） |
| `O` | 在浏览器中打开远程仓库 |

- 操作执行后有 1 秒冷却期，防止误触
- 推送模式：左键重置焦点，右键切到操作按钮
- 恢复模式：右键切到操作按钮，Enter 确认恢复
- 模式选择：启动时默认光标在推送模式，左右键移动光标，回车确认后锁定（无超时自动确认）

## Troubleshooting

### 常见问题

- **`python` 命令找不到**：使用 `py` 代替 `python`，或在系统 PATH 中添加 Python 安装路径
- **`rich` 模块找不到**：运行 `pip install -r requirements.txt` 安装依赖
- **`gh` 命令找不到**：运行 `winget install --id GitHub.cli` 安装 GitHub CLI
- **推送失败（认证错误）**：运行 `gh auth login` 重新登录 GitHub
- **推送失败（仓库不存在）**：工具会自动打开浏览器创建仓库，完成后自动检测并继续同步
- **终端显示乱码**：确保使用 Windows Terminal 或支持 VT100 的终端，CMD 原生终端可能不完全支持 ANSI 转义序列

### 调试技巧

- 应用启动后显示模式选择界面，默认光标在推送模式，左右键移动光标，回车确认
- 确认模式后不可切换，推送模式执行同步，恢复模式加载提交历史
- 同步过程日志实时显示在底部
- 日志区域显示最近的操作记录（同步、推送、删除等），按时间倒序
- 状态面板显示当前分支、远程仓库地址（可点击跳转）、最新 Release 版本
- 文件列表中带 `(已忽略)` 标签的表示已被 `.gitignore` 排除，不会被同步
- 推送操作：按 `→` 切换焦点到操作按钮，按 `Enter` 执行；非忽略文件执行删除（从 GitHub 远程删除），已忽略文件执行推送（上传到 GitHub）
- 恢复操作：按 `←` `→` 移动光标到恢复模式，按 `Enter` 确认，用 `↑` `↓` 选择 commit，按 `→` 再 `Enter` 确认恢复

## Testing Instructions

- 测试文件位于 `tests/` 目录，使用 `pytest` 运行
- 运行全部测试：`python -m pytest tests/`
- 手动验证：在测试目录中运行 `python -m src`，观察同步行为
- 验证关注点：
  - 首次运行应自动初始化 Git 仓库并创建 `.gitignore`
  - 文件列表正确显示目录内容
  - 删除/推送操作正确执行
  - 错误信息正确显示中文翻译
  - 按 Q 键可正常退出程序

## Code Style

### 命名规范
- 类名: `PascalCase`（`GitManager`, `App`）
- 函数/方法: `snake_case`（`get_display_width`, `refresh_file_list`）
- 常量: `UPPER_SNAKE_CASE`（`STYLE_RED`, `KEY_ENTER`, `COOLDOWN_PERIOD`）
- 私有方法: 前缀 `_`（`_parse_push_error`, `_refresh_caches`）

### 格式约定
- 中文注释和文档字符串
- 颜色使用 `config.py` 中的 Rich `Style` 对象，禁止硬编码 ANSI 转义序列
- TUI 边框使用 Unicode 圆角字符：`╭╮╰╯│─`
- 模块间使用相对导入（`from .config import ...`）

### TUI 渲染规则
- 使用 Rich `Live` 组件进行全屏渲染，`refresh_per_second=4`
- 屏幕由 `Group` 组成：`build_main_box()`（左右两栏圆角框，日志在左栏内，无独立日志面板）
- 圆角框目标宽度 101 字符（`App.BOX_WIDTH`，左右栏各 49 保证奇数宽，虚线可首尾减号对称），终端不足时自动收缩；左右栏之间以竖线分隔，形似打开的书
- 右栏顶部为模式导航栏，下方以减号虚线封闭并隔一个空行再接列表区
- 左栏：模式选择导航栏 + 列表区
- 模式选择导航栏：位于左栏顶部（`推送模式 | 恢复模式`，各占一半宽度，无横线竖线间隔），左右键移动光标，回车确认后锁定，选中模式整块背景高亮，下方隔一个空行接列表区
- 右栏：状态区（项目/分支/主页/版本）、空行、日志区
- 变更检测：选择模式前通过 `git status --porcelain` 统计变更文件数，有变更时在分支行后括号显示 `分支: main (3)`（默认色）
- 推送模式显示文件列表（带 [+] / [-] 状态标记），恢复模式显示 Git 提交历史列表
- 恢复模式列表显示 commit hash 和提交时间
- 左右栏每行通过 `_merge_row()` 合并，padding 用 `get_display_width(line.plain)` 测量，确保竖线和右边框对齐
- 恢复模式版本列表在栏内整体居中显示（按内容最大宽度计算统一缩进 `_pad_row`），保持列对齐；推送模式文件列表保持左对齐
- 文件名等宽填充至 `max_name_width`（上限为右栏宽减固定开销），超宽用 `_truncate()` 截断加省略号
- 状态区值和日志消息同样通过 `_truncate()` 截断，防止撑破边框
- 滚动指示器 `...` 在文件列表超出可见区域时显示
- 超链接使用 Rich `Style(link=url)` 替代手写 OSC 8 序列

### 渲染性能
- **禁止在渲染路径中执行子进程调用**。`build_screen()` 只读取缓存，不调用 `git` 或 `gh`；`_get_status/_get_release/_get_changes` 均为纯读缓存，不触发刷新
- 启动即渲染界面框架，缓存未就绪时状态区仅显示项目名、其余行留空（静默加载，无加载回显）；初始化（`do_first_sync` + `_refresh_caches` + `refresh_file_list`）在后台线程执行，完成后自动 `live.update` 刷新
- 模式锁定（`_on_mode_selected`）前会 `join` 等待初始化线程结束，避免与同步操作并发访问仓库
- 恢复模式预览：光标聚焦恢复模式（未锁定）即通过 `_ensure_releases_loaded()` 静默预加载提交历史（无占位回显，列表区留空），后台异步加载完成后自动刷新；已加载或加载中则不重复触发
- 恢复模式占位项（`(加载中...)` / `(无提交)`）通过 `_restore_available()` 拦截，不可展开操作或执行恢复
- 状态、Release 和变更信息缓存在 `App._cached_status`、`App._cached_release` 和 `App._cached_changes` 中
- 缓存在后台初始化完成后和每次操作（删除/推送）完成后通过 `_refresh_caches()` 刷新
- 使用 `object()` 哨兵值（`_cache_miss_sentinel`）区分"未缓存"和"缓存值为 None"
- GitManager 的 `on_log` 回调在 Live 上下文中触发 `live.update()` 实现实时更新

### 错误处理
- 子进程错误通过 `run_command()` 统一捕获，合并 stdout 和 stderr 返回
- **所有推送失败统一调用 `_parse_push_error()`** 翻译为中文提示，包括 `sync()`、`force_push()`、`remove_from_github()`、`push_to_github()` 中的推送操作
- `_parse_push_error()` 大小写不敏感匹配关键词：
  - `recv failure` / `connection` / `failed to connect` → 网络连接异常
  - `could not resolve host` → DNS 解析异常
  - `timeout` → 连接超时
  - `authentication failed` / `403` → 认证异常
  - `repository not found` / `404` → 仓库不存在
  - `rejected` + (`non-fast-forward` 或 `fetch first`) → 推送被拒绝
  - `schannel` / `certificate` / `ssl` → SSL 证书验证异常
  - `everything up-to-date` → 无需推送
- 无法识别的错误回退显示 `未知错误: ` + 原始英文信息
- Release 发布失败不阻塞同步主流程

### 远程仓库配置
- `configure_remote()` 全自动配置，无需用户输入
- 远程 URL 由 `get_github_username()` + 目录名拼接：`https://github.com/{username}/{repo_name}`
- `get_github_username()` 按优先级尝试：`gh api user` → 当前仓库 git remote → 邻近目录仓库 git remote
- 推送时若仓库不存在，自动打开浏览器创建并轮询检测

### Rich Live 交互限制
- Rich 15 不支持 `Live.pause()`，需使用 `Live.stop()` + `Live.start()` 配合 `try/finally` 管理 TUI 状态
- 用户输入提示在 `Live(screen=True)` 上下文中无法正常工作，避免在全屏 TUI 模式下执行交互式输入

## Build and Deployment

```bash
# 发布新版本流程
# 1. 更新 changelog.md 写入版本说明
# 2. 运行同步工具，自动检测 changelog.md 并通过 gh release create 发布 GitHub Release
python -m src
```

- 无构建步骤，直接运行 `python -m src`
- `sync.bat` 固定指向项目源码路径（`PROJECT_DIR`），可复制到任意目录使用
- bat 所在目录即为同步目标（`%~dp0`），通过 `PYTHONPATH` 设置源码路径
- `.gitignore` 默认包含 `sync.bat`，避免启动器被意外提交

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
