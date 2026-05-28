# GitHubSync Rich 重构设计文档

**日期**: 2026-05-28
**状态**: 已细化，待审阅
**方案**: Rich Live 驱动 + 多文件模块化

## 1. 重构目标

将 GitHubSync 从单文件 ~1150 行手写 ANSI TUI 重构为基于 Rich 库的模块化架构，提升代码可维护性，同时保持核心功能和交互体验不变，并借助 Rich 能力做合理增强。

## 2. 决策记录

| 决策项 | 选择 | 理由 |
|---|---|---|
| 重构范围 | 全面重构 | 用户选择 |
| 文件结构 | 多文件模块化 | 职责清晰，易维护 |
| 平台支持 | 仅 Windows | 保持现状，依赖 msvcrt |
| 键盘输入 | 保留 msvcrt | Rich 不处理键盘，msvcrt 稳定可靠 |
| UI 演进 | 核心不变 + 合理增强 | 利用 Rich 的 Spinner、更好的着色等 |
| 依赖管理 | requirements.txt | 简单直接 |
| 渲染方案 | Rich Live 驱动 | 消除 ~200 行手写 ANSI 渲染代码 |

## 3. 模块结构

```
GitHubSync/
├── github_sync/
│   ├── __init__.py          # 包标识，版本常量
│   ├── __main__.py          # 入口：python -m github_sync [目录]
│   ├── config.py            # 常量：颜色主题、键盘码、超时设置
│   ├── utils.py             # 工具函数：run_command()、get_input_with_default()
│   ├── git_manager.py       # GitManager 类（从单文件抽出，逻辑不变）
│   └── app.py               # App 类：Rich Live 驱动的主 TUI
├── run_sync.bat             # 启动器（更新为 python -m github_sync）
├── requirements.txt         # rich>=13.0
├── AGENTS.md
├── AGENTS.py
└── changelog.md
```

### 3.1 config.py (~30 行)

Catppuccin Mocha 颜色主题用 Rich `Style` 对象定义：

```python
from rich.style import Style

# 颜色主题
STYLE_RESET     = Style()
STYLE_BOLD      = Style(bold=True)
STYLE_DIM       = Style(dim=True)
STYLE_RED       = Style(color="#F38BA8")
STYLE_GREEN     = Style(color="#A6E3A1")
STYLE_YELLOW    = Style(color="#F9E2AF")
STYLE_BLUE      = Style(color="#89B4FA")
STYLE_GRAY      = Style(color="#6C7086")
STYLE_WHITE     = Style(color="#CDD6F4")
STYLE_STRIKE    = Style(strike=True)
STYLE_SELECTED  = Style(bgcolor="#31748F", bold=True, color="#CDD6F4")
STYLE_LINK      = Style(color="#89B4FA", underline=True)

# 日志样式
STYLE_LOG_SUCCESS = Style(color="#A6E3A1", bold=True)
STYLE_LOG_ERROR   = Style(color="#F38BA8", bold=True)
STYLE_LOG_WARN    = Style(color="#F9E2AF", bold=True)
STYLE_LOG_INFO    = Style(color="#89B4FA", bold=True)

# 键盘扫描码
KEY_UP    = b"H"
KEY_DOWN  = b"P"
KEY_LEFT  = b"K"
KEY_RIGHT = b"M"
KEY_ENTER = b"\r"
KEY_ESC   = b"\x1b"
KEY_Q     = b"q"
KEY_O     = b"o"

# 超时设置
IDLE_TIMEOUT = 60        # 无操作自动退出（秒）
COOLDOWN_PERIOD = 1.0    # 操作冷却期（秒）

# 布局尺寸
STATUS_PANEL_HEIGHT = 6  # 状态面板固定行数
LOG_PANEL_HEIGHT = 8     # 日志面板固定行数
```

### 3.2 utils.py (~60 行)

- `enable_vt100()` — 调用 `os.system("")` 启用 Windows VT100 终端处理
- `run_command(cmd, cwd=None)` — 子进程执行封装，返回 `(returncode, stdout, stderr)`
- `get_input_with_default(prompt, default_val)` — 带预填充文本的输入框，基于 msvcrt
- `get_key()` — 非阻塞按键读取，处理 Windows 扩展键前缀

### 3.3 git_manager.py (~400 行)

从 `github_sync.py` 原样抽出 `GitManager` 类，逻辑不变，仅调整接口签名。

#### 构造函数

```python
class GitManager:
    def __init__(self, cwd: str, on_log: Callable[[], None] | None = None)
```
- `cwd`: 同步目标目录的绝对路径
- `on_log`: 日志回调，每次 `self.log()` 时调用，App 传入 `live.update` 触发重绘
- 实例变量：`self.updated_items: dict[str, str]`（`{文件名: 'A'|'D'}`），`sync()` 时填充

#### 公共方法

```python
def get_status(self) -> dict
```
返回值：
```python
# 未初始化
{"initialized": False}
# 已初始化
{"initialized": True, "branch": "main", "remote": "https://github.com/user/repo"}
# remote 未配置时值为 "未配置"
```
逻辑：检查 `.git` 目录存在 → `git rev-parse --abbrev-ref HEAD` 取分支（回退 `git branch --show-current`，默认 `"main"`）→ `git remote -v` 取 origin URL。

```python
def init_repo(self) -> None
```
在 `cwd` 执行 `git init`，日志 "正在初始化 Git 仓库" / "Git 仓库初始化成功"。

```python
def sync(self) -> None
```
核心同步流程，10 步：
1. `create_ignore()` — 创建默认 `.gitignore`（如不存在）
2. `get_status()` — 未初始化则 `init_repo()`
3. `git add .` — 暂存所有文件
4. `git status --porcelain` — 解析变更文件，填充 `self.updated_items`
5. `git commit -m "Update: {时间戳}"` — 提交（自动配置 git identity 如缺失）
6. 检查远程配置 — 未配置则 `configure_remote()`
7. `git branch -M main` + `git push -u origin main`
8. 推送失败（仓库不存在）→ `create_github_repo()` → 重新推送
9. 推送被拒绝（冲突）→ `git pull --rebase` → 重新推送
10. 以上均失败 → `force_push()`

成功推送后自动调用 `publish_release()`。

可能产生的日志条目：

| 日志 | 类型 | 触发条件 |
|---|---|---|
| 正在扫描 | INFO | 始终 |
| 正在提交 | INFO | 有变更 |
| 没有更改需要提交 | INFO | 无变更 |
| 正在推送 GitHub | INFO | 推送前 |
| 同步成功 | SUCCESS | 推送成功 |
| 检测到冲突，尝试自动合并 | WARN | push rejected |
| 强制推送成功 | SUCCESS | force push 成功 |
| 推送失败：{原因} | ERROR | 所有推送均失败 |

```python
def create_github_repo(self) -> bool
```
1. 从 `cwd` 目录名推导仓库名，`gh api user` 取 GitHub 用户名
2. `webbrowser.open(f"https://github.com/new?name={repo_name}")` 打开浏览器
3. 每 3 秒轮询 `gh repo view {username}/{repo_name}`（最长 5 分钟）
4. 每次轮询调用 `self.on_log()` 触发 UI 重绘
5. 检测到仓库存在后：`git remote add origin {url}`（或 `set-url`）
6. 返回 `True`（成功）/ `False`（超时或无用户名）

```python
def force_push(self) -> None
```
1. `git push -u origin main --force`
2. 失败时调用 `_parse_push_error()` 翻译错误消息
3. 日志 "强制推送成功" 或 "推送失败：{中文原因}"

```python
def publish_release(self) -> None
```
1. 检查 `changelog.md` 是否存在且非空
2. 生成版本号：`{年份}w{ISO周数}{字母后缀}`（如 `25w22a`，同周递增 b/c/d...）
3. `gh release create {version} --notes-file changelog.md`
4. 成功/失败日志，失败不阻塞主流程

```python
def get_latest_release(self) -> str | None
```
`gh release list --repo {slug} --limit 1`，返回最新版本号字符串或 `None`。

```python
def configure_remote(self) -> None
```
尝试通过 `get_input_with_default()` 让用户输入远程 URL，或自动通过 `create_github_repo()` 创建。

#### 私有方法

```python
def _parse_push_error(self, error_msg: str) -> Text
```
大小写不敏感匹配关键词，返回 Rich `Text` 对象：

| 关键词 | 返回文本 |
|---|---|
| `recv failure` / `connection` / `failed to connect` | 网络连接失败，请检查网络后重试 |
| `could not resolve host` | DNS 解析失败 |
| `timeout` | 连接超时 |
| `authentication failed` / `403` | 认证失败，请运行 `gh auth login` |
| `repository not found` / `404` | 仓库不存在 |
| `rejected` + `non-fast-forward` | 推送被拒绝（远程有新提交） |
| `schannel` / `certificate` / `ssl` | SSL 证书验证失败 |
| `everything up-to-date` | 无需推送 |
| 无法匹配 | 原始英文信息 |

```python
def log(self, message: str, level: str = "INFO") -> None
```
添加日志条目到 `self.log_entries` 列表，调用 `self.on_log()` 回调。`level` 取值：`INFO` / `SUCCESS` / `ERROR` / `WARN`。

#### 辅助方法（原样保留）

- `create_ignore()` — 创建默认 `.gitignore`
- `add_to_gitignore(item_name)` — 追加条目
- `remove_from_gitignore(item_name)` — 删除条目
- `get_github_username()` — `gh api user --jq .login`
- `get_repo_slug()` — 从 remote URL 解析 `user/repo`

### 3.4 app.py (~400 行)

Rich Live 驱动的主 TUI 应用。

#### 构造函数

```python
class App:
    def __init__(self, repo_path: str)
```

| 实例变量 | 类型 | 初始值 | 说明 |
|---|---|---|---|
| `git` | `GitManager` | `GitManager(repo_path, on_log=self._on_git_log)` | Git 操作管理 |
| `running` | `bool` | `True` | 主循环控制标志 |
| `selected_index` | `int` | `0` | 文件列表当前选中行 |
| `action_index` | `int` | `0` | 焦点：0=文件名，1=操作按钮 |
| `file_items` | `list[dict]` | `[]` | 文件列表数据（由 `refresh_file_list()` 填充） |
| `first_sync_done` | `bool` | `False` | 首次同步是否完成 |
| `deadline` | `float` | `time.time() + 60` | 自动退出截止时间 |
| `timeout_seconds` | `int` | `60` | 倒计时显示值 |
| `operation_in_progress` | `bool` | `False` | 操作执行锁 |
| `cooldown_until` | `float` | `0` | 冷却期截止时间 |
| `_cached_status` | `dict \| None` | `None` | git 状态缓存 |
| `_cached_release` | `str \| object` | `None` | release 版本缓存 |
| `_cache_miss_sentinel` | `object` | `object()` | 区分"未缓存"与"缓存值为 None" |
| `console` | `Console` | `Console()` | Rich 控制台实例 |

#### 文件列表数据模型

`self.file_items` 是一个 `list[dict]`，每个条目：

```python
{
    "name": str,           # 文件或目录名
    "ignored": bool,       # 是否在 .gitignore 中
    "action_text": str,    # "推送"（已忽略的文件）或 "删除"（正常文件）
    "tag_text": str,       # "(已忽略)" 或 ""
}
```

与当前相比，去掉了 `width`、`fixed_width`、`action` lambda——Rich Table 自动处理列宽和对齐，操作通过 `selected_index` 索引分发而非 lambda 闭包。

#### 方法清单

**生命周期方法：**

```python
def run(self) -> None
```
主入口。流程：
1. `enable_vt100()`
2. `GitManager` 初始化
3. 首次同步（`self.git.sync()`，设 `first_sync_done = True`）
4. `_refresh_caches()`
5. `refresh_file_list()`
6. 进入 `Live` 上下文，启动主循环
7. 退出清理：`console.print()` 打印退出信息

**渲染方法（均返回 `RenderableType`）：**

```python
def build_screen(self) -> Layout
```
组合四个区域为 `Layout`：
```python
layout.split_column(
    Layout(self.build_status_panel(), size=STATUS_PANEL_HEIGHT),
    Layout(self.build_timer_bar(), size=1),
    Layout(self.build_file_table(), ratio=1),
    Layout(self.build_log_panel(), size=LOG_PANEL_HEIGHT),
)
```

```python
def build_status_panel(self) -> Panel
```
- 标题：项目名（`os.path.basename(repo_path)`）
- 内容 `Text` 对象，逐行：
  - `分支: {branch}` — `STYLE_WHITE`
  - `远程: {url}` — URL 部分用 `Style(link=url, color="#89B4FA")`
  - `Release: {version}` — 版本号用 `Style(link=release_url, color="#89B4FA")`，无 release 时显示 "无"
- 边框：圆角（`box=box.ROUNDED`），颜色 `STYLE_GRAY`

```python
def build_timer_bar(self) -> Text
```
- 计算终端宽度，`─` 字符数 = 已过时间占比，`┄` 字符数 = 剩余时间占比
- 已过部分 `STYLE_GRAY`，剩余部分 `STYLE_BLUE`
- 末尾附加倒计时文字 ` {timeout_seconds}s`

```python
def build_file_table(self) -> Table | Text
```
- 无文件时返回 `Text("(空目录)", style=STYLE_GRAY)`
- 创建 `Table`：三列（标记、文件名、操作），无表头，`show_lines=False`
- 滚动逻辑：
  - 计算可用行数 = 终端高度 - `STATUS_PANEL_HEIGHT` - 1（timer）- `LOG_PANEL_HEIGHT` - 边框
  - 如果 `len(file_items) <= visible_rows`：全部显示
  - 否则：以 `selected_index` 为中心计算窗口范围 `[start, end)`
  - 窗口未到顶部时 `start=0`；未到末尾时 `end=len(file_items)`
  - `start > 0` 时第一行替换为 `Text("...", style=STYLE_GRAY)`
  - `end < len(file_items)` 时最后一行替换为 `Text("...", style=STYLE_GRAY)`
- 每行样式：
  - 选中行：`STYLE_SELECTED`（蓝色背景 + 粗体）
  - 已忽略行：`STYLE_DIM + STYLE_STRIKE`
  - 焦点在操作按钮时（`action_index == 1` 且当前行选中）：操作文字额外加 `STYLE_BOLD + STYLE_WHITE`
  - 标记列：`updated_items` 中有 `'A'` 显示 `[+]`（绿色），`'D'` 显示 `[-]`（红色），否则空

```python
def build_log_panel(self) -> Panel
```
- 取最近 N 条日志（N = `LOG_PANEL_HEIGHT - 2`，减去边框）
- 每条日志构建为 `Text` 对象：
  ```python
  line = Text()
  line.append(f"[{timestamp}] ", style=STYLE_DIM)
  line.append(f"{level_label} ", style=LEVEL_STYLES[level])  # SUCCESS/ERROR/WARN/INFO
  line.append(message)
  ```
- 所有行组合为一个 `Text`（用 `\n` 连接）
- 包裹在 `Panel(text, title="日志", box=box.ROUNDED, border_style=STYLE_GRAY)`

**交互方法：**

```python
def handle_key(self, key: bytes) -> None
```
按键分发逻辑：

| 按键 | 行为 |
|---|---|
| `KEY_UP` | `selected_index = (selected_index - 1) % len(file_items)`，`action_index = 0` |
| `KEY_DOWN` | `selected_index = (selected_index + 1) % len(file_items)`，`action_index = 0` |
| `KEY_LEFT` | `action_index = 0` |
| `KEY_RIGHT` | `action_index = 1` |
| `KEY_ENTER` | `action_index == 0` 时切换到 1；`action_index == 1` 时执行操作 |
| `KEY_O` | 在浏览器中打开远程仓库 URL |

操作执行入口：
```python
def execute_action(self) -> None
```
根据 `file_items[selected_index]` 的 `ignored` 状态分发：
- `ignored == True` → `push_to_github(item_name)`（取消忽略并推送）
- `ignored == False` → `confirm_delete(item_name)`（确认后删除）

```python
def confirm_delete(self, item_name: str) -> None
```
1. 写入日志：`"确定删除 '{item_name}' 吗？(按回车确认，Esc/Q 取消)"`，类型 WARN
2. `live.update(self.build_screen())` 刷新显示
3. 阻塞等待按键：`key = get_key()`
4. `KEY_ENTER`：物理删除（目录 `shutil.rmtree`，文件 `os.remove`），日志 SUCCESS/ERROR
5. 其他键：日志 "取消删除操作"，INFO
6. 无论结果：`refresh_file_list()`，`_refresh_caches()`

```python
def push_to_github(self, item_name: str) -> None
```
设 `operation_in_progress = True` → 从 `.gitignore` 移除 → `git add` → `git commit` → `git push` → 日志 → `refresh_file_list()` → 解锁 + 冷却期。

```python
def remove_from_github(self, item_name: str) -> None
```
设 `operation_in_progress = True` → `git rm --cached` → 加入 `.gitignore` → `git commit` → `git push` → 日志 → `refresh_file_list()` → 解锁 + 冷却期。

**数据刷新方法：**

```python
def refresh_file_list(self) -> None
```
1. `os.listdir(self.git.cwd)` 获取所有条目，跳过 `.git`
2. 分为 `dirs` 和 `files`，各自排序
3. 读取 `.gitignore`，构建 `ignored_items` 集合
4. 遍历 dirs + files，构建 `file_items` 列表
5. 空目录时添加 `{"name": "(空目录)", "ignored": False, "action_text": "", "tag_text": ""}`
6. 修正 `selected_index` 不越界

```python
def _refresh_caches(self) -> None
```
`_cached_status = self.git.get_status()`，`_cached_release = self.git.get_latest_release()`（None 时用 `_cache_miss_sentinel` 替代）。

```python
def _on_git_log(self) -> None
```
GitManager 的 `on_log` 回调。在 Live 上下文中调用 `live.update(self.build_screen())`，实现 git 操作期间的 UI 实时更新。

## 4. TUI 渲染架构

### 4.1 核心渲染循环

```python
from rich.live import Live
from rich.console import Console

console = Console()

with Live(self.build_screen(), console=console, refresh_per_second=4, screen=True) as live:
    while True:
        if msvcrt.kbhit():
            key = get_key()
            self.handle_key(key)

        self.update_countdown()
        live.update(self.build_screen())
        time.sleep(0.05)
```

### 4.2 屏幕布局

```
┌──────────────────────────────────────┐
│  Status Panel (Panel)                │  固定高度 ~6 行
│  项目名 / 分支 / 远程 / Release      │
├──────────────────────────────────────┤
│  Timer Bar (Text)                    │  1 行
├──────────────────────────────────────┤
│                                      │
│  File List (Table, 可滚动)           │  弹性高度
│  [+] file.py        [推送]           │
│  [-] old.py         [删除]           │
│      (已忽略) .env                   │
│                                      │
├──────────────────────────────────────┤
│  Log Panel (Panel + Text)            │  固定高度 ~8 行
│  [成功] 同步完成                      │
│  [错误] 推送失败                      │
└──────────────────────────────────────┘
```

### 4.3 build_screen() 方法

```python
def build_screen(self) -> RenderableType:
    layout = Layout()
    layout.split_column(
        Layout(self.build_status_panel(), size=STATUS_HEIGHT),
        Layout(self.build_timer_bar(), size=1),
        Layout(self.build_file_table(), ratio=1),
        Layout(self.build_log_panel(), size=LOG_HEIGHT),
    )
    return layout
```

### 4.4 组件详情

**Status Panel** — `Panel` + `Text` 组合：
- 项目名、分支用 `STYLE_WHITE`
- 远程 URL 用 Rich markup `[link=URL]text[/link]`
- Release 版本同样用 link markup

**File List** — `Table` 组件：
- 三列：状态标记、文件名、操作按钮
- 选中行应用 `STYLE_SELECTED`
- 已忽略文件应用 `STYLE_DIM + STYLE_STRIKE`
- 焦点列（文件名 vs 操作按钮）通过额外高亮区分
- 超出可用高度时，滚动显示选中区域，顶部/底部显示 `...` 指示器

**Timer Bar** — `Text` 对象：
- 保留 `─`（已过）/ `┄`（剩余）字符方案
- 用 `STYLE_GRAY` 着色已过部分，`STYLE_BLUE` 着色剩余部分

**Log Panel** — `Panel` 包裹 `Text` 对象：
- 每条日志：`Text(timestamp, style=STYLE_DIM)` + `Text(type_label, style=对应样式)` + `Text(message)`
- 自动折行由 Rich 处理

### 4.5 超链接

替代手写 OSC 8 序列：

```python
# 之前: \033]8;;url\033\\text\033]8;;\033\\
# 之后:
text = Text()
text.append("远程: ", style=STYLE_GRAY)
text.append(remote_url, style=Style(link=remote_url, color="#89B4FA"))
```

## 5. 键盘输入与主循环

### 5.1 App 状态模型

```python
class App:
    selected_index: int = 0       # 文件列表选中行
    action_index: int = 0         # 0=文件名焦点, 1=操作按钮焦点
    file_items: list = []         # 当前文件列表数据

    logs: list = []               # [(timestamp, type, message)]
    operation_in_progress: bool
    last_operation_time: float
    deadline: float               # 60s 自动退出

    _cached_status: dict
    _cached_release: str
```

### 5.2 主循环流程

```
启动 → enable_vt100() → Console 初始化 → GitManager 初始化
  → 首次同步 → _refresh_caches()
  → 进入 Live 上下文
    → 循环:
        kbhit? → get_key() → handle_key() → live.update()
        倒计时检查 → 超时则 break
        operation_in_progress? → 持续 live.update() 显示等待
        sleep(0.05)
  → 退出清理 → console.show_cursor() → 打印退出信息
```

### 5.3 操作执行

删除/推送操作：设 `operation_in_progress = True` → 主循环跳过键盘、持续 `live.update()` 显示等待 → 操作完成 → 刷新缓存 → 解锁。逻辑与当前一致。

## 6. Rich 增强功能

| 增强点 | 当前实现 | Rich 方案 |
|---|---|---|
| 同步中等待 | 日志文字 | `Spinner` 组件（同步/推送时显示旋转动画） |
| 推送进度 | 无 | `Progress` 条（可选，大文件推送时显示） |
| 退出倒计时 | `─`/`┄` 字符 | 保留字符方案，用 `Style` 着色增强 |
| 日志时间戳 | 纯文本 | `Text` 对象，时间戳 `dim` 样式，消息按类型着色 |

## 7. 可删除的代码

迁移完成后删除以下手写代码（约 300 行）：

- `get_display_width()` — Rich 内置 CJK 宽度计算
- `strip_ansi()` — 不再产生裸 ANSI 序列
- `wrap_ansi_line()` — Rich 自动折行
- `Colors` 类 — 替换为 `config.py` 中的 `Style` 对象
- `init_console()` 中的光标隐藏/显示 — Rich `Live` 接管光标控制；但 `os.system("")` 启用 VT100 处理仍保留，移入 `utils.py` 的 `enable_vt100()` 函数
- `clear_screen()` — Rich `Live` 接管
- `render()` 中的行差异对比逻辑 — Rich `Live` 自动处理

## 8. 依赖管理

```txt
# requirements.txt
rich>=13.0
```

入口检测：

```python
try:
    from rich.console import Console
except ImportError:
    print("请先安装依赖: pip install -r requirements.txt")
    sys.exit(1)
```

## 9. 迁移策略

按模块逐步迁移，每步可独立验证。所有阶段在 `github_sync/` 包目录下操作。

### Phase 1：基础设施层（config.py + utils.py）

**创建文件：**
- `github_sync/__init__.py` — 空文件或仅含 `__version__ = "2.0.0"`
- `github_sync/config.py` — 从原文件提取 `Colors` 类（转为 Rich `Style`）、`Keys` 类（转为字节常量）、超时/布局常量
- `github_sync/utils.py` — 从原文件提取 `enable_vt100()`、`run_command()`、`get_key()`、`get_input_with_default()`

**验证：**
```bash
python -c "from github_sync.config import STYLE_RED, KEY_UP; print(STYLE_RED, KEY_UP)"
python -c "from github_sync.utils import run_command; print(run_command('git --version'))"
```

### Phase 2：Git 逻辑层（git_manager.py）

**创建文件：**
- `github_sync/git_manager.py` — 从原文件完整复制 `GitManager` 类
  - 导入改为 `from .config import ...` 和 `from .utils import run_command`
  - `_parse_push_error()` 返回值改为 `rich.text.Text`
  - `log()` 方法签名不变，增加 `on_log` 回调机制

**验证：**
```bash
python -c "from github_sync.git_manager import GitManager; gm = GitManager('.'); print(gm.get_status())"
```

### Phase 3：TUI 应用层（app.py）

**创建文件：**
- `github_sync/app.py` — 全新编写，Rich Live 驱动
  - 实现 `App` 类所有方法（见 3.4 节）
  - `build_screen()` / `build_status_panel()` / `build_file_table()` / `build_log_panel()` / `build_timer_bar()`
  - `handle_key()` / `execute_action()` / `confirm_delete()`
  - `run()` 主循环

**验证：**
```bash
python -m github_sync   # 在测试目录中运行，检查完整交互流程
```

### Phase 4：入口与清理

**创建文件：**
- `github_sync/__main__.py` — 入口脚本
- `requirements.txt` — `rich>=13.0`

**修改文件：**
- `run_sync.bat` — 改为 `python -m github_sync "%~dp0"`

**删除代码：**
- 原 `github_sync.py` 单文件（功能已完全迁移到包中）
- 确认 `get_display_width()`、`strip_ansi()`、`wrap_ansi_line()`、`Colors` 类、`init_console()`、`clear_screen()`、`render()` 行差异逻辑均已移除

**最终验证：**
```bash
python -c "import py_compile; py_compile.compile('github_sync/app.py', doraise=True)"
python -m github_sync   # 完整功能测试
```

## 10. 运行方式

```bash
# 安装依赖
pip install -r requirements.txt

# 运行（同步当前目录）
python -m github_sync

# 运行（同步指定目录）
python -m github_sync "C:\path\to\project"
```

`run_sync.bat` 更新为调用 `python -m github_sync "%~dp0"`。
