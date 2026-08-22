# AGENTS.md

## Project Overview

GitHubSync 是一个 Windows 终端同步工具，将本地目录同步到 GitHub 仓库。基于 `git` 和 `gh` CLI 实现全部操作，提供 CLI 子命令与极简交互两种形态（CLI-first）。
- **CLI 子命令**：`status` / `push` / `restore` / `diff` / `info` / `switch`，POSIX 输出契约（结果走 stdout、诊断走 stderr、isatty 着色、退出码 0/1/2/3）
- **极简交互**：无子命令 + tty 时进入，顶栏常驻 + 内容区刷新，标签页单循环（`tui/interactive.py`）
- **Release 发布**：检测到 `changelog.md` 时自动发布 GitHub Release（YYwWWa 版本号）。changelog.md 不入库（gitignore 隔离），本地存在非空即触发发布；推送列表注入显示 changelog 行保持可见（置底），工作区干净时顶栏 `*推送*` 标记仍出现；旧版已入库残留首次同步自动 `git rm --cached`（本地保留）随推送清掉远端；发布成功后删除本地文件，无远端残留
- **自动创建仓库**、自动配置远程；推送 = 本地 1:1 覆盖远程当前分支（分叉自动强推；仅建仓初始化时改名一次 main，此后同步不动分支名），拉取 = 远程 1:1 复刻本地（reset + clean）

- **语言**: Python 3.12+
- **版本**: 3.0.0（定义于 `main.py`）
- **平台**: Windows only（交互模式依赖 `msvcrt`；CLI 子命令不依赖）
- **外部依赖**: `git` CLI、`gh` CLI（GitHub 官方命令行工具）
- **Python 依赖**: 无第三方依赖（纯标准库；markup→ANSI 着色由 `core/ansi.py` 自研实现）

## 架构（CLI/TUI 双薄表现层 + core 业务层）

```
main.py                  # 入口：argparse 调度 + create_services 唯一组装点
pyproject.toml           # 元数据（无全局命令；GITHUBSYNC_REPO 环境变量仅 github_sync.bat 层读写）
github_sync.bat          # Windows 启动器（纯批处理，零 PowerShell）：主场三文件判定（同目录 main.py + cli\parser.py + core\protocols.py 齐全）则 setx 幂等持久化 GITHUBSYNC_REPO 到用户环境并同步本目录；便携副本读变量（进程内缺失回退用户注册表）定位代码、同步 bat 所在目录，均未设报错退出码 3
│
├── core/                # 业务层：Provider 协议 + 用例服务（不碰 UI / 不碰 argparse）
│   ├── config.py        # 语义色、键盘扫描码（KEY_*）
│   ├── ansi.py          # markup→ANSI 自研解析（[#hex]/[on #hex]/[bold]/[strike]/[link]、嵌套、isatty 判定）
│   ├── i18n.py          # tr() 中英双语（按系统语言 / GITHUBSYNC_LANG 覆盖）
│   ├── events.py        # DomainEventBus + ActionLog 事件（业务→表现层解耦）
│   ├── file_logger.py   # 文件日志：事件 + 命令详情落盘项目根 logs/ 会话文件（所有项目调用统一汇聚，logs/ 入 .gitignore）
│   ├── exceptions.py    # SyncError 异常体系 + classify_push_error()
│   ├── protocols.py     # GitProvider / GitHubProvider 协议（接口定义处；ahead_behind_upstream() 为 @{u} 无参形式）
│   ├── status.py        # RepoInfo / RepoStatus + parse_porcelain / decide_status
│   ├── services.py      # Services 组合容器（git/gh/bus/status/sync/restore/file_ops/release）
│   ├── status_service.py# StatusService：CLI 与交互模式的唯一状态来源（只读 git 调用 ThreadPoolExecutor 一波并行）
│   ├── sync_service.py  # 全量同步（扫描→提交→推送→失败恢复→Release）
│   ├── restore_service.py / release_service.py / file_ops_service.py
│   ├── command.py       # run_command / run_command_stream（超时）+ retry 装饰器（仅只读操作）+ 命令日志钩子
│   ├── executor.py      # Inline/Thread 双实现（submit(fn, callback)；callback 在 worker 线程触发，仅允许线程安全操作如 queue.put，禁止 ANSI 渲染与事件发布）
│   ├── git_provider.py  # GitCLIProvider：git CLI 实现（ahead_behind_upstream 走 HEAD...@{u}，get_status 无 remote 子进程）
│   ├── github_provider.py # GhCLIProvider：gh CLI 实现
│   ├── gitignore_parser.py # GitignoreMatcher：完整 gitignore 规范解析
│   ├── push_progress.py# push 进度解析（parse_progress 纯函数：git push --progress 行 → 紧凑进度文本）
│   └── utils.py         # get_key / poll_key（kbhit 轮询，默认 50ms）/ hide_cursor / get_display_width（VT100 启用在 ansi.py）
│
├── cli/                 # CLI 表现层：argparse + 输出格式化（零业务逻辑）
│   ├── parser.py        # build_parser：子命令 / path / -C / --json 等
│   ├── commands.py      # COMMANDS：各子命令执行函数（返回退出码）
│   ├── output.py        # status_line / 着色（format_diff 已下沉 core/status.py）
│   └── exit_codes.py    # EXIT_OK / EXIT_CHANGES / EXIT_DIVERGED / EXIT_FAILED
│
├── tui/                 # 交互表现层：渲染纯函数 + 标签页视图（零业务逻辑、零子进程）
│   ├── screen.py        # render_header / render_menu / render_status_line 纯函数
│   ├── interactive.py   # InteractiveApp：骨架首帧（info=None 零 I/O）+ 非阻塞主循环（poll_key 轮询 + queue 脏标志 drain）+ 状态/版本后台加载 + 顶栏常驻 + 标签页单循环派发
│   ├── view_base.py     # ViewBase：activate/render/handle_key/invalidate + loading 态（executor 后台加载）
│   ├── push_view.py     # 推送标签页：推送会话一页流（会话头 + 阶段摘要横排 + 实时日志流窗口）
│   ├── pull_view.py     # 拉取标签页：本地历史提交，首个 Enter 对齐远程，其余恢复
│   ├── files_view.py    # 文件标签页：↑↓ 移动，Enter 切换推送/忽略
│   ├── branch_view.py   # 分支标签页：首行合并到 main，下方分支列表 Enter 切换
│   └── renderer.py      # markup_to_ansi
│
└── tests/               # pytest（fakes.py 内存版 Provider，无需真实 git/gh）
```

### 标签页视图契约（ViewBase）

- 构造接受 `executor` / `on_loaded` 关键字参数（生产 ThreadExecutor 后台线程，测试默认 InlineExecutor 同步执行，保证确定性）；
- `activate()`：切入时调用，首次或失效后才经 executor 踢后台 `_load()`（懒加载 + loading 态），缓存命中零扫描；加载完成回调置标记并触发 `on_loaded`（回调在 worker 线程触发，仅允许线程安全操作如 queue.put，ANSI 输出只在主线程）；
- `render()`：缓存数据 → 内容区文本，纯函数零 I/O；loading 期间返回空串（留白不显示）；
- `handle_key(key)`：处理 ↑/↓/Enter，返回需失效的视图 id 列表，主循环统一 `invalidate()` 并对当前视图立即重扫；loading 期间守卫返回 `[]`（含 Enter——空数据不得触发操作）；
- `deactivate()`：切出时调用（默认无操作；PushView 会话视图切出保留，可切回查看）；
- 状态签名（status/change_count/ahead/behind）变化时主循环失效推送与拉取视图，当前视图立即重扫。

### 依赖规则

- 业务在 core，表现层在 cli/tui，两层都只依赖 core；core 不 import cli/tui；
- **接口定义在 core/protocols.py，实现在 core/git_provider.py / github_provider.py**（依赖倒置，可替换实现）；
- UI 永不触碰 git/gh 命令（tui/ 与 cli/ 中无 subprocess 调用，全部走 core 服务）；
- 渲染路径零子进程：`tui/screen.py` 纯函数只读 RepoInfo；
- 事件驱动：core 服务发布事件（DomainEventBus），表现层订阅刷新；交互模式中 PushView 订阅带 stage 标识的 ActionLog 做结构化阶段回显（PROGRESS 级别实时更新阶段详情，如扫描文件数/提交数/push 对象写入百分比；CLI 纯文本消费者忽略 stage），CLI 仍按 stdout/stderr 契约输出；`core/file_logger.py` 在组合根订阅全部事件 + `core/command.py` 命令钩子，把 TUI 无回显的日志与命令详情统一落盘项目根 `logs/githubsync-<时间戳毫秒>.log`（每次运行一个新会话文件，CLI/TUI、任何被同步项目都汇聚到此目录；`logs/` 由 GitHubSync 自身 .gitignore 排除；1MB 轮转，写失败静默）。

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

# 运行交互模式（无子命令 + tty 时进入；目录来源优先级：-C > 位置参数 > 当前目录）
python -m main

# 运行交互模式（同步指定目录，位置参数）
python -m main "C:\path\to\project"

# 运行 CLI 子命令（目录来源同上）
python -m main status
python -m main push --yes

# Windows 启动器（纯批处理，零 PowerShell；主场 = 同目录 main.py + cli\parser.py + core\protocols.py 齐全，setx 幂等持久化 GITHUBSYNC_REPO 到用户环境并同步本目录；便携副本读变量含注册表回退定位代码、同步 bat 所在目录，均未设报错退出码 3）
github_sync.bat
```

> **注意**：如果 `python` 命令不可用，尝试使用 Windows Python 启动器 `py`。

## Development Workflow

```bash
# 语法检查（项目根目录执行）
python -c "import py_compile, glob; [py_compile.compile(f, doraise=True) for f in glob.glob('main.py') + glob.glob('cli/**/*.py', recursive=True) + glob.glob('core/**/*.py', recursive=True) + glob.glob('tui/**/*.py', recursive=True)]"

# 运行全部测试（FakeProvider 无需真实 git/gh）
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
- `test_interactive.py`：渲染纯函数、推荐动作映射、标签切换（← → 即显内容免 Enter）、主循环与视图交互；
- `test_views.py`：标签页视图协议——懒加载（activate 幂等/失效重扫，FakeProvider 计数器断言）、handle_key 状态转移、渲染对齐；
- 手动验证：`python -m main` 观察同步行为（交互模式无退出键，直接关闭窗口）。

## Keyboard Shortcuts

| 按键 | 功能 |
|---|---|
| `←` `→` | 循环切换标签页（推送 / 拉取 / 文件 / 分支），切换即显示内容（免 Enter），`[ ]` 框选当前标签 |
| `Enter` | 执行当前标签内选中项（推送 / 对齐远程·恢复历史 / 切换忽略 / 合并到 main·切换分支），初始标签停在推荐动作上 |
| `↑` `↓` | 标签内移动选中项（文件 / 拉取历史 / 分支列表） |
| `o` | 在浏览器中打开远程仓库（隐藏快捷键，不进菜单） |

- 顶栏版本号是 OSC 8 超链接（目标 = 仓库 Releases 页面）：支持超链接的终端（Windows Terminal 等）中 Ctrl+点击直接打开，与主页 URL 的终端原生交互一致；程序零感知点击事件

- Backspace / Esc 已废弃：按无效键处理（零输出），导航全靠 ← →
- 导航栏固定四项：`推送` `拉取` `文件` `分支`（四项槽位等宽，`_MENU_SLOT` 按语言动态计算 = 最大内容（括号 2 + `*` 2 + 最长文本）+ 2：中文 10 / 英文 12，最密集时相邻间隙恒 2 格；内容槽内居中，仅选中项括号可见如 `[推送]` + `#636363` 底色紧贴内容、两侧各留 1 格（宽 = 内容 + 2），未选中项为裸文本无括号；框选左右移动、`*` 同步标记增减只改槽内留白，其他选项位置零偏移，行总宽恒 4×槽位，分叉时不再切换为恢复/强制推送）；推送 / 拉取有新的同步时文本两侧加 `*`（如 `*推送*`，选中时 `[*推送*]`，由 `_has_sync()` 判定：CHANGED/AHEAD/NO_REPO/NO_REMOTE/DIVERGED 标记推送，BEHIND/DIVERGED 标记拉取；分支项无 `*` 概念）
- 分支标签页（`branch_view.py`）：本地分支列表，当前分支名浅绿 `COLOR_CYAN`；首行固定「合并到 main」（仅当前分支 ≠ main 时出现）——Enter 执行 checkout main → merge → push，冲突自动 merge --abort + 切回原分支并标 `[✕]`；分支行 Enter 切换（当前分支行无操作）；脏区（有未提交变更）Enter 一律标 `[!]` 拒绝；切换/合并成功返回全部视图 id 统一失效重扫；新建分支只走 CLI `switch -c`（TUI 无文本输入机制）
- 拉取标签页（`pull_view.py`）：本地最近 20 条提交列表（最新在前），光标默认首个——Enter 对齐远程（fetch + reset --hard origin/分支 + clean -fd，本地 1:1 复刻远程，丢弃本地已提交独有内容与未跟踪文件）；其余提交 Enter 恢复到该历史版本（无二次确认）；无提交时显示提示文本
- 菜单渲染见 `tui/screen.py`：`MENU_ITEMS` 定义项序（即 ← → 切换顺序），`menu_for_action()` 把推荐动作映射为初始标签落点（diff/refresh 无标签项，落推送）
- 操作执行后有 1 秒冷却期，防止误触
- 退出无专用按键：直接关闭终端窗口即可（Ctrl+C 兜底）
- Enter 执行当前标签内选中项，菜单不标注键位

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
- 顶栏（`render_header`）：启动首帧立即渲染骨架（`info=None`，7 行：项目行 + 留白状态行 + 菜单块，零 I/O）；git 状态与 gh Release tag 由后台线程加载，到达后更新为完整布局（项目 / 分支·状态 / 主页 / 版本 / 空行 / 菜单块 / 空行；版本行 tag 文本包 `[link <releases_url> …]` markup，由 `core/ansi.py` 渲染为 OSC 8 超链接供终端 Ctrl+点击；无远程不渲染主页与版本行）
- 状态行变化 → `\x1b[2;1H\x1b[2K` 定点重写；菜单高亮变化 → `_redraw_menu` 定点重绘
- 内容区变化 → `\x1b[{H+1};1H\x1b[J` 定位清除后重绘；内容相同 → 零输出
- 输出行数受可用高度限制（`_content_rows`），超屏截断保留末尾，防止终端滚动顶掉顶栏
- 行首统一缩进 2 空格；文件名/列表超宽 `_truncate()` 截断
- **禁止在渲染路径中执行子进程调用**（`build_screen`/`render_*` 只读缓存）

### 无回显化（同步操作结果由视图状态表达）
- 推送：`PushView`（`tui/push_view.py`）推送会话一页流视图——按 Enter 后按状态预构建阶段清单（init/config/scan/commit/push/release），一页内同时呈现：竖排阶段行（每阶段一行 `  ✓ Scan`，状态符号 `·` 未开始 / `…` 进行中 / `✓` 完成 / `✕` 失败 / `-` 未执行 + 英文短名，对齐清楚；无会话时 Scan 行显示工作区变更数 `· Scan 2 change(s)`，按 Enter 前即可确认本次变更，推送过程阶段行只显示符号变化）、动作行（阶段行下方固定一行，覆盖式显示当前动作 `> 推送到 GitHub`，不累积不滚动，结束即显示最后结果 `✓ 推送完成（N 项更改）` / `✕ 失败原因`）；`git push --progress` 经 `run_command_stream` 流式解析，PROGRESS 事件只更新内部 detail 不渲染，避免进度刷屏；git 仍为一次 commit + push
- 拉取：`PullView`（`tui/pull_view.py`）通过 `GitProvider.remote_head()` 取远程跟踪引用，本地与远程一致的提交 hash 标浅绿 `COLOR_CYAN`（#ABDFA7，与 [✓] 同色），其余不变色
- 文件标签页：`FileOpsService.push_file/remove_file` 返回 bool，失败文件行首 `[!]`（红），按钮状态切换即成功指示
- 失败原因由 i18n 可读消息表达（`推送失败: 网络连接异常…`），原始命令输出落盘 logs/ 供 AI 调试（排查用 CLI `status`）

## Troubleshooting

- **`python` 命令找不到**：使用 `py` 代替，或在 PATH 中添加 Python 安装路径
- **`gh` 命令找不到**：运行 `winget install --id GitHub.cli`
- **推送失败（认证错误）**：运行 `gh auth login` 重新登录
- **推送失败（仓库不存在）**：SyncService 自动打开浏览器创建仓库并重推
- **推送被拒绝（分叉）**：自动强推（本地 1:1 覆盖远程，丢弃远程独有提交）；强推仍被拒（如分支保护）时报错，改用 `githubsync restore --remote` 对齐远程
- **终端显示乱码**：使用 Windows Terminal 或支持 VT100 的终端
