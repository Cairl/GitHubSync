# AGENTS.md

## Project Overview

GitHubSync 是一个 Windows 终端 TUI 工具，将本地目录同步到 GitHub 仓库。基于 `git` 和 `gh` CLI 实现全部操作，使用 Rich 库渲染 TUI 界面。
- 推送模式：上传新文件到 GitHub 或从 GitHub 删除文件（文件级操作）
- 恢复模式：浏览 Git 提交历史，选择后回车恢复到指定 commit
- Release 发布：检测到 `changelog.md` 时自动发布 GitHub Release 并删除本地文件
- 自动创建仓库、自动配置远程、冲突时强制推送

- **语言**: Python 3.12+
- **版本**: 2.1.0（定义于 `src/__init__.py`）
- **平台**: Windows only（依赖 `msvcrt`、`shutil.get_terminal_size` 等）
- **外部依赖**: `git` CLI、`gh` CLI（GitHub 官方命令行工具）
- **Python 依赖**: `rich>=13.0`（通过 requirements.txt 管理）

## 架构（四层洋葱模型）

```
src/
├── __init__.py            # 包标识，定义 __version__
├── __main__.py            # 组合根：唯一组装依赖的地方（create_app）
├── config.py              # 常量层：Rich Style 主题、键盘码、布局参数
├── utils.py               # 工具函数：enable_vt100、get_key、get_display_width
│
├── domain/                # 领域层：纯业务，零 I/O
│   ├── exceptions.py      # SyncError 异常体系 + classify_push_error()
│   ├── events.py          # DomainEventBus + 领域事件（ActionLog/SyncCompleted/...）
│   ├── protocols.py       # GitProvider / GitHubProvider 协议（接口定义处）
│   └── state.py           # AppState 状态机（idle/syncing/restoring/cooldown）
│
├── application/           # 应用层：用例编排（不碰 UI / 不碰命令，可单测）
│   ├── sync_service.py    # SyncService：全量同步（扫描→提交→推送→失败恢复→Release）
│   ├── restore_service.py # RestoreService：版本恢复
│   ├── release_service.py # ReleaseService：版本号计算（YYwWWa）+ Release 发布
│   └── file_ops_service.py# FileOpsService：文件级推送/删除/物理删除 + 列表扫描
│
├── infrastructure/        # 基础设施层：适配器（可替换）
│   ├── command.py         # run_command（带超时）+ retry 装饰器（仅只读操作）
│   ├── git_provider.py    # GitCLIProvider：git CLI 实现
│   ├── github_provider.py # GhCLIProvider：gh CLI 实现
│   └── gitignore_parser.py# GitignoreMatcher：完整 gitignore 规范解析
│
└── presentation/          # 表现层：TUI（只渲染 + 按键，零业务逻辑）
    ├── app.py             # App：Rich Live 主循环（纯控制器）+ 事件订阅刷新
    ├── context.py         # AppContext：组合上下文（缓存刷新/后台线程/预加载）
    ├── renderer.py        # RichRenderer：纯渲染（书页双栏/截断/滚动）
    └── modes/             # 模式组件（策略模式）
        ├── base.py        # Mode 协议：handle_key / on_mode_selected
        ├── push_mode.py   # 推送模式组件
        ├── restore_mode.py# 恢复模式组件
        └── registry.py    # ModeRegistry 注册表
```

### 依赖规则

- 依赖只向内：表现层 → 应用层 → 领域层 → 基础设施层；
- **接口定义在领域层（protocols.py），实现在基础设施层**（依赖倒置）；
- UI 永不触碰 git/gh 命令（App/模式组件中无任何 subprocess 调用）；
- 渲染路径零子进程：`build_screen` 只读 `AppState` 缓存；
- 事件驱动：业务层发布事件（DomainEventBus），表现层订阅刷新，替代旧 on_log 回调。

### 扩展性约定

- **新增模式**：实现 Mode 协议（handle_key/on_mode_selected）+ `ModeRegistry.register("名称", 类)` 一行注册，主循环/渲染器/事件总线零改动；
- **更换 git 实现**：实现 GitProvider 协议即可（如 libgit2），上层零改动；
- **新增日志消费者**：订阅 DomainEventBus 对应事件，业务层零改动。

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

> **注意**：如果 `python` 命令不可用，尝试使用 Windows Python 启动器 `py`。

## Development Workflow

```bash
# 语法检查（项目根目录执行）
python -c "import py_compile, glob; [py_compile.compile(f, doraise=True) for f in glob.glob('src/**/*.py', recursive=True)]"

# 运行全部测试（33 个用例，FakeProvider 无需真实 git/gh）
python -m pytest tests/ -v

# 运行应用（同步当前工作目录）
python -m src
```

## Testing Instructions

- 测试文件位于 `tests/`，使用 `pytest`（`tests/fakes.py` 提供内存版 Git/GitHub 协议实现）；
- `test_sync_service.py`：同步流程、失败恢复（仓库不存在/非快进/网络错误）、事件发布；
- `test_release_service.py`：版本号计算纯逻辑（YYwWWa 递增/跨周重置）、发布流程；
- `test_infrastructure.py`：gitignore 解析、命令超时、重试装饰器；
- `test_app_interaction.py`：按键 → 模式组件 → 用例服务 全链路交互；
- 手动验证：`python -m src` 观察同步行为，验证关注点同 v2.0。

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
- 模式选择：启动时默认光标在推送模式，左右键移动光标，回车确认后锁定
- 恢复模式预览：光标聚焦恢复模式（未锁定）即静默预加载提交历史

## Code Style

### 命名规范
- 类名: `PascalCase`（`SyncService`, `GitCLIProvider`, `RichRenderer`）
- 函数/方法: `snake_case`（`refresh_file_list`, `classify_push_error`）
- 常量: `UPPER_SNAKE_CASE`（`STYLE_RED`, `KEY_ENTER`, `COOLDOWN_PERIOD`）
- 私有方法: 前缀 `_`（`_recover_push_failure`, `_scan_changes`）

### 格式约定
- 中文注释和文档字符串
- 颜色使用 `config.py` 中的 Rich `Style` 对象，禁止硬编码 ANSI 转义序列
- 模块间使用相对导入（`from ..domain.events import ...`）
- 分层边界：domain 不 import application/infrastructure/presentation；application 只依赖 domain 协议；presentation 只依赖应用层与领域层

### TUI 渲染规则（继承 v2.0，迁移至 RichRenderer）
- 使用 Rich `Live` 全屏渲染，`refresh_per_second=4`
- 圆角框目标宽度 101 字符，左右栏各 49 保证奇数宽
- 左栏：模式选择导航栏 + 列表区；右栏：状态区 + 日志区
- 恢复模式版本列表整体居中，推送模式文件列表左对齐
- 文件名等宽填充至 `max_name_width`，超宽 `_truncate()` 截断
- 滚动指示器 `...` 在列表超出可见区域时显示
- 超链接使用 Rich `Style(link=url)` 替代手写 OSC 8 序列
- **禁止在渲染路径中执行子进程调用**（`build_screen` 只读缓存）

## Troubleshooting

- **`python` 命令找不到**：使用 `py` 代替，或在 PATH 中添加 Python 安装路径
- **`rich` 模块找不到**：运行 `pip install -r requirements.txt`
- **`gh` 命令找不到**：运行 `winget install --id GitHub.cli`
- **推送失败（认证错误）**：运行 `gh auth login` 重新登录
- **推送失败（仓库不存在）**：SyncService 自动打开浏览器创建仓库并重推
- **终端显示乱码**：使用 Windows Terminal 或支持 VT100 的终端
