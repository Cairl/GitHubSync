# GitHubSync

> CLI-first 的 GitHub 仓库同步工具 —— 查看状态、提交推送、恢复版本、自动发布 Release

## 功能特性

- **CLI 子命令**：`status` / `push` / `restore` / `diff` / `info`，支持 `--json` / `--yes` 等参数，退出码 0/1/2/3 语义化
- **极简交互模式**：无子命令直接启动，顶栏常驻（项目 / 分支·状态 / 菜单），← → 移动光标、Enter 执行选中项
- **1:1 双向同步**：推送 = 本地覆盖远程（分叉自动强推，丢弃远程独有提交）；拉取 = 远程复刻本地（fetch + reset + clean，丢弃本地独有内容与未跟踪文件）
- **文件级控制**：文件视图展示变化/忽略文件列表，Enter 切换推送（加入 Git）与忽略（加入 .gitignore）
- **版本恢复**：拉取视图浏览最近 20 个 commit，回车直接 `reset --hard` 到任意历史版本；首项支持对齐远程
- **自动版本发布**：基于日历版本号（`YYwWWx`）自动计算版本号，读取 changelog.md 发布 GitHub Release
- **默认执行**：初始光标停在推荐动作上，← → 选择、Enter 执行选中项（菜单不标注键位），子视图用 Backspace 返回，退出直接关闭窗口
- **中英双语**：全部用户可见文案按系统语言自动切换（`GITHUBSYNC_LANG` 可覆盖）
- **POSIX 输出契约**：结果走 stdout、诊断走 stderr、按 isatty 自动着色
- **远程仓库管理**：按 `o` 在浏览器中打开 GitHub 仓库页面，支持自动创建仓库
- **智能错误处理**：推送失败时解析具体错误原因（网络、认证等），仓库不存在自动引导创建，分叉自动强推

## 技术栈

- Python 3.12+
- **Rich** >= 13.0（终端输出增强）
- **GitHub CLI** (`gh`)：用于 Releases 管理和仓库操作
- **Git**：核心同步引擎

## 安装

```bash
git clone <repo-url>
cd GitHubSync
pip install -r requirements.txt
```

### 前置要求

- **Git**：命令行可用
- **GitHub CLI (`gh`)**：需先登录 (`gh auth login`)，用于 Release 发布和仓库管理

## 使用

### 基本用法

```bash
# 安装为全局命令（任意目录敲 githubsync 即同步当前目录）
pip install -e .

# 同步当前工作目录（交互模式）
python -m main

# 同步指定目录
python -m main /path/to/your/repo

# CLI 子命令
python -m main status
python -m main push --yes
python -m main diff
python -m main info
```

### 通过 bat 脚本启动

```bash
github_sync.bat
```

该脚本会将项目所在目录作为同步目标，进入交互模式。

### 交互模式操作

导航栏固定三项：`推送` `拉取` `文件`（仅选中项带括号如 `[推送]` + 底色框选，未选中项为裸文本），用左右键移动光标、回车执行；推送 / 拉取有新的同步时文本两侧加星号（如 `*推送*`，选中时 `[*推送*]`）。

| 按键 | 功能 |
|------|------|
| `←` `→` | 移动菜单光标（`[ ]` 框选推送 / 拉取 / 文件，循环移动） |
| `Enter` | 执行光标选中的菜单项（推送 / 拉取视图 / 文件视图） |
| `↑` `↓` | 子视图内移动（文件视图、拉取历史列表） |
| `o` | 在浏览器中打开远程仓库（隐藏快捷键，不进菜单） |
| `Backspace` / `Esc` | 从子视图返回主屏 |

拉取视图：本地最近 20 条提交（最新在前），光标默认停在第一个（最新提交）——回车即对齐远程（fetch 后 `reset --hard` 到 origin/分支，再 `clean -fd` 清理未跟踪文件，本地 1:1 复刻远程，丢弃本地独有内容）；移到其他提交上回车即恢复到该历史版本（无二次确认）。
初始光标停在当前状态的推荐动作上（有变化推荐推送、落后推荐拉取），直接回车即可执行推荐操作；菜单中 `*推送*` / `*拉取*` 表示该侧有新同步待处理。
退出无专用按键：直接关闭终端窗口即可（Ctrl+C 兜底）。

操作结果无文字回显，由视图状态表达：推送时待推文件标记 `[·]`（上传中）→ `[✓]`（完成）/ `[✕]`（失败）；拉取视图中与远程一致的提交 hash 标青色；文件视图操作失败行首显示 `[!]`。

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
├── github_sync.bat        # Windows 启动器
├── pyproject.toml         # 打包元数据（全局 githubsync 命令）
├── requirements.txt       # Python 依赖
├── changelog.md           # 版本更新日志（供 Release 读取）
├── AGENTS.md              # 开发文档
├── cli/                   # CLI 表现层（parser / commands / output / exit_codes）
├── core/                  # 业务层（Provider 协议 + 用例服务 + gitignore 解析）
├── tui/                   # 交互表现层（screen / interactive / files_view / restore_view）
└── tests/                 # pytest 单测（FakeProvider 注入，无需真实 git/gh）
```

> 架构细节见 `AGENTS.md`。依赖规则：cli/ 与 tui/ 只依赖 core/，core/ 不依赖表现层；
> 接口定义在 `core/protocols.py`、实现在 `core/git_provider.py` / `core/github_provider.py`。

## 配置说明

所有布局和样式常量集中在 `core/config.py`：

- **语义色（GitHub Primer 配色）**：成功 `#3FB950`、警告 `#F6E2B7`、错误 `#F85149`、次要 `#8B949E`
- **键盘映射**：← →（移动菜单光标）、Enter（执行选中项）、↑ ↓（文件视图移动）、O（打开远程）、Backspace / Esc（返回）
- **操作冷却**：每次操作执行后有 1 秒冷却期，防止误触
- **语言覆盖**：`GITHUBSYNC_LANG=zh|en` 强制指定界面语言

## 系统要求

- Windows 操作系统（交互模式依赖 `msvcrt`）
- Git
- GitHub CLI (`gh`)，需已登录
- Python 3.12+

## 许可证

MIT
test-line-for-visual-verification
