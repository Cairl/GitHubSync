# GitHubSync

> 基于 Rich 的 GitHub 仓库同步 TUI 工具 —— 可视化推送文件、恢复版本、自动发布 Release

## 功能特性

- **双模式操作**：推送模式 / 恢复模式，通过左右方向键切换
- **双栏界面**：左侧模式导航栏 + 文件与版本列表，右侧信息面板（项目状态 / 操作日志），形似打开的书
- **智能同步**：自动初始化 Git 仓库、创建 .gitignore、配置远程、提交推送
- **文件级控制**：可视化文件列表，支持逐个文件的推送（添加到 Git）和删除（加入 .gitignore）
- **物理删除确认**：删除文件时提供确认弹窗，支持彻底删除或仅忽略
- **版本恢复**：浏览最近 20 个 commit 记录，按回车即可恢复到任意历史版本
- **自动版本发布**：基于日历版本号（`YYwWWx` 格式）自动计算版本号，读取 changelog.md 发布 GitHub Release
- **手动确认**：模式选择后按回车确认，任务完成后按 Q 键退出
- **Catppuccin Mocha 主题**：24 位 RGB 配色，文件状态标签（+/-）带颜色区分
- **远程仓库管理**：按 O 键在浏览器中打开 GitHub 仓库页面，支持自动创建仓库
- **智能错误处理**：推送失败时解析具体错误原因（网络、认证、冲突等），支持自动重试和强制推送

## 技术栈

- Python 3.x
- **Rich** >= 13.0（终端输出增强，Live 渲染引擎）
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
# 同步当前工作目录
python -m src

# 同步指定目录
python -m src /path/to/your/repo
```

### 通过 bat 脚本启动

```bash
github_sync.bat
```

该脚本会将项目所在目录作为同步目标。

### 操作方式

| 阶段 | 按键 | 功能 |
|------|------|------|
| 模式选择 | ← / → | 切换推送模式 / 恢复模式 |
| 模式选择 | Enter | 确认当前高亮模式 |
| 文件列表 | ↑ / ↓ | 选择文件 |
| 文件列表 | Enter（第1次）| 展开操作项 |
| 文件列表 | Enter（第2次）| 执行推送/删除操作 |
| 版本列表 | ↑ / ↓ | 选择历史版本 |
| 版本列表 | Enter（第1次）| 展开恢复操作 |
| 版本列表 | Enter（第2次）| 执行版本恢复 |
| 任意阶段 | O | 在浏览器中打开远程仓库 |
| 任意阶段 | Q | 退出程序 |

### 工作流程

1. **启动**：自动初始化 Git 仓库（如未初始化），创建 .gitignore，尝试配置远程
2. **推送模式**：显示文件列表，已忽略文件标记 `(已忽略)` 可推送，未忽略文件可删除
3. **恢复模式**：显示最近 20 个 commit 记录，选择并恢复到指定版本

## 项目结构

```
GitHubSync/
├── github_sync.bat          # Windows 启动脚本
├── requirements.txt          # Python 依赖
├── changelog.md              # 版本更新日志（供 Release 读取）
├── AGENTS.md                 # 开发文档
├── tests/                    # pytest 单测（FakeProvider 注入，无需真实 git/gh）
└── src/
    ├── __init__.py           # 包入口，版本号 2.1.0
    ├── __main__.py           # 组合根：唯一组装依赖的地方（create_app）
    ├── config.py             # 颜色主题、键盘映射、布局常量
    ├── utils.py              # 工具函数：VT100、按键、宽度计算
    ├── domain/               # 领域层：异常体系、事件总线、协议接口、状态机（零 I/O）
    ├── application/          # 应用层：同步/恢复/发布/文件级操作 四类用例服务（可单测）
    ├── infrastructure/       # 基础设施层：git/gh CLI 适配器、gitignore 解析（可替换）
    └── presentation/         # 表现层：Rich Live 主循环、渲染器、模式组件（策略模式）
```

> 架构细节见 `docs/architecture-refactor.md`。依赖规则：表现层 → 应用层 → 领域层 → 基础设施层，
> 接口定义在领域层、实现在基础设施层，新增模式 = 实现 Mode 协议 + 注册一行。

## 配置说明

所有布局和样式常量集中在 `src/config.py`：

- **Catppuccin Mocha 配色方案**：红 `#F38BA8`、绿 `#A6E3A1`、黄 `#F9E2AF`、蓝 `#89B4FA`、白 `#CDD6F4`
- **日志级别样式**：ACTION（正在）/ DONE（完成）/ FAIL（失败）/ NOTE（注意），各带独立颜色
- **键盘映射**：方向键、Enter、Esc、Q、O
- **操作冷却**：每次操作执行后有 1 秒冷却期，防止误触

## 系统要求

- Windows 操作系统（依赖 `msvcrt`）
- Git
- GitHub CLI (`gh`)，需已登录
- Python 3.x

## 许可证

MIT
