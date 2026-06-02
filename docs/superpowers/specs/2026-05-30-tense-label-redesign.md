# 日志时态词体系重设计

## 背景

当前日志系统使用"信息/成功/错误/警告"作为状态标签，消息体自带时态词（如"正在推送 GitHub"、"同步成功"），导致标签和消息体语义重复，且同一动作的进行和完成之间缺乏视觉关联。

## 设计目标

1. 用时态词"正在/完成/失败/注意"替代原标签，让标签承担时态表达
2. 消息体去掉所有时态词，只保留动作描述
3. 同一动作的"正在"行在完成/失败时原地替换，日志行数不增加
4. 逻辑统一：每条"完成/失败"必有前置"正在"，无特例

## 新标签体系

| 旧标签 | 新标签 | 日志级别常量 | 用途 | 配对 |
|---|---|---|---|---|
| 信息 | 正在 | ACTION | 动作进行中 | 与完成/失败配对 |
| 成功 | 完成 | DONE | 动作完成 | 替换正在 |
| 错误 | 失败 | FAIL | 动作失败 | 替换正在 |
| 警告 | 注意 | NOTE | 独立提示 | 无配对 |

## 核心机制：上下文管理器

### API

```python
from contextlib import contextmanager

class _ActionResult:
    def __init__(self):
        self.failed = False
        self.detail = None

class GitManager:
    @contextmanager
    def action(self, msg):
        idx = len(self.logs)
        self.log(msg, "ACTION")
        result = _ActionResult()
        try:
            yield result
        finally:
            ts, _, orig_msg = self.logs[idx]
            new_ts = datetime.now().strftime("%H:%M:%S")
            level = "FAIL" if result.failed else "DONE"
            detail = f": {result.detail}" if result.detail else ""
            self.logs[idx] = (new_ts, level, f"{orig_msg}{detail}")
            if self.on_log:
                self.on_log()
```

`detail` 字段同时适用于成功和失败场景：
- 成功详情：`完成 配置远程仓库: https://github.com/user/repo`
- 失败详情：`失败 推送 GitHub: 网络连接异常`

### 调用方式

成功路径（无详情）：
```python
with self.action("推送 GitHub") as result:
    s, m = run_command("git push ...")
    if not s:
        result.failed = True
        result.detail = self._parse_push_error(m)
```

成功路径（带详情）：
```python
with self.action("配置远程仓库") as result:
    # ... do work
    if s:
        result.detail = url
    else:
        result.failed = True
        result.detail = m
```

显示效果：
- 进入时：`[14:30:00] 正在 推送 GitHub`
- 成功时：`[14:30:05] 完成 推送 GitHub`（原地替换，时间戳更新）
- 失败时：`[14:30:05] 失败 推送 GitHub: 网络连接异常`（原地替换）

### 时间戳行为

动作完成时，时间戳更新为完成时间，因为该行现在代表完成/失败状态。

## 独立消息

不在动作上下文中的消息使用 `log()` 方法，级别为 NOTE：
```python
self.log("检测到冲突，尝试自动合并", "NOTE")
# 显示为：[14:30:06] 注意 检测到冲突，尝试自动合并
```

## 消息体去时态词

所有消息体去掉"正在""成功""失败"等时态词，由标签承担时态表达：

| 旧消息 | 新消息体 |
|---|---|
| `正在初始化 Git 仓库` | `初始化 Git 仓库` |
| `Git 仓库初始化成功` | （由上下文管理器自动变为"完成"） |
| `正在推送 GitHub` | `推送 GitHub` |
| `同步成功` | （由上下文管理器自动变为"完成"） |
| `正在删除: xxx` | `删除: xxx` |
| `删除成功: xxx` | （由上下文管理器自动变为"完成"） |

## `_parse_push_error` 译文调整

"失败"→"异常"，避免与标签"失败"重复：

| 旧译文 | 新译文 |
|---|---|
| 网络连接失败，请检查网络或代理设置 | 网络连接异常，请检查网络或代理设置 |
| DNS 解析失败，无法连接到 GitHub | DNS 解析异常，无法连接到 GitHub |
| 连接超时，网络可能不稳定 | 不变 |
| 认证失败，请检查 GitHub 登录状态 | 认证异常，请检查 GitHub 登录状态 |
| 仓库不存在或没有访问权限 | 不变 |
| SSL 证书验证失败，请检查系统根证书或代理设置 | SSL 证书验证异常，请检查系统根证书或代理设置 |
| 推送被拒绝，远程仓库有更新未同步 | 不变 |
| 无需推送，所有内容已是最新 | 不变 |

## 所有日志消息改造映射

### git_manager.py 动作（用 `with self.action()`）

| 方法 | 动作消息 | 备注 |
|---|---|---|
| `init_repo()` | `初始化 Git 仓库` | |
| `create_ignore()` | `创建 .gitignore` | 原来无前置 INFO，需补上 |
| `sync()` 扫描阶段 | `扫描` | |
| `sync()` 提交阶段 | `提交` | |
| `sync()` 推送阶段 | `推送 GitHub` | |
| `sync()` 重新推送 | `重新推送` | |
| `configure_remote()` | `配置远程仓库` | URL 移到完成详情 |
| `publish_release()` 发布 | `发布 Release {tag}` | |
| `publish_release()` 更新 | `更新 Release` | |
| `create_github_repo()` | `等待仓库创建` | 原来是 WARN，改为动作 |
| `force_push()` | `强制推送` | |

### app.py 动作（用 `with self.git.action()`）

| 方法 | 动作消息 |
|---|---|
| `remove_from_github()` | `删除: {name}` |
| `push_to_github()` | `推送: {name}` |

### 独立消息（用 `log()` + NOTE）

| 旧消息 | 新消息 |
|---|---|
| `没有更改需要提交` | `没有更改需要提交` |
| `自动配置 Git 身份: {username}` | `自动配置 Git 身份: {username}` |
| `检测到冲突，尝试自动合并` | `检测到冲突，尝试自动合并` |
| `合并成功，重新推送` | `合并成功，重新推送` |
| `自动合并失败，尝试强制推送` | `自动合并失败，尝试强制推送` |
| `无法获取 GitHub 用户名，远程仓库未配置` | `无法获取 GitHub 用户名` |
| `无法获取仓库信息，跳过 Release 发布` | `跳过 Release 发布` |
| `版本序列已达上限 z，将使用 z` | `版本序列已达上限 z` |
| `取消删除操作` | `取消删除操作` |
| `未配置远程仓库` | `未配置远程仓库` |

## config.py 改动

```python
LEVEL_STYLES = {
    "ACTION": STYLE_LOG_INFO,
    "DONE": STYLE_LOG_SUCCESS,
    "FAIL": STYLE_LOG_ERROR,
    "NOTE": STYLE_LOG_WARN,
}

LEVEL_LABELS = {
    "ACTION": "正在",
    "DONE": "完成",
    "FAIL": "失败",
    "NOTE": "注意",
}
```

## 涉及文件

- `src/config.py`：更新 LEVEL_STYLES 和 LEVEL_LABELS
- `src/git_manager.py`：添加 `_ActionResult`、`action()` 上下文管理器，改造所有 `log()` 调用
- `src/app.py`：改造所有 `self.git.log()` 调用，更新 `build_log_text()` 中的级别引用
