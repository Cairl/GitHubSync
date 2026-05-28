# GitHubSync Rich 重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 GitHubSync 从单文件 ~1150 行手写 ANSI TUI 重构为基于 Rich 库的多文件模块化架构。

**Architecture:** Rich Live 驱动全屏 TUI，Layout 组合 Panel/Table/Text 组件构建界面。msvcrt 处理键盘输入，GitManager 封装 Git 操作逻辑，两者通过回调机制通信。

**Tech Stack:** Python 3.12+, Rich 13+, msvcrt (Windows), git CLI, gh CLI

---

## File Structure

```
GitHubSync/
├── github_sync/
│   ├── __init__.py          # 包标识 + 版本
│   ├── __main__.py          # python -m github_sync 入口
│   ├── config.py            # Style 常量 + 键盘码 + 布局参数
│   ├── utils.py             # enable_vt100, run_command, get_key, get_input_with_default
│   ├── git_manager.py       # GitManager 类（从单文件抽出）
│   └── app.py               # App 类（Rich Live TUI）
├── run_sync.bat             # 更新为 python -m github_sync
├── requirements.txt         # rich>=13.0
├── AGENTS.md
├── AGENTS.py
├── changelog.md
└── github_sync.py           # 原文件，Phase 4 删除
```

---

## Phase 1：基础设施层

### Task 1: 创建包结构和依赖

**Files:**
- Create: `github_sync/__init__.py`
- Create: `requirements.txt`

- [ ] **Step 1: 创建 requirements.txt**

```
rich>=13.0
```

- [ ] **Step 2: 安装 Rich**

Run: `pip install rich --quiet`
Expected: 安装成功

- [ ] **Step 3: 创建 github_sync 目录和 __init__.py**

```python
__version__ = "2.0.0"
```

- [ ] **Step 4: 验证包可导入**

Run: `python -c "import github_sync; print(github_sync.__version__)"`
Expected: `2.0.0`

- [ ] **Step 5: 提交**

```bash
git add github_sync/__init__.py requirements.txt
git commit -m "feat: 初始化 github_sync 包结构和 Rich 依赖"
```

---

### Task 2: 创建 config.py

**Files:**
- Create: `github_sync/config.py`

- [ ] **Step 1: 创建 config.py，包含全部常量**

```python
from rich.style import Style

# ─── Catppuccin Mocha 颜色主题 ───────
STYLE_BOLD      = Style(bold=True)
STYLE_DIM       = Style(dim=True)
STYLE_RED       = Style(color="#F38BA8")
STYLE_GREEN     = Style(color="#A6E3A1")
STYLE_YELLOW    = Style(color="#F9E2AF")
STYLE_BLUE      = Style(color="#89B4FA")
STYLE_GRAY      = Style(color="#6C7086")
STYLE_WHITE     = Style(color="#CDD6F4")
STYLE_STRIKE    = Style(strike=True, dim=True)
STYLE_SELECTED  = Style(bgcolor="#31748F", bold=True, color="#CDD6F4")
STYLE_LINK      = Style(color="#89B4FA", underline=True)

# ─── 日志样式 ───────
STYLE_LOG_SUCCESS = Style(color="#A6E3A1", bold=True)
STYLE_LOG_ERROR   = Style(color="#F38BA8", bold=True)
STYLE_LOG_WARN    = Style(color="#F9E2AF", bold=True)
STYLE_LOG_INFO    = Style(color="#89B4FA", bold=True)

LEVEL_STYLES = {
    "SUCCESS": STYLE_LOG_SUCCESS,
    "ERROR": STYLE_LOG_ERROR,
    "WARN": STYLE_LOG_WARN,
    "INFO": STYLE_LOG_INFO,
}

LEVEL_LABELS = {
    "SUCCESS": "成功",
    "ERROR": "错误",
    "WARN": "警告",
    "INFO": "信息",
}

# ─── 键盘扫描码 ───────
KEY_UP    = b"H"
KEY_DOWN  = b"P"
KEY_LEFT  = b"K"
KEY_RIGHT = b"M"
KEY_ENTER = b"\r"
KEY_ESC   = b"\x1b"
KEY_Q     = b"q"
KEY_O     = b"o"

# ─── 超时设置 ───────
IDLE_TIMEOUT = 60
COOLDOWN_PERIOD = 1.0

# ─── 布局尺寸 ───────
STATUS_PANEL_HEIGHT = 6
LOG_PANEL_HEIGHT = 8
```

- [ ] **Step 2: 验证导入**

Run: `python -c "from github_sync.config import STYLE_RED, KEY_UP, LEVEL_STYLES; print(STYLE_RED, KEY_UP, list(LEVEL_STYLES.keys()))"`
Expected: `Style(color=Color("#F38BA8")) b'H' ['SUCCESS', 'ERROR', 'WARN', 'INFO']`

- [ ] **Step 3: 提交**

```bash
git add github_sync/config.py
git commit -m "feat: 添加 config.py — Rich Style 主题、键盘码、布局常量"
```

---

### Task 3: 创建 utils.py

**Files:**
- Create: `github_sync/utils.py`

- [ ] **Step 1: 创建 utils.py**

```python
import os
import sys
import subprocess
import msvcrt


def enable_vt100():
    os.system("")


def run_command(command, cwd=None):
    try:
        result = subprocess.run(
            command, cwd=cwd, shell=True, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', errors='replace'
        )
        return True, result.stdout.strip()
    except subprocess.CalledProcessError as e:
        msg = (e.stdout.strip() + "\n" + e.stderr.strip()).strip()
        return False, msg


def get_key():
    key = msvcrt.getch()
    if key in (b'\xe0', b'\x00'):
        return msvcrt.getch()
    return key


def get_input_with_default(prompt, default_val=""):
    sys.stdout.write(prompt + default_val)
    sys.stdout.flush()

    res = list(default_val)
    while True:
        try:
            char = msvcrt.getwch()
        except Exception:
            continue

        if char == '\r':
            sys.stdout.write('\n')
            return "".join(res)
        elif char == '\x08':
            if res:
                res.pop()
                sys.stdout.write('\b \b')
                sys.stdout.flush()
        elif char == '\x1b':
            sys.stdout.write('\n')
            return ""
        elif char == '\x00' or char == '\xe0':
            msvcrt.getwch()
        else:
            if char.isprintable():
                res.append(char)
                sys.stdout.write(char)
                sys.stdout.flush()
```

- [ ] **Step 2: 验证导入**

Run: `python -c "from github_sync.utils import run_command, enable_vt100; s, m = run_command('git --version'); print(s, m)"`
Expected: `True git version 2.x.x`

- [ ] **Step 3: 提交**

```bash
git add github_sync/utils.py
git commit -m "feat: 添加 utils.py — run_command、get_key、enable_vt100"
```

---

## Phase 2：Git 逻辑层

### Task 4: 提取 GitManager 到 git_manager.py

**Files:**
- Create: `github_sync/git_manager.py`

- [ ] **Step 1: 创建 git_manager.py**

从原 `github_sync.py` 第 180-572 行完整复制 `GitManager` 类，做以下修改：

1. 顶部导入替换：
```python
import os
import re
import time
import tempfile
import subprocess
from datetime import datetime
from .utils import run_command
```

2. `log()` 方法改为存储结构化数据（不再拼接 ANSI 颜色码）：
```python
def log(self, msg, type="INFO"):
    timestamp = datetime.now().strftime("%H:%M:%S")
    self.logs.append((timestamp, type, msg))
    if self.on_log:
        self.on_log()
```

3. 构造函数中 `self.logs` 初始化不变，但类型变为 `list[tuple[str, str, str]]`：
```python
def __init__(self, repo_path, on_log=None):
    self.cwd = repo_path
    self.logs = []
    self.on_log = on_log
    self.frozen_changes = None
    self.updated_items = {}
```

4. `configure_remote()` 中删除 ANSI 光标控制，改为简单的 print：
```python
def configure_remote(self):
    username = self.get_github_username()
    repo_name = os.path.basename(self.cwd)
    default_url = f"https://github.com/{username}/{repo_name}" if username else ""

    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f" [{timestamp}] 正在配置远程仓库: ", end="")
    from .utils import get_input_with_default
    url = get_input_with_default("", default_url).strip()

    if not url:
        self.log("未输入 URL，操作取消", "WARN")
        return
    s, m = run_command(f"git remote add origin {url}", cwd=self.cwd)
    if not s:
        s, m = run_command(f"git remote set-url origin {url}", cwd=self.cwd)

    if s:
        self.log(f"远程仓库设置成功: {url}", "SUCCESS")
    else:
        self.log(f"设置远程失败: {m}", "ERROR")
```

5. `_parse_push_error()` 返回纯字符串（不变，仅去掉类型标注中的 `-> str`）：
```python
def _parse_push_error(self, msg):
    m = msg.lower()
    if "recv failure" in m or "connection" in m or "failed to connect" in m:
        return "网络连接失败，请检查网络或代理设置"
    if "could not resolve host" in m:
        return "DNS 解析失败，无法连接到 GitHub"
    if "timeout" in m:
        return "连接超时，网络可能不稳定"
    if "authentication failed" in m or "403" in m:
        return "认证失败，请检查 GitHub 登录状态"
    if "repository not found" in m or "404" in m:
        return "仓库不存在或没有访问权限"
    if "schannel" in m or "certificate" in m or "ssl" in m:
        return "SSL 证书验证失败，请检查系统根证书或代理设置"
    if "rejected" in m and "non-fast-forward" in m:
        return "推送被拒绝，远程仓库有更新未同步"
    if "everything up-to-date" in m:
        return "无需推送，所有内容已是最新"
    return f"未知错误: {msg}"
```

其余方法（`get_status`、`init_repo`、`create_ignore`、`sync`、`create_github_repo`、`force_push`、`publish_release`、`get_latest_release`、`calculate_next_version`、`get_github_username`、`get_repo_slug`、`add_to_gitignore`、`remove_from_gitignore`）从原文件逐字复制，不做任何修改。

完整的 git_manager.py 文件内容如下（~400 行）：

```python
import os
import re
import time
import tempfile
from datetime import datetime
from .utils import run_command


class GitManager:
    def __init__(self, repo_path, on_log=None):
        self.cwd = repo_path
        self.logs = []
        self.on_log = on_log
        self.frozen_changes = None
        self.updated_items = {}

    def log(self, msg, type="INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.logs.append((timestamp, type, msg))
        if self.on_log:
            self.on_log()

    def get_status(self):
        if not os.path.exists(os.path.join(self.cwd, ".git")):
            return {"initialized": False}

        s, branch = run_command("git rev-parse --abbrev-ref HEAD", cwd=self.cwd)
        if not s or branch == "HEAD":
            s, branch = run_command("git branch --show-current", cwd=self.cwd)

        branch = branch.strip() if s and branch.strip() else "main"

        s, remote_out = run_command("git remote -v", cwd=self.cwd)
        remote = "未配置"
        if s and "origin" in remote_out:
            parts = remote_out.split()
            if len(parts) > 1:
                remote = parts[1]

        return {
            "initialized": True,
            "branch": branch,
            "remote": remote
        }

    def init_repo(self):
        self.log("正在初始化 Git 仓库", "INFO")
        s, m = run_command("git init", cwd=self.cwd)
        if s:
            self.log("Git 仓库初始化成功", "SUCCESS")
        else:
            self.log(f"初始化失败: {m}", "ERROR")

    def create_ignore(self):
        gitignore_path = os.path.join(self.cwd, ".gitignore")
        if os.path.exists(gitignore_path):
            return

        content = "__pycache__/\n*.pyc\n.env\n.DS_Store\n.vscode/\n.idea/\ndist/\nbuild/\n*.spec\nvenv/\nrun_sync.bat\n"
        try:
            with open(gitignore_path, "w", encoding="utf-8") as f:
                f.write(content)
            self.log("默认 .gitignore 创建成功", "SUCCESS")
        except Exception as e:
            self.log(f"创建失败: {e}", "ERROR")

    def get_github_username(self):
        s, m = run_command("gh api user -q .login")
        if s and m and len(m) < 40:
            return m.strip()

        s, m = run_command("git remote -v", cwd=self.cwd)
        if "github.com" in m:
            match = re.search(r"github\.com[:/]([^/ \n\r]+)/", m)
            if match:
                return match.group(1).split('@')[-1]

        try:
            parent_dir = os.path.dirname(self.cwd)
            for folder in os.listdir(parent_dir):
                folder_path = os.path.join(parent_dir, folder)
                if not os.path.isdir(folder_path) or folder.startswith('.'):
                    continue
                try:
                    dot_git = os.path.join(folder_path, ".git")
                    if os.path.exists(dot_git):
                        s, m = run_command(f'git -C "{folder_path}" remote -v')
                        if s and "github.com" in m:
                            match = re.search(r"github\.com[:/]([^/ \n\r]+)/", m)
                            if match:
                                user = match.group(1).split('@')[-1]
                                if user and user != "git":
                                    return user
                except Exception:
                    continue
        except Exception:
            pass

        return None

    def get_repo_slug(self):
        s, m = run_command("git remote -v", cwd=self.cwd)
        if s and "github.com" in m:
            match = re.search(r"github\.com[:/]([^/ \n\r]+)/([^/ \n\r]+?)(?:\.git)?(?:\s|$)", m)
            if match:
                return f"{match.group(1)}/{match.group(2)}"
        return None

    def get_latest_release(self):
        repo_slug = self.get_repo_slug()
        if not repo_slug:
            return None
        s, m = run_command(f"gh release list --repo {repo_slug} --limit 1")
        if s and m:
            parts = m.split()
            if parts:
                return parts[0]
        return None

    def calculate_next_version(self):
        latest = self.get_latest_release()
        now = datetime.now()
        yy = now.strftime("%y")
        iso_cal = now.isocalendar()
        week = iso_cal[1]
        current_prefix = f"{yy}w{week:02d}"

        if not latest:
            return f"{current_prefix}a"

        m = re.match(r'^(\d{2}w\d{2})([a-z])$', latest)
        if not m:
            return f"{current_prefix}a"

        prev_prefix = m.group(1)
        prev_seq = m.group(2)

        if prev_prefix == current_prefix:
            next_char = chr(ord(prev_seq) + 1)
            if next_char > 'z':
                self.log("版本序列已达上限 z，将使用 z", "WARN")
                next_char = 'z'
            return f"{current_prefix}{next_char}"
        else:
            return f"{current_prefix}a"

    def publish_release(self):
        releases_path = os.path.join(self.cwd, "changelog.md")
        if not os.path.exists(releases_path):
            return

        try:
            with open(releases_path, "r", encoding="utf-8") as f:
                body = f.read().strip()
        except OSError as e:
            self.log(f"读取 changelog.md 失败: {e}", "ERROR")
            return

        if not body:
            return

        tag = self.calculate_next_version()
        repo_slug = self.get_repo_slug()
        if not repo_slug:
            self.log("无法获取仓库信息，跳过 Release 发布", "WARN")
            return

        tmp_file = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
                f.write(body)
                tmp_file = f.name

            self.log(f"正在发布 Release {tag}", "INFO")
            s, m = run_command(f'gh release create {tag} --repo {repo_slug} --target main --notes-file "{tmp_file}"')

            if s:
                self.log("发布成功", "SUCCESS")
            elif "already exist" in m.lower():
                self.log("正在更新 Release", "INFO")
                s, m = run_command(f'gh release edit {tag} --repo {repo_slug} --notes-file "{tmp_file}"')
                if s:
                    self.log("发布成功", "SUCCESS")
                else:
                    self.log(f"Release 更新失败: {m}", "ERROR")
                    return
            else:
                self.log(f"Release 发布失败: {m}", "ERROR")
                return

            try:
                os.remove(releases_path)
                self.log("删除成功 changelog.md", "INFO")
            except OSError as e:
                self.log(f"删除 changelog.md 失败: {e}", "WARN")

        except Exception as e:
            self.log(f"Release 发布异常: {e}", "ERROR")
        finally:
            if tmp_file and os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except OSError:
                    pass

    def configure_remote(self):
        username = self.get_github_username()
        repo_name = os.path.basename(self.cwd)
        default_url = f"https://github.com/{username}/{repo_name}" if username else ""

        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f" [{timestamp}] 正在配置远程仓库: ", end="")
        from .utils import get_input_with_default
        url = get_input_with_default("", default_url).strip()

        if not url:
            self.log("未输入 URL，操作取消", "WARN")
            return
        s, m = run_command(f"git remote add origin {url}", cwd=self.cwd)
        if not s:
            s, m = run_command(f"git remote set-url origin {url}", cwd=self.cwd)

        if s:
            self.log(f"远程仓库设置成功: {url}", "SUCCESS")
        else:
            self.log(f"设置远程失败: {m}", "ERROR")

    def sync(self):
        self.create_ignore()

        status = self.get_status()
        if not status["initialized"]:
            self.init_repo()
            status = self.get_status()

        self.log("正在扫描", "INFO")
        s, m = run_command("git add .", cwd=self.cwd)
        if not s:
            self.log(f"文件暂存失败: {m}", "ERROR")
            return

        s, st = run_command("git status --porcelain", cwd=self.cwd)
        self.updated_items = {}
        if st:
            for line in st.splitlines():
                if len(line) > 3:
                    status_char = line[0] if line[0] != ' ' else line[1]
                    path = line[3:].strip().strip('"')
                    if " -> " in path:
                        path = path.split(" -> ")[-1].strip().strip('"')

                    parts = re.split(r'[\\/]', path)
                    if parts:
                        name = parts[0]
                        final_status = 'D' if status_char == 'D' else 'A'
                        self.updated_items[name] = final_status

            msg = f"Update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            self.log("正在提交", "INFO")
            s, m = run_command(f'git commit -m "{msg}"', cwd=self.cwd)
            if not s:
                if "author identity" in m.lower() or "user.name" in m.lower():
                    username = self.get_github_username() or "User"
                    run_command(f'git config user.name "{username}"', cwd=self.cwd)
                    run_command(f'git config user.email "{username}@users.noreply.github.com"', cwd=self.cwd)
                    self.log(f"自动配置 Git 身份: {username}", "INFO")
                    s, m = run_command(f'git commit -m "{msg}"', cwd=self.cwd)
                if not s:
                    self.log(f"提交失败: {m}", "ERROR")
                    return
        else:
            self.log("没有更改需要提交", "INFO")

        if status["remote"] == "未配置":
            self.configure_remote()
            status = self.get_status()
            if status["remote"] == "未配置":
                return

        run_command("git branch -M main", cwd=self.cwd)
        self.log("正在推送 GitHub", "INFO")
        s, m = run_command("git push -u origin main", cwd=self.cwd)

        if s:
            self.log("同步成功", "SUCCESS")
            self.publish_release()
        else:
            if "repository not found" in m.lower() or "does not exist" in m.lower() or "404" in m:
                if self.create_github_repo():
                    self.log("正在重新推送", "INFO")
                    s, m = run_command("git push -u origin main", cwd=self.cwd)
                    if s:
                        self.log("同步成功", "SUCCESS")
                        self.publish_release()
                        return

            if "rejected" in m or "fetch first" in m:
                self.log("检测到冲突，尝试自动合并", "WARN")
                s_pull, m_pull = run_command("git pull origin main --rebase", cwd=self.cwd)
                if s_pull:
                    self.log("合并成功，重新推送", "INFO")
                    s_push, m_push = run_command("git push -u origin main", cwd=self.cwd)
                    if s_push:
                        self.log("同步成功 (合并成功)", "SUCCESS")
                        self.publish_release()
                        return
                    else:
                        self.log(f"合并后推送失败: {m_push}", "ERROR")
                else:
                    self.log("自动合并失败，尝试强制推送", "WARN")
                    run_command("git rebase --abort", cwd=self.cwd)

            self.force_push()

    def create_github_repo(self):
        import webbrowser

        repo_name = os.path.basename(self.cwd)
        username = self.get_github_username()

        if username:
            url = f"https://github.com/new?name={repo_name}"
        else:
            url = "https://github.com/new"

        webbrowser.open(url)
        self.log("等待仓库创建", "WARN")

        remote_url = f"https://github.com/{username}/{repo_name}" if username else ""
        if not remote_url:
            self.log("无法确定仓库地址", "ERROR")
            return False

        max_wait = 300
        waited = 0
        while waited < max_wait:
            time.sleep(3)
            waited += 3
            s, m = run_command(f'gh repo view {username}/{repo_name}')
            if s:
                self.log("检测到仓库创建成功", "SUCCESS")
                break
            if self.on_log:
                self.on_log()
        else:
            self.log("等待仓库创建超时（5分钟）", "ERROR")
            return False

        s, m = run_command(f"git remote add origin {remote_url}", cwd=self.cwd)
        if not s:
            run_command(f"git remote set-url origin {remote_url}", cwd=self.cwd)

        return True

    def force_push(self):
        s, m = run_command("git push -u origin main --force", cwd=self.cwd)
        if s:
            self.log("强制推送成功", "SUCCESS")
            self.publish_release()
        else:
            reason = self._parse_push_error(m)
            self.log(f"推送失败：{reason}", "ERROR")

    def _parse_push_error(self, msg):
        m = msg.lower()
        if "recv failure" in m or "connection" in m or "failed to connect" in m:
            return "网络连接失败，请检查网络或代理设置"
        if "could not resolve host" in m:
            return "DNS 解析失败，无法连接到 GitHub"
        if "timeout" in m:
            return "连接超时，网络可能不稳定"
        if "authentication failed" in m or "403" in m:
            return "认证失败，请检查 GitHub 登录状态"
        if "repository not found" in m or "404" in m:
            return "仓库不存在或没有访问权限"
        if "schannel" in m or "certificate" in m or "ssl" in m:
            return "SSL 证书验证失败，请检查系统根证书或代理设置"
        if "rejected" in m and "non-fast-forward" in m:
            return "推送被拒绝，远程仓库有更新未同步"
        if "everything up-to-date" in m:
            return "无需推送，所有内容已是最新"
        return f"未知错误: {msg}"
```

- [ ] **Step 2: 语法检查**

Run: `python -c "import py_compile; py_compile.compile('github_sync/git_manager.py', doraise=True); print('OK')"`
Expected: `OK`

- [ ] **Step 3: 验证导入和基本功能**

Run: `python -c "from github_sync.git_manager import GitManager; gm = GitManager('.'); print(gm.get_status()); print(type(gm.logs))"`
Expected: `{'initialized': True, 'branch': 'main', 'remote': '...'}` 和 `<class 'list'>`

- [ ] **Step 4: 提交**

```bash
git add github_sync/git_manager.py
git commit -m "feat: 提取 GitManager 到独立模块，日志改为结构化存储"
```

---

## Phase 3：TUI 应用层

### Task 5: 创建 app.py — App 骨架 + 数据刷新

**Files:**
- Create: `github_sync/app.py`

- [ ] **Step 1: 创建 app.py，包含构造函数、refresh_file_list、缓存方法**

```python
import os
import sys
import time
import shutil
import msvcrt

from rich.console import Console
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.style import Style
from rich import box

from .config import (
    STYLE_BOLD, STYLE_DIM, STYLE_RED, STYLE_GREEN, STYLE_YELLOW,
    STYLE_BLUE, STYLE_GRAY, STYLE_WHITE, STYLE_STRIKE, STYLE_SELECTED,
    STYLE_LINK, LEVEL_STYLES, LEVEL_LABELS,
    KEY_UP, KEY_DOWN, KEY_LEFT, KEY_RIGHT, KEY_ENTER, KEY_ESC, KEY_Q, KEY_O,
    IDLE_TIMEOUT, COOLDOWN_PERIOD, STATUS_PANEL_HEIGHT, LOG_PANEL_HEIGHT,
)
from .utils import enable_vt100, run_command, get_key
from .git_manager import GitManager


class App:
    def __init__(self, repo_path):
        self.git = GitManager(repo_path, on_log=self._on_git_log)
        self.console = Console()
        self.running = True
        self.selected_index = 0
        self.action_index = 0
        self.file_items = []
        self.first_sync_done = False
        self.timeout_seconds = IDLE_TIMEOUT
        self.deadline = time.time() + IDLE_TIMEOUT
        self.operation_in_progress = False
        self.cooldown_until = 0
        self._cached_status = None
        self._cached_release = None
        self._cache_miss_sentinel = object()
        self._live = None

    def _on_git_log(self):
        if self._live:
            self._live.update(self.build_screen())

    def _get_status(self):
        if self._cached_status is None:
            self._refresh_caches()
        return self._cached_status

    def _get_release(self):
        if self._cached_release is None:
            self._refresh_caches()
        if self._cached_release is self._cache_miss_sentinel:
            return None
        return self._cached_release

    def _refresh_caches(self):
        self._cached_status = self.git.get_status()
        release = self.git.get_latest_release()
        self._cached_release = release if release is not None else self._cache_miss_sentinel

    def refresh_file_list(self):
        self.file_items = []
        try:
            items = os.listdir(self.git.cwd)
            dirs = []
            files = []
            for item in items:
                if item == ".git":
                    continue
                if os.path.isdir(os.path.join(self.git.cwd, item)):
                    dirs.append(item)
                else:
                    files.append(item)

            dirs.sort()
            files.sort()

            gitignore_path = os.path.join(self.git.cwd, ".gitignore")
            ignored_items = set()
            if os.path.exists(gitignore_path):
                with open(gitignore_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            ignored_items.add(line.rstrip("/"))

            for name in dirs + files:
                ignored = name in ignored_items
                action_text = "推送" if ignored else "删除"
                tag_text = "(已忽略)" if ignored else ""
                self.file_items.append({
                    "name": name,
                    "ignored": ignored,
                    "action_text": action_text,
                    "tag_text": tag_text,
                })

            if not self.file_items:
                self.file_items.append({
                    "name": "(空目录)",
                    "ignored": False,
                    "action_text": "",
                    "tag_text": "",
                })

            if self.selected_index >= len(self.file_items):
                self.selected_index = 0

        except Exception as e:
            self.git.log(f"刷新文件列表失败: {e}", "ERROR")
```

- [ ] **Step 2: 语法检查**

Run: `python -c "import py_compile; py_compile.compile('github_sync/app.py', doraise=True); print('OK')"`
Expected: `OK`

- [ ] **Step 3: 提交**

```bash
git add github_sync/app.py
git commit -m "feat: app.py 骨架 — 构造函数、文件列表刷新、缓存"
```

---

### Task 6: app.py — 渲染方法

**Files:**
- Modify: `github_sync/app.py` (在 `refresh_file_list` 方法后追加)

- [ ] **Step 1: 添加 build_status_panel 方法**

```python
    def build_status_panel(self):
        status = self._get_status()
        content = Text()

        if status["initialized"]:
            remote_raw = status["remote"]
            if remote_raw.startswith("git@"):
                osc_url = f"https://{remote_raw[len('git@'):].replace(':', '/', 1)}"
            elif remote_raw.startswith("http"):
                osc_url = remote_raw
            else:
                osc_url = f"https://{remote_raw}"

            content.append("项目: ", style=STYLE_GRAY)
            content.append(os.path.basename(self.git.cwd), style=STYLE_WHITE)
            content.append("\n")

            content.append("分支: ", style=STYLE_GRAY)
            content.append(status["branch"], style=STYLE_WHITE)
            content.append("\n")

            content.append("远程: ", style=STYLE_GRAY)
            if remote_raw != "未配置":
                content.append(remote_raw, style=Style(link=osc_url, color="#F9E2AF"))
            else:
                content.append("未配置", style=STYLE_DIM)
            content.append("\n")

            latest_release = self._get_release()
            content.append("版本: ", style=STYLE_GRAY)
            if latest_release:
                release_url = f"{osc_url}/releases/tag/{latest_release}"
                content.append(latest_release, style=Style(link=release_url, color="#A6E3A1"))
            else:
                content.append("无", style=STYLE_DIM)
        else:
            content.append("未初始化 Git 仓库", style=STYLE_RED)
            content.append("\n")
            content.append("启动时将自动初始化", style=STYLE_DIM)

        return Panel(
            content,
            title=os.path.basename(self.git.cwd),
            box=box.ROUNDED,
            border_style=STYLE_GRAY,
        )
```

- [ ] **Step 2: 添加 build_timer_bar 方法**

```python
    def build_timer_bar(self):
        try:
            width = shutil.get_terminal_size().columns
        except Exception:
            width = 80

        bar_width = width - 6
        elapsed_ratio = 1.0 - (self.timeout_seconds / IDLE_TIMEOUT)
        filled = int(bar_width * elapsed_ratio)
        empty = bar_width - filled

        bar = Text()
        bar.append("─" * filled, style=STYLE_DIM)
        bar.append("┄" * empty, style=STYLE_BLUE)
        bar.append(f" {self.timeout_seconds}s", style=STYLE_GRAY)
        return bar
```

- [ ] **Step 3: 添加 build_file_table 方法**

```python
    def build_file_table(self):
        if not self.file_items or self.file_items[0]["name"] == "(空目录)":
            return Text("  (空目录)", style=STYLE_GRAY)

        try:
            term_height = shutil.get_terminal_size().lines
        except Exception:
            term_height = 24

        visible_rows = max(3, term_height - STATUS_PANEL_HEIGHT - 1 - LOG_PANEL_HEIGHT - 4)

        display_start = 0
        display_items = self.file_items
        show_top_indicator = False
        show_bottom_indicator = False

        if len(self.file_items) > visible_rows:
            half = visible_rows // 2
            display_start = max(0, self.selected_index - half)
            end = min(len(self.file_items), display_start + visible_rows)
            if end == len(self.file_items):
                display_start = max(0, end - visible_rows)
            display_items = self.file_items[display_start:end]
            show_top_indicator = display_start > 0
            show_bottom_indicator = (display_start + len(display_items)) < len(self.file_items)

        table = Table(
            show_header=False,
            show_lines=False,
            box=None,
            padding=(0, 1),
            expand=True,
        )
        table.add_column("status", width=3, no_wrap=True)
        table.add_column("name", ratio=1, no_wrap=True)
        table.add_column("action", no_wrap=True)
        table.add_column("tag", no_wrap=True)

        if show_top_indicator:
            table.add_row(Text(""), Text("...", style=STYLE_DIM), Text(""), Text(""))

        for i, item in enumerate(display_items):
            actual_index = display_start + i
            is_selected = (actual_index == self.selected_index)
            name = item["name"]

            status_char = self.git.updated_items.get(name)
            if status_char == 'A':
                status_text = Text("[+]", style=STYLE_GREEN)
            elif status_char == 'D':
                status_text = Text("[-]", style=STYLE_RED)
            else:
                status_text = Text("   ")

            if is_selected:
                name_style = STYLE_SELECTED
            elif item["ignored"]:
                name_style = STYLE_STRIKE
            else:
                name_style = STYLE_WHITE

            name_text = Text(f" {name}", style=name_style)

            action_label = item["action_text"]
            if is_selected and self.action_index == 1:
                action_color = STYLE_GREEN if item["ignored"] else STYLE_RED
                action_text = Text(f" {action_label} ", style=Style(
                    bgcolor="#31748F", bold=True,
                    color=action_color.color if action_color.color else "#CDD6F4"
                ))
            else:
                action_text = Text(f" {action_label} ", style=STYLE_DIM)

            tag_text = Text(item["tag_text"], style=STYLE_DIM) if item["tag_text"] else Text("")

            table.add_row(status_text, name_text, action_text, tag_text)

        if show_bottom_indicator:
            table.add_row(Text(""), Text("...", style=STYLE_DIM), Text(""), Text(""))

        return table
```

- [ ] **Step 4: 添加 build_log_panel 方法**

```python
    def build_log_panel(self):
        max_lines = LOG_PANEL_HEIGHT - 2
        recent_logs = self.git.logs[-max_lines:] if len(self.git.logs) > max_lines else self.git.logs

        content = Text()
        for i, (timestamp, level, message) in enumerate(recent_logs):
            if i > 0:
                content.append("\n")
            label = LEVEL_LABELS.get(level, level)
            style = LEVEL_STYLES.get(level, STYLE_WHITE)
            content.append(f"[{timestamp}] ", style=STYLE_DIM)
            content.append(f"{label} ", style=style)
            content.append(message)

        return Panel(
            content,
            title="日志",
            box=box.ROUNDED,
            border_style=STYLE_GRAY,
        )
```

- [ ] **Step 5: 添加 build_screen 方法**

```python
    def build_screen(self):
        layout = Layout()
        layout.split_column(
            Layout(self.build_status_panel(), size=STATUS_PANEL_HEIGHT),
            Layout(self.build_timer_bar(), size=1),
            Layout(self.build_file_table(), ratio=1),
            Layout(self.build_log_panel(), size=LOG_PANEL_HEIGHT),
        )
        return layout
```

- [ ] **Step 6: 语法检查**

Run: `python -c "import py_compile; py_compile.compile('github_sync/app.py', doraise=True); print('OK')"`
Expected: `OK`

- [ ] **Step 7: 提交**

```bash
git add github_sync/app.py
git commit -m "feat: app.py 渲染方法 — status_panel、timer、file_table、log_panel"
```

---

### Task 7: app.py — 交互 + 操作 + 主循环

**Files:**
- Modify: `github_sync/app.py` (在 `build_screen` 方法后追加)

- [ ] **Step 1: 添加交互方法**

```python
    def handle_key(self, key):
        if key == KEY_UP:
            if self.file_items:
                self.selected_index = (self.selected_index - 1) % len(self.file_items)
                self.action_index = 0
        elif key == KEY_DOWN:
            if self.file_items:
                self.selected_index = (self.selected_index + 1) % len(self.file_items)
                self.action_index = 0
        elif key == KEY_LEFT:
            self.action_index = 0
        elif key == KEY_RIGHT:
            self.action_index = 1
        elif key == KEY_ENTER:
            if self.file_items and self.file_items[self.selected_index]["name"] != "(空目录)":
                if self.action_index == 1:
                    self.execute_action()
                else:
                    self.action_index = 1
                self.deadline = time.time() + IDLE_TIMEOUT
        elif key == KEY_O or key == b"O":
            self.open_remote()

    def execute_action(self):
        item = self.file_items[self.selected_index]
        item_name = item["name"]
        if item_name == "(空目录)":
            return

        self.operation_in_progress = True
        try:
            if item.get("ignored", False):
                self.push_to_github(item_name)
            else:
                self.remove_from_github(item_name)
        finally:
            self._refresh_caches()
            self.operation_in_progress = False
            self.cooldown_until = time.time() + COOLDOWN_PERIOD

    def remove_from_github(self, item_name):
        self.git.log(f"正在删除: {item_name}", "INFO")

        s, m = run_command(f'git ls-files "{item_name}"', cwd=self.git.cwd)
        if s and m.strip():
            s, m = run_command(f'git rm -r --cached "{item_name}"', cwd=self.git.cwd)
            if not s:
                self.git.log(f"删除失败: {m}", "ERROR")
                return

        self.add_to_gitignore(item_name)
        run_command('git add .gitignore', cwd=self.git.cwd)

        msg = f"Delete: {item_name}"
        s, m = run_command(f'git commit -m "{msg}"', cwd=self.git.cwd)
        if not s and "nothing to commit" not in m.lower() and "no changes added to commit" not in m.lower():
            self.git.log(f"提交失败: {m}", "ERROR")
            return

        if s:
            status = self.git.get_status()
            branch = status.get("branch", "main")
            if branch == "未知" or not branch:
                branch = "main"

            s, m = run_command(f"git push origin {branch}", cwd=self.git.cwd)
            if not s:
                self.git.log(f"推送失败: {m}", "ERROR")

        self.refresh_file_list()
        self.git.updated_items[item_name] = 'D'
        self.git.log(f"删除成功: {item_name}", "SUCCESS")

    def add_to_gitignore(self, item_name):
        gitignore_path = os.path.join(self.git.cwd, ".gitignore")
        try:
            with open(gitignore_path, "a", encoding="utf-8") as f:
                f.write(f"\n{item_name}\n")
        except Exception as e:
            self.git.log(f"添加忽略失败: {e}", "ERROR")

    def confirm_delete(self, item_name):
        path = os.path.join(self.git.cwd, item_name)
        self.git.log(f"确定删除 '{item_name}' 吗？(按回车确认，Esc/Q 取消)", "WARN")
        if self._live:
            self._live.update(self.build_screen())

        key = get_key()
        if key == KEY_ENTER:
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                self.git.log(f"从本地磁盘物理删除成功: {item_name}", "SUCCESS")
                self.refresh_file_list()
            except Exception as e:
                self.git.log(f"物理删除失败: {e}", "ERROR")
        else:
            self.git.log("取消删除操作", "INFO")

    def push_to_github(self, item_name):
        self.git.log(f"正在推送: {item_name}", "INFO")

        self.remove_from_gitignore(item_name)
        run_command('git add .gitignore', cwd=self.git.cwd)
        run_command(f'git add "{item_name}"', cwd=self.git.cwd)

        msg = f"Add: {item_name}"
        s, m = run_command(f'git commit -m "{msg}"', cwd=self.git.cwd)
        if not s and "nothing to commit" not in m.lower() and "no changes added to commit" not in m.lower():
            self.git.log(f"提交失败: {m}", "ERROR")
            self.refresh_file_list()
            return

        if not s:
            self.git.log("没有新文件需要推送", "WARN")
            self.refresh_file_list()
            return

        status = self.git.get_status()
        branch = status.get("branch", "main")
        if branch == "未知" or not branch:
            branch = "main"

        s, m = run_command(f"git push origin {branch}", cwd=self.git.cwd)
        if s:
            self.git.log(f"推送成功: {item_name}", "SUCCESS")
            self.git.updated_items[item_name] = 'A'
        else:
            self.git.log(f"推送失败: {m}", "ERROR")

        self.refresh_file_list()

    def remove_from_gitignore(self, item_name):
        gitignore_path = os.path.join(self.git.cwd, ".gitignore")
        try:
            with open(gitignore_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            new_lines = [line for line in lines if line.strip().rstrip("/") != item_name]
            with open(gitignore_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
        except Exception as e:
            self.git.log(f"移除忽略失败: {e}", "ERROR")

    def open_remote(self):
        import webbrowser
        status = self.git.get_status()
        if status["initialized"] and status["remote"] != "未配置":
            remote_url = status["remote"]
            if not remote_url.startswith("http"):
                remote_url = f"https://{remote_url.replace('git@', '').replace(':', '/')}"
            webbrowser.open(remote_url)
            self.git.log(f"打开成功: {remote_url}", "SUCCESS")
        else:
            self.git.log("未配置远程仓库", "WARN")
```

- [ ] **Step 2: 添加 run 方法**

```python
    def run(self):
        enable_vt100()

        if not self.first_sync_done:
            self.operation_in_progress = True
            self.git.sync()
            self.first_sync_done = True
            self._refresh_caches()
            self.operation_in_progress = False
            self.cooldown_until = time.time() + COOLDOWN_PERIOD
            self.refresh_file_list()
            self.deadline = time.time() + IDLE_TIMEOUT

        with Live(
            self.build_screen(),
            console=self.console,
            refresh_per_second=4,
            screen=True,
        ) as live:
            self._live = live

            while self.running:
                if msvcrt.kbhit():
                    if self.operation_in_progress or time.time() < self.cooldown_until:
                        while msvcrt.kbhit():
                            msvcrt.getch()
                        time.sleep(0.01)
                        continue

                    key = get_key()
                    self.deadline = time.time() + IDLE_TIMEOUT
                    self.handle_key(key)
                    live.update(self.build_screen())
                else:
                    remaining = self.deadline - time.time()
                    self.timeout_seconds = max(0, round(remaining))
                    if remaining < 0:
                        self.running = False
                    live.update(self.build_screen())
                    time.sleep(0.05)

            self._live = None

        self.console.print("\n退出成功。")
```

- [ ] **Step 3: 语法检查**

Run: `python -c "import py_compile; py_compile.compile('github_sync/app.py', doraise=True); print('OK')"`
Expected: `OK`

- [ ] **Step 4: 提交**

```bash
git add github_sync/app.py
git commit -m "feat: app.py 交互方法 + 操作执行 + Rich Live 主循环"
```

---

## Phase 4：入口与清理

### Task 8: 创建入口脚本 + 更新启动器

**Files:**
- Create: `github_sync/__main__.py`
- Modify: `run_sync.bat`

- [ ] **Step 1: 创建 __main__.py**

```python
import os
import sys

if sys.platform != "win32":
    print("此工具仅支持 Windows 平台。")
    sys.exit(1)

try:
    from rich.console import Console
except ImportError:
    print("请先安装依赖: pip install -r requirements.txt")
    sys.exit(1)

from .app import App


def main():
    if len(sys.argv) > 1:
        potential_path = sys.argv[1]
        if os.path.isdir(potential_path):
            repo_path = potential_path
        else:
            print(f"错误: '{potential_path}' 不是一个有效的文件夹。")
            sys.exit(1)
    else:
        repo_path = os.getcwd()

    app = App(repo_path)
    app.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"\n发生错误: {e}")
```

- [ ] **Step 2: 更新 run_sync.bat**

```bat
@echo off
set "DIR=%~dp0"
python -m github_sync "%DIR:~0,-1%"
```

- [ ] **Step 3: 语法检查**

Run: `python -c "import py_compile; py_compile.compile('github_sync/__main__.py', doraise=True); print('OK')"`
Expected: `OK`

- [ ] **Step 4: 验证包入口**

Run: `python -c "from github_sync.__main__ import main; print('入口可导入')"`
Expected: `入口可导入`

- [ ] **Step 5: 提交**

```bash
git add github_sync/__main__.py run_sync.bat
git commit -m "feat: 添加 __main__.py 入口，更新 run_sync.bat"
```

---

### Task 9: 删除旧文件 + 最终验证

**Files:**
- Delete: `github_sync.py`

- [ ] **Step 1: 全模块语法检查**

Run:
```bash
python -c "import py_compile; py_compile.compile('github_sync/__init__.py', doraise=True)"
python -c "import py_compile; py_compile.compile('github_sync/config.py', doraise=True)"
python -c "import py_compile; py_compile.compile('github_sync/utils.py', doraise=True)"
python -c "import py_compile; py_compile.compile('github_sync/git_manager.py', doraise=True)"
python -c "import py_compile; py_compile.compile('github_sync/app.py', doraise=True)"
python -c "import py_compile; py_compile.compile('github_sync/__main__.py', doraise=True)"
```
Expected: 全部通过，无输出

- [ ] **Step 2: 验证完整包导入**

Run: `python -c "from github_sync.app import App; from github_sync.config import STYLE_RED; from github_sync.git_manager import GitManager; from github_sync.utils import run_command; print('全部导入成功')"`
Expected: `全部导入成功`

- [ ] **Step 3: 删除旧的单文件**

```bash
git rm github_sync.py
```

- [ ] **Step 4: 在测试目录运行完整应用**

在任意测试目录中运行：
```bash
python -m github_sync
```
验证：
- 全屏 TUI 正常显示（状态面板、文件列表、日志面板、倒计时条）
- ↑↓ 键切换文件选中
- ←→ 键切换焦点
- Enter 执行操作
- O 键打开远程仓库
- 60 秒倒计时自动退出

- [ ] **Step 5: 最终提交**

```bash
git add -A
git commit -m "refactor: 删除旧单文件，Rich 重构完成"
```
