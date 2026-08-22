# GitHubSync

> CLI-first 的 GitHub 仓库同步工具 —— 查看状态、提交推送、恢复版本、自动发布 Release

## 功能特性

- **CLI 子命令**：`status` / `push` / `restore` / `diff` / `info` / `switch`，支持 `--json` / `--yes` 等参数，退出码 0/1/2/3 语义化
- **极简交互模式**：无子命令直接启动，顶栏常驻（项目 / 分支·状态 / 主页 / 版本 / 菜单），← → 切换标签页即显示内容（免 Enter）
- **启动秒开**：交互模式首帧立即渲染骨架界面（不等任何 git/gh I/O），仓库状态、版本号与各标签页数据由后台线程异步加载，按键即刻响应；CLI 状态查询的只读 git 调用并行执行
- **1:1 双向同步**：推送 = 本地覆盖远程（分叉自动强推，丢弃远程独有提交）；拉取 = 远程复刻本地（fetch + reset + clean，丢弃本地独有内容与未跟踪文件）
- **文件级控制**：文件视图展示变化/忽略文件列表，Enter 切换推送（加入 Git）与忽略（加入 .gitignore）
- **版本恢复**：拉取视图浏览最近 20 个 commit，回车直接 `reset --hard` 到任意历史版本；首项支持对齐远程
- **自动版本发布**：基于日历版本号（`YYwWWx`）自动计算版本号，读取 changelog.md 发布 GitHub Release；changelog.md 不入库（gitignore 隔离），推送列表注入显示待发布提示，发布成功后删除本地文件，远端无残留
- **默认执行**：初始标签停在推荐动作上，← → 切换标签即显内容、Enter 执行标签内选中项（菜单不标注键位），退出直接关闭窗口
- **中英双语**：全部用户可见文案按系统语言自动切换（`GITHUBSYNC_LANG` 可覆盖）
- **POSIX 输出契约**：结果走 stdout、诊断走 stderr、按 isatty 自动着色
- **远程仓库管理**：按 `o` 在浏览器中打开 GitHub 仓库页面；顶栏版本号是超链接，Ctrl+点击直接打开 Releases 页面，支持自动创建仓库
- **智能错误处理**：推送失败时解析具体错误原因（网络、认证等），仓库不存在自动引导创建，分叉自动强推
- **文件调试日志**：TUI 无回显化的业务日志与 git/gh 命令执行详情（含失败输出）统一落盘项目根 `logs/` 目录，每次运行一个带时间戳的会话文件批量保存——无论同步哪个项目都汇聚到这里（打开项目即可查看；`logs/` 已被 .gitignore 排除，不随同步推送），超 1MB 自动轮转，方便后期 AI 调试

## 技术栈

- Python 3.12+（纯标准库，零第三方运行时依赖；终端着色由 `core/ansi.py` 自研实现）
- **GitHub CLI** (`gh`)：用于 Releases 管理和仓库操作
- **Git**：核心同步引擎

## 安装

```bash
git clone <repo-url>
cd GitHubSync
```

无需安装：直接 `python -m main` 运行，目标目录由参数指定（默认当前目录）。环境变量 `GITHUBSYNC_REPO` 仅 `github_sync.bat` 使用，主程序不读取。

### 前置要求

- **Git**：命令行可用
- **GitHub CLI (`gh`)**：需先登录 (`gh auth login`)，用于 Release 发布和仓库管理

## 使用

### 基本用法

```bash
# 同步当前工作目录（交互模式）
python -m main

# 同步指定目录（位置参数）
python -m main D:\path\to\your\repo

# CLI 子命令（目录来源优先级：-C > 位置参数 > 当前目录）
python -m main status
python -m main push --yes
python -m main diff
python -m main info
python -m main switch <branch>      # 切换分支（-c 新建并切换）
```

### 通过 bat 脚本启动

```bash
github_sync.bat
```

该脚本为纯批处理实现（零 PowerShell），行为按位置区分：在仓库根运行（main.py 与 bat 同目录）时，自动把 `GITHUBSYNC_REPO` 静默持久化到用户环境变量并进入交互模式（同步本目录）；把 bat 复制到其他位置（便携）运行时，读取 `GITHUBSYNC_REPO`（进程内缺失则回退用户环境变量）定位 GitHubSync 代码仓库（均未设置则报错退出码 3），同步目标是 bat 所在目录。

### 交互模式操作

导航栏固定四项：`推送` `拉取` `文件` `分支`（仅选中项带括号如 `[推送]` + 底色框选，未选中项为裸文本），用左右键循环切换标签页、切换即显示内容（免 Enter）；推送 / 拉取有新的同步时文本两侧加星号（如 `*推送*`，选中时 `[*推送*]`）。

| 按键 | 功能 |
|------|------|
| `←` `→` | 循环切换标签页（`[ ]` 框选推送 / 拉取 / 文件 / 分支），切换即显示内容 |
| `Enter` | 执行当前标签内选中项（推送 / 对齐远程·恢复历史 / 切换忽略 / 合并到 main·切换分支） |
| `↑` `↓` | 标签内移动（文件列表、拉取历史列表、分支列表） |
| `o` | 在浏览器中打开远程仓库（隐藏快捷键，不进菜单） |

- 顶栏版本号是 OSC 8 超链接（指向仓库 Releases 页面）：在 Windows Terminal 等支持超链接的终端中 **Ctrl+点击** 直接打开，与主页 URL 的交互一致

拉取标签页：本地最近 20 条提交（最新在前），光标默认停在第一个（最新提交）——回车即对齐远程（fetch 后 `reset --hard` 到 origin/分支，再 `clean -fd` 清理未跟踪文件，本地 1:1 复刻远程，丢弃本地独有内容）；移到其他提交上回车即恢复到该历史版本（无二次确认）。
分支标签页：本地分支列表（当前分支标浅绿），回车切换分支；当前不在 main 时首行固定「合并到 main」——回车执行 切换 main → 合并 → 推送 一条龙，冲突自动中止并切回原分支。有未提交变更时切换与合并均被禁止（行首 `[!]`），需先推送。新建分支走 CLI：`python -m main switch <branch> -c`。
初始标签停在当前状态的推荐动作上（有变化推荐推送、落后推荐拉取），直接回车即可执行推荐操作；菜单中 `*推送*` / `*拉取*` 表示该侧有新同步待处理。Backspace / Esc 已废弃（按无效键处理）。
退出无专用按键：直接关闭终端窗口即可（Ctrl+C 兜底）。

操作结果由视图状态表达：推送页激活即在后台预执行扫描（免 Enter 显示真实扫描结论行「✓ 扫描完成」+ 变更数或「没有需要提交的更改」，按 Enter 续跑复用扫描结果不重复执行），推送过程按阶段逐行累积回显（提交 / 推送 / 发布各一行，进行中 `>`、完成 `✓` 留痕、失败 `✕`，推送实时进度拼在动作行尾），结束后阶段行保留可回溯；拉取标签页中与远程一致的提交 hash 标青色；文件标签页操作失败行首显示 `[!]`。

### CLI 退出码

| 退出码 | 含义 |
|--------|------|
| 0 | 成功 / 干净 |
| 1 | 检测到待同步变化 |
| 2 | 分叉 / 冲突 |
| 3 | 操作失败 |

## 项目结构

```
GitHubSync/
├── main.py                # 入口：argparse 调度 + create_services 唯一组装点
├── github_sync.bat        # Windows 启动器（纯批处理，零 PowerShell）
├── pyproject.toml         # 元数据（无全局命令；GITHUBSYNC_REPO 环境变量仅 github_sync.bat 层读写）
├── requirements.txt       # 空文件：零第三方依赖声明
├── AGENTS.md              # 开发文档
├── cli/                   # CLI 表现层（parser / commands / output / exit_codes）
├── core/                  # 业务层（Provider 协议 + 用例服务 + gitignore 解析）
├── tui/                   # 交互表现层（screen / interactive / view_base / push_view / pull_view / files_view / branch_view）
└── tests/                 # pytest 单测（FakeProvider 注入，无需真实 git/gh）
```

> 架构细节见 `AGENTS.md`。依赖规则：cli/ 与 tui/ 只依赖 core/，core/ 不依赖表现层；
> 接口定义在 `core/protocols.py`、实现在 `core/git_provider.py` / `core/github_provider.py`。

## 配置说明

所有布局和样式常量集中在 `core/config.py`：

- **语义色（GitHub Primer 配色）**：成功 `#3FB950`、警告 `#F6E2B7`、错误 `#F85149`、次要 `#8B949E`
- **键盘映射**：← →（切换标签页即显内容）、Enter（执行标签内选中项）、↑ ↓（标签内移动）、O（打开远程）；Backspace / Esc 已废弃
- **操作冷却**：每次操作执行后有 1 秒冷却期，防止误触
- **语言覆盖**：`GITHUBSYNC_LANG=zh|en` 强制指定界面语言

## 系统要求

- Windows 操作系统（交互模式依赖 `msvcrt`）
- Git
- GitHub CLI (`gh`)，需已登录
- Python 3.12+

## 许可证

MIT
