# AGENTS.md

## Project Overview

GitHubSync 是一个 Windows 终端同步工具，将本地目录同步到 GitHub 仓库。基于 `git` 和 `gh` CLI 实现全部操作，提供 CLI 子命令与极简交互两种形态（CLI-first）。
- **CLI 子命令**：`status` / `push` / `restore` / `diff` / `info`，POSIX 输出契约（结果走 stdout、诊断走 stderr、isatty 着色、退出码 0/1/2/3）
- **极简交互**：无子命令 + tty 时进入，顶栏常驻 + 内容区刷新，单键循环（`tui/interactive.py`）
- **Release 发布**：检测到 `changelog.md` 时自动发布 GitHub Release
- **自动创建仓库**、自动配置远程；推送 = 本地 1:1 覆盖远程（分叉自动强推），拉取 = 远程 1:1 复刻本地（reset + clean）

- **语言**: Python 3.12+
- **版本**: 3.0.0（定义于 `main.py`）
- **平台**: Windows only（交互模式依赖 `msvcrt`；CLI 子命令不依赖）
- **外部依赖**: `git` CLI、`gh` CLI（GitHub 官方命令行工具）
- **Python 依赖**: 无第三方依赖（纯标准库；markup→ANSI 着色由 `core/ansi.py` 自研实现）

## 架构（CLI/TUI 双薄表现层 + core 业务层）

```
main.py                  # 入口：argparse 调度 + create_services 唯一组装点
pyproject.toml           # 打包：console_scripts githubsync = main:main
github_sync.bat          # Windows 启动器：Set-Location 到脚本目录后 python -m main
│
├── core/                # 业务层：Provider 协议 + 用例服务（不碰 UI / 不碰 argparse）
│   ├── config.py        # 语义色、键盘扫描码（KEY_*）
│   ├── ansi.py          # markup→ANSI 自研解析（[#hex]/[on #hex]/[bold]/[strike]、嵌套、isatty 判定）
│   ├── i18n.py          # tr() 中英双语（按系统语言 / GITHUBSYNC_LANG 覆盖）
│   ├── events.py        # DomainEventBus + ActionLog 事件（业务→表现层解耦）
│   ├── exceptions.py    # SyncError 异常体系 + classify_push_error()
│   ├── protocols.py     # GitProvider / GitHubProvider 协议（接口定义处）
│   ├── status.py        # RepoInfo / RepoStatus + parse_porcelain / decide_status
│   ├── services.py      # Services 组合容器（git/gh/bus/status/sync/restore/file_ops/release）
│   ├── status_service.py# StatusService：CLI 与交互模式的唯一状态来源
│   ├── sync_service.py  # 全量同步（扫描→提交→推送→失败恢复→Release）
│   ├── restore_service.py / release_service.py / file_ops_service.py
│   ├── command.py       # run_command（超时）+ retry 装饰器（仅只读操作）
│   ├── git_provider.py  # GitCLIProvider：git CLI 实现
│   ├── github_provider.py # GhCLIProvider：gh CLI 实现
│   ├── gitignore_parser.py # GitignoreMatcher：完整 gitignore 规范解析
│   └── utils.py         # enable_vt100 / get_key / hide_cursor / get_display_width
│
├── cli/                 # CLI 表现层：argparse + 输出格式化（零业务逻辑）
│   ├── parser.py        # build_parser：子命令 / path / -C / --json 等
│   ├── commands.py      # COMMANDS：各子命令执行函数（返回退出码）
│   ├── output.py        # status_line / format_diff / 着色
│   └── exit_codes.py    # EXIT_OK / EXIT_CHANGES / EXIT_DIVERGED / EXIT_FAILED
│
├── tui/                 # 交互表现层：渲染纯函数 + 单键循环（零业务逻辑、零子进程）
│   ├── screen.py        # render_header / render_menu / render_status_line 纯函数
│   ├── interactive.py   # InteractiveApp：顶栏常驻 + 内容区刷新的主循环
│   ├── files_view.py    # 文件视图：↑↓ 移动，Enter 切换推送/忽略
│   ├── restore_view.py  # 拉取视图：本地历史提交，首个 Enter 对齐远程，其余恢复
│   └── renderer.py      # DiffRenderer / markup_to_ansi
│
└── tests/               # pytest（fakes.py 内存版 Provider，无需真实 git/gh）
```

### 依赖规则

- 业务在 core，表现层在 cli/tui，两层都只依赖 core；core 不 import cli/tui；
- **接口定义在 core/protocols.py，实现在 core/git_provider.py / github_provider.py**（依赖倒置，可替换实现）；
- UI 永不触碰 git/gh 命令（tui/ 与 cli/ 中无 subprocess 调用，全部走 core 服务）；
- 渲染路径零子进程：`tui/screen.py` 纯函数只读 RepoInfo；
- 事件驱动：core 服务发布事件（DomainEventBus），表现层订阅刷新；交互模式取消订阅 ActionLog（同步操作无回显，结果由视图状态标记/颜色表达），CLI 仍按 stdout/stderr 契约输出。

### 扩展性约定

- **新增 CLI 子命令**：cli/parser.py 注册 + cli/commands.py 实现，main.py 零改动；
- **更换 git 实现**：实现 GitProvider 协议即可（如 libgit2），上层零改动；
- **新增日志消费者**：订阅 DomainEventBus 对应事件，业务层零改动。

## Setup Commands

```bash
# 安装 gh CLI（GitHub 官方工具）
winget install --id GitHub.cli

# 登录 GitHub
gh auth login

# 安装为全局命令（任意目录敲 githubsync 即同步当前目录）
pip install -e .

# 运行交互模式（同步当前目录，无子命令 + tty 时进入）
python -m main

# 运行交互模式（同步指定目录）
python -m main "C:\path\to\project"

# 运行 CLI 子命令（同步当前目录）
python -m main status
python -m main push --yes

# Windows 启动器（同步脚本所在目录）
github_sync.bat
```

> **注意**：如果 `python` 命令不可用，尝试使用 Windows Python 启动器 `py`。

## Development Workflow

```bash
# 语法检查（项目根目录执行）
python -c "import py_compile, glob; [py_compile.compile(f, doraise=True) for f in glob.glob('main.py') + glob.glob('cli/**/*.py', recursive=True) + glob.glob('core/**/*.py', recursive=True) + glob.glob('tui/**/*.py', recursive=True)]"

# 运行全部测试（102 个用例，FakeProvider 无需真实 git/gh）
python -m pytest tests/ -v

# 运行交互模式（同步当前工作目录）
python -m main
```

## Testing Instructions

- 测试文件位于 `tests/`，使用 `pytest`（`tests/fakes.py` 提供内存版 Git/GitHub 协议实现）；
- `test_cli.py`：子命令路由、退出码、--json、stdout/stderr 分流、isatty 无 ANSI；
- `test_status_service.py`：porcelain 解析、状态判定（clean/changed/ahead/behind/diverged）；
- `test_sync_service.py`：同步流程、失败恢复（仓库不存在/非快进/网络错误）、事件发布；
- `test_release_service.py`：版本号计算纯逻辑（YYwWWa 递增/跨周重置）、发布流程；
- `test_infrastructure.py`：gitignore 解析、命令超时、重试装饰器；
- `test_interactive.py`：渲染纯函数、推荐动作映射、菜单光标（← → + Enter）、主循环与视图交互（Enter 执行选中项、Backspace 返回）；
- `test_renderer.py`：markup→ANSI 转换；
- 手动验证：`python -m main` 观察同步行为（交互模式无退出键，直接关闭窗口）。

## Keyboard Shortcuts

| 按键 | 功能 |
|---|---|
| `←` `→` | 移动菜单光标（推送 / 拉取 / 文件，循环移动），`[ ]` 框选当前选中项 |
| `Enter` | 执行光标选中的菜单项（推送 / 拉取 / 文件视图），初始光标停在推荐动作上 |
| `↑` `↓` | 子视图内移动选中项（文件 / 拉取历史列表） |
| `o` | 在浏览器中打开远程仓库（隐藏快捷键，不进菜单） |
| `Backspace` / `Esc` | 从子视图返回主屏 |

- 导航栏固定三项：`推送` `拉取` `文件`（三项槽位等宽，`_MENU_SLOT` 按语言动态计算 = 最大内容（括号 2 + `*` 2 + 最长文本）+ 2：中文 10 / 英文 11，最密集时相邻间隙恒 2 格；内容槽内居中，仅选中项括号可见如 `[推送]` + `#636363` 底色紧贴内容、两侧各留 1 格（宽 = 内容 + 2），未选中项为裸文本无括号；框选左右移动、`*` 同步标记增减只改槽内留白，其他选项位置零偏移，行总宽恒 3×槽位，分叉时不再切换为恢复/强制推送）；推送 / 拉取有新的同步时文本两侧加 `*`（如 `*推送*`，选中时 `[*推送*]`，由 `_has_sync()` 判定：CHANGED/AHEAD/NO_REPO/NO_REMOTE/DIVERGED 标记推送，BEHIND/DIVERGED 标记拉取）
- 拉取视图（`restore_view.py`）：本地最近 20 条提交列表（最新在前），光标默认首个——Enter 对齐远程（fetch + reset --hard origin/分支 + clean -fd，本地 1:1 复刻远程，丢弃本地已提交独有内容与未跟踪文件）；其余提交 Enter 恢复到该历史版本（无二次确认）；无提交时提示并返回
- 菜单渲染见 `tui/screen.py`：`MENU_ITEMS` 定义项序（即 ← → 移动顺序），`menu_for_action()` 把推荐动作映射为初始光标落点（diff/refresh 无菜单项，落推送）
- 操作执行后有 1 秒冷却期，防止误触
- 退出无专用按键：直接关闭终端窗口即可（Ctrl+C 兜底）
- Enter 执行光标选中项，菜单不标注键位

## Code Style

### 命名规范
- 类名: `PascalCase`（`SyncService`, `GitCLIProvider`, `InteractiveApp`）
- 函数/方法: `snake_case`（`refresh_file_list`, `classify_push_error`）
- 常量: `UPPER_SNAKE_CASE`（`COLOR_ERROR`, `KEY_ENTER`, `EXIT_FAILED`）
- 私有方法: 前缀 `_`（`_recover_push_failure`, `_scan_changes`）

### 格式约定
- 中文注释和文档字符串
- 颜色使用 `core/config.py` 中的颜色常量（markup 标签如 `[#3FB950]`，由 `core/ansi.py` 转 ANSI），禁止硬编码 ANSI 转义序列
- 模块间使用相对导入（`from ..domain.events import ...` 仅旧版；当前用 `from core.xxx import ...`）
- 分层边界：core 不 import cli/tui；cli/tui 只依赖 core 服务与协议

### TUI 渲染规则（顶栏常驻 + 内容区刷新）
- 顶栏（`render_header`）只绘制一次：项目 / 分支·状态 / 主页 / 空行 / 菜单块 / 空行
- 状态行变化 → `\x1b[2;1H\x1b[2K` 定点重写；菜单高亮变化 → `_redraw_menu` 定点重绘
- 内容区变化 → `\x1b[{H+1};1H\x1b[J` 定位清除后重绘；内容相同 → 零输出
- 输出行数受可用高度限制（`_content_rows`），超屏截断保留末尾，防止终端滚动顶掉顶栏
- 行首统一缩进 2 空格；文件名/列表超宽 `_truncate()` 截断
- **禁止在渲染路径中执行子进程调用**（`build_screen`/`render_*` 只读缓存）

### 无回显化（同步操作结果由视图状态表达）
- 推送：`InteractiveApp._push` 状态机——按 Enter 后 `_push_state` 接管视图，所有待推文件标记 `[·]`（灰，上传中）→ 成功 `[✓]`（绿）/ 失败 `[✕]`（红），停留 1 秒后交还主循环；git 仍为一次 commit + push
- 拉取：`RestoreView` 通过 `GitProvider.remote_head()` 取远程跟踪引用，本地与远程一致的提交 hash 标浅绿 `COLOR_CYAN`（#ABDFA7，与 [✓] 同色），其余不变色
- 文件视图：`FileOpsService.push_file/remove_file` 返回 bool，失败文件行首 `[!]`（红），按钮状态切换即成功指示
- 失败原因完全无回显：`[✕]`/`[!]` 即全部反馈（排查用 CLI `status`）

## Troubleshooting

- **`python` 命令找不到**：使用 `py` 代替，或在 PATH 中添加 Python 安装路径
- **`gh` 命令找不到**：运行 `winget install --id GitHub.cli`
- **推送失败（认证错误）**：运行 `gh auth login` 重新登录
- **推送失败（仓库不存在）**：SyncService 自动打开浏览器创建仓库并重推
- **推送被拒绝（分叉）**：自动强推（本地 1:1 覆盖远程，丢弃远程独有提交）；强推仍被拒（如分支保护）时报错，改用 `githubsync restore --remote` 对齐远程
- **终端显示乱码**：使用 Windows Terminal 或支持 VT100 的终端
