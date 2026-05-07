# GitHubSync

Windows 终端 TUI 工具，将本地目录同步到 GitHub 仓库。

## 项目结构

- `github_sync.py` — 单文件应用，包含 TUI 框架、Git 操作逻辑、文件管理
- `run_sync.bat` — 启动器脚本，将自身所在目录作为目标路径传入 github_sync.py
- `tests/` — 单元测试

## 核心流程

1. 启动时自动执行 `sync()`：扫描文件 → 暂存 → 提交 → 推送
2. 推送成功后自动检测 `release.md`，若存在则发布 GitHub Release
3. TUI 界面支持文件列表浏览、删除/推送操作、60 秒倒计时自动退出

## 关键设计

- 基于 `gh` CLI 操作 GitHub（检测仓库、发布 Release）
- Release 发布失败不阻塞同步主流程
- 首次提交遇到 `Author identity unknown` 时自动配置 Git 身份
- 无命令行参数时默认同步当前工作目录，无需 GUI 依赖
- TUI 状态面板显示最新 Release 版本号，支持点击跳转对应 Release 页面

## 变更记录

### 26w19a

#### 修改范围
- `github_sync.py` — `App` 类缓存机制修复与渲染性能优化

#### 原因与背景
- 26w18c 引入的缓存机制存在缺陷：`_get_release()` 使用 `None` 区分"未缓存"和"缓存值为 None"，但 `get_latest_release()` 返回 `None`（无 release）是合法值，导致缓存永远 miss，每帧重复执行 `git remote -v` 子进程，仍卡顿 30ms+
- 文件列表渲染使用 `strip_ansi` + `get_display_width` 计算每行宽度，长列表时开销累积
- `...` 滚动指示器的填充宽度硬编码错误，导致边框不对齐

#### 行为差异
- 引入 `_cache_miss_sentinel` 哨兵值，正确区分"未缓存"与"缓存值为 None」，彻底消除重复子进程调用
- 文件名显示宽度在 `refresh_file_list()` 中预计算并缓存，渲染时直接读取
- 文件列表行采用 `fixed_width + max_cn_width` 预计算总宽，避免每帧正则解析 ANSI 序列
- `...` 滚动指示器填充计算修正为 `box_width - 8 - 1`

#### 系统影响
- 仅影响 `App` 类内部渲染逻辑，不影响 GitManager 及外部接口
- 渲染耗时从 ~35ms 降至 ~0.1ms

#### 关键问题
- 缓存哨兵值：使用 `object()` 实例作为哨兵，避免与合法返回值 `None` 冲突
- 宽度预计算一致性：`fixed_width` 必须包含所有固定字符（包括 `│`、空格、action 后空格），`max_cn_width` 动态补充 padding 差异

### 26w18c

#### 修改范围
- `github_sync.py` — `App` 类新增缓存机制

#### 原因与背景
- `get_render_lines()` 每次渲染调用 `git.get_status()` 和 `git.get_latest_release()`，后者通过 `gh release list` 发起网络请求，导致渲染路径阻塞 200-500ms+，TUI 操作菜单出现明显顿挫感

#### 行为差异
- 状态和 Release 信息在初始化和操作完成后刷新缓存，渲染时直接读取缓存，不再每帧执行子进程调用
- 主循环空闲 sleep 从 50ms 降至 10ms，操作响应更及时

#### 系统影响
- 仅影响 App 类内部，不影响 GitManager 及外部接口

#### 关键问题
- 缓存一致性：在 `delete_selected()` 和初始同步完成后调用 `_refresh_caches()` 确保缓存与实际状态同步

### 2026-04-30

- 新增 `run_sync.bat` 启动器脚本，支持将 bat 所在目录自动作为同步目标
- 默认 `.gitignore` 新增 `run_sync.bat`，避免启动器被意外提交到用户仓库
- 移除 `run_sync.bat` 末尾的 `cmd /k`，脚本执行完毕后自动关闭窗口
- TUI 状态面板新增"版本"信息，显示 GitHub Releases 最新版本号（蓝色，支持 OSC8 点击跳转）
