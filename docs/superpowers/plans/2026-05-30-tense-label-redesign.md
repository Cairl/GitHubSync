# 日志时态词体系重设计 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将日志标签从"信息/成功/错误/警告"替换为"正在/完成/失败/注意"，用上下文管理器实现动作的原地替换。

**Architecture:** 在 GitManager 中添加 `action()` 上下文管理器，进入时记录"正在"行，退出时原地替换为"完成"或"失败"。所有旧 `log()` 调用改造为 `action()` 或 `log(msg, "NOTE")`。消息体去掉时态词，由标签承担时态表达。

**Tech Stack:** Python 3.12+, Rich, contextlib

---

### Task 1: 更新 config.py 日志级别常量

**Files:**
- Modify: `src/config.py:22-34`

- [ ] **Step 1: 替换 LEVEL_STYLES 和 LEVEL_LABELS**

将 `src/config.py` 中的 LEVEL_STYLES 和 LEVEL_LABELS 替换为：

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

- [ ] **Step 2: 语法检查**

Run: `python -c "import py_compile; py_compile.compile('src/config.py', doraise=True)"`
Expected: 无输出（通过）

- [ ] **Step 3: Commit**

```bash
git add src/config.py
git commit -m "重构：日志级别常量从 INFO/SUCCESS/ERROR/WARN 改为 ACTION/DONE/FAIL/NOTE"
```

---

### Task 2: 添加 _ActionResult 和 action() 上下文管理器

**Files:**
- Modify: `src/git_manager.py:1-21`

- [ ] **Step 1: 在 git_manager.py 顶部添加 contextmanager 导入**

在 `from .utils import run_command` 之后添加：

```python
from contextlib import contextmanager
```

- [ ] **Step 2: 在 GitManager 类之前添加 _ActionResult 类**

```python
class _ActionResult:
    def __init__(self):
        self.failed = False
        self.detail = None
```

- [ ] **Step 3: 在 GitManager 类中添加 action() 方法**

在 `log()` 方法之后添加：

```python
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

- [ ] **Step 4: 语法检查**

Run: `python -c "import py_compile; py_compile.compile('src/git_manager.py', doraise=True)"`
Expected: 无输出（通过）

- [ ] **Step 5: Commit**

```bash
git add src/git_manager.py
git commit -m "重构：添加 _ActionResult 和 action() 上下文管理器"
```

---

### Task 3: 改造 git_manager.py — init_repo() 和 create_ignore()

**Files:**
- Modify: `src/git_manager.py:46-65`

- [ ] **Step 1: 改造 init_repo()**

将：

```python
    def init_repo(self):
        self.log("正在初始化 Git 仓库", "INFO")
        s, m = run_command("git init", cwd=self.cwd)
        if s:
            self.log("Git 仓库初始化成功", "SUCCESS")
        else:
            self.log(f"初始化失败: {m}", "ERROR")
```

替换为：

```python
    def init_repo(self):
        with self.action("初始化 Git 仓库") as result:
            s, m = run_command("git init", cwd=self.cwd)
            if not s:
                result.failed = True
                result.detail = m
```

- [ ] **Step 2: 改造 create_ignore()**

将：

```python
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
```

替换为：

```python
    def create_ignore(self):
        gitignore_path = os.path.join(self.cwd, ".gitignore")
        if os.path.exists(gitignore_path):
            return

        content = "__pycache__/\n*.pyc\n.env\n.DS_Store\n.vscode/\n.idea/\ndist/\nbuild/\n*.spec\nvenv/\nrun_sync.bat\n"
        with self.action("创建 .gitignore") as result:
            try:
                with open(gitignore_path, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception as e:
                result.failed = True
                result.detail = str(e)
```

- [ ] **Step 3: 语法检查**

Run: `python -c "import py_compile; py_compile.compile('src/git_manager.py', doraise=True)"`
Expected: 无输出（通过）

- [ ] **Step 4: Commit**

```bash
git add src/git_manager.py
git commit -m "重构：init_repo() 和 create_ignore() 改用 action() 上下文管理器"
```

---

### Task 4: 改造 git_manager.py — configure_remote()

**Files:**
- Modify: `src/git_manager.py:206-223`

- [ ] **Step 1: 改造 configure_remote()**

将：

```python
    def configure_remote(self):
        username = self.get_github_username()
        repo_name = os.path.basename(self.cwd)
        url = f"https://github.com/{username}/{repo_name}" if username else ""

        if not url:
            self.log("无法获取 GitHub 用户名，远程仓库未配置", "WARN")
            return

        self.log(f"正在配置远程仓库: {url}", "INFO")
        s, m = run_command(f"git remote add origin {url}", cwd=self.cwd)
        if not s:
            s, m = run_command(f"git remote set-url origin {url}", cwd=self.cwd)

        if s:
            self.log(f"远程仓库设置成功: {url}", "SUCCESS")
        else:
            self.log(f"设置远程失败: {m}", "ERROR")
```

替换为：

```python
    def configure_remote(self):
        username = self.get_github_username()
        repo_name = os.path.basename(self.cwd)
        url = f"https://github.com/{username}/{repo_name}" if username else ""

        if not url:
            self.log("无法获取 GitHub 用户名", "NOTE")
            return

        with self.action("配置远程仓库") as result:
            s, m = run_command(f"git remote add origin {url}", cwd=self.cwd)
            if not s:
                s, m = run_command(f"git remote set-url origin {url}", cwd=self.cwd)
            if s:
                result.detail = url
            else:
                result.failed = True
                result.detail = m
```

- [ ] **Step 2: 语法检查**

Run: `python -c "import py_compile; py_compile.compile('src/git_manager.py', doraise=True)"`
Expected: 无输出（通过）

- [ ] **Step 3: Commit**

```bash
git add src/git_manager.py
git commit -m "重构：configure_remote() 改用 action() 上下文管理器"
```

---

### Task 5: 改造 git_manager.py — sync()（核心复杂方法）

**Files:**
- Modify: `src/git_manager.py:225-310`

这是最复杂的改造，因为 sync() 有多分支重试逻辑。需要将每个阶段拆分为独立的 action 上下文。

- [ ] **Step 1: 改造 sync() 方法**

将整个 `sync()` 方法替换为：

```python
    def sync(self):
        self.create_ignore()

        status = self.get_status()
        if not status["initialized"]:
            self.init_repo()
            status = self.get_status()

        with self.action("扫描") as result:
            s, m = run_command("git add .", cwd=self.cwd)
            if not s:
                result.failed = True
                result.detail = f"文件暂存异常: {m}"
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
            with self.action("提交") as result:
                s, m = run_command(f'git commit -m "{msg}"', cwd=self.cwd)
                if not s:
                    if "author identity" in m.lower() or "user.name" in m.lower():
                        username = self.get_github_username() or "User"
                        run_command(f'git config user.name "{username}"', cwd=self.cwd)
                        run_command(f'git config user.email "{username}@users.noreply.github.com"', cwd=self.cwd)
                        self.log(f"自动配置 Git 身份: {username}", "NOTE")
                        s, m = run_command(f'git commit -m "{msg}"', cwd=self.cwd)
                    if not s:
                        result.failed = True
                        result.detail = m
                        return
        else:
            self.log("没有更改需要提交", "NOTE")

        if status["remote"] == "未配置":
            self.configure_remote()
            status = self.get_status()
            if status["remote"] == "未配置":
                return

        run_command("git branch -M main", cwd=self.cwd)
        with self.action("推送 GitHub") as result:
            s, m = run_command("git push -u origin main", cwd=self.cwd)
            if not s:
                result.failed = True
                result.detail = m

        if s:
            self.publish_release()
        else:
            if "repository not found" in m.lower() or "does not exist" in m.lower() or "404" in m:
                if self.create_github_repo():
                    with self.action("重新推送") as result:
                        s, m = run_command("git push -u origin main", cwd=self.cwd)
                        if not s:
                            result.failed = True
                            result.detail = m
                    if s:
                        self.publish_release()
                        return

            if "rejected" in m or "fetch first" in m:
                self.log("检测到冲突，尝试自动合并", "NOTE")
                s_pull, m_pull = run_command("git pull origin main --rebase", cwd=self.cwd)
                if s_pull:
                    self.log("合并成功，重新推送", "NOTE")
                    with self.action("推送 GitHub") as result:
                        s_push, m_push = run_command("git push -u origin main", cwd=self.cwd)
                        if s_push:
                            result.detail = "合并成功"
                        else:
                            result.failed = True
                            result.detail = m_push
                    if s_push:
                        self.publish_release()
                        return
                else:
                    self.log("自动合并失败，尝试强制推送", "NOTE")
                    run_command("git rebase --abort", cwd=self.cwd)

            self.force_push()
```

注意点：
- 扫描阶段：`git add .` 失败时设置 `result.detail` 为 "文件暂存异常: {m}"（用"异常"替代"失败"）
- 提交阶段：`git commit` 失败时设置 `result.failed = True` 并 return
- 推送阶段：先执行推送，再根据结果决定后续流程
- 重新推送和合并后推送各自是独立的 action 上下文
- 合并成功的推送使用 `result.detail = "合并成功"` 在完成行显示详情

- [ ] **Step 2: 语法检查**

Run: `python -c "import py_compile; py_compile.compile('src/git_manager.py', doraise=True)"`
Expected: 无输出（通过）

- [ ] **Step 3: Commit**

```bash
git add src/git_manager.py
git commit -m "重构：sync() 改用 action() 上下文管理器，多阶段动作独立追踪"
```

---

### Task 6: 改造 git_manager.py — publish_release()

**Files:**
- Modify: `src/git_manager.py:147-204`

- [ ] **Step 1: 改造 publish_release()**

将整个 `publish_release()` 方法替换为：

```python
    def publish_release(self):
        releases_path = os.path.join(self.cwd, "changelog.md")
        if not os.path.exists(releases_path):
            return

        with self.action("读取 changelog.md") as result:
            try:
                with open(releases_path, "r", encoding="utf-8") as f:
                    body = f.read().strip()
            except OSError as e:
                result.failed = True
                result.detail = str(e)
                return

        if not body:
            return

        tag = self.calculate_next_version()
        repo_slug = self.get_repo_slug()
        if not repo_slug:
            self.log("跳过 Release 发布", "NOTE")
            return

        tmp_file = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
                f.write(body)
                tmp_file = f.name

            with self.action(f"发布 Release {tag}") as result:
                s, m = run_command(f'gh release create {tag} --repo {repo_slug} --target main --notes-file "{tmp_file}"')
                if s:
                    pass
                elif "already exist" in m.lower():
                    with self.action("更新 Release") as update_result:
                        s, m = run_command(f'gh release edit {tag} --repo {repo_slug} --notes-file "{tmp_file}"')
                        if not s:
                            update_result.failed = True
                            update_result.detail = m
                            return
                else:
                    result.failed = True
                    result.detail = m
                    return

            with self.action("删除 changelog.md") as result:
                try:
                    os.remove(releases_path)
                except OSError as e:
                    result.failed = True
                    result.detail = str(e)

        except Exception as e:
            self.log(f"Release 发布异常: {e}", "NOTE")
        finally:
            if tmp_file and os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except OSError:
                    pass
```

注意点：
- "读取 changelog.md" 包裹在独立 action 中，失败时显示"失败 读取 changelog.md: xxx"
- "更新 Release" 是嵌套在 "发布 Release" action 内的独立 action（当 Release 已存在时）
- "删除 changelog.md" 从原来的 INFO 改为独立 action
- 外层异常用 `log(..., "NOTE")` 因为是安全网，无法预知动作开始

- [ ] **Step 2: 语法检查**

Run: `python -c "import py_compile; py_compile.compile('src/git_manager.py', doraise=True)"`
Expected: 无输出（通过）

- [ ] **Step 3: Commit**

```bash
git add src/git_manager.py
git commit -m "重构：publish_release() 改用 action() 上下文管理器"
```

---

### Task 7: 改造 git_manager.py — create_github_repo() 和 force_push()

**Files:**
- Modify: `src/git_manager.py:312-379`

- [ ] **Step 1: 改造 create_github_repo()**

将整个 `create_github_repo()` 方法替换为：

```python
    def create_github_repo(self):
        import webbrowser

        repo_name = os.path.basename(self.cwd)
        username = self.get_github_username()

        if username:
            url = f"https://github.com/new?name={repo_name}"
        else:
            url = "https://github.com/new"

        webbrowser.open(url)

        with self.action("等待仓库创建") as result:
            remote_url = f"https://github.com/{username}/{repo_name}" if username else ""
            if not remote_url:
                result.failed = True
                result.detail = "无法确定仓库地址"
                return False

            max_wait = 300
            waited = 0
            while waited < max_wait:
                time.sleep(3)
                waited += 3
                s, m = run_command(f'gh repo view {username}/{repo_name}')
                if s:
                    break
                if self.on_log:
                    self.on_log()
            else:
                result.failed = True
                result.detail = "等待超时（5分钟）"
                return False

        s, m = run_command(f"git remote add origin {remote_url}", cwd=self.cwd)
        if not s:
            run_command(f"git remote set-url origin {remote_url}", cwd=self.cwd)

        return True
```

- [ ] **Step 2: 改造 force_push()**

将：

```python
    def force_push(self):
        s, m = run_command("git push -u origin main --force", cwd=self.cwd)
        if s:
            self.log("强制推送成功", "SUCCESS")
            self.publish_release()
        else:
            reason = self._parse_push_error(m)
            self.log(f"推送失败：{reason}", "ERROR")
```

替换为：

```python
    def force_push(self):
        with self.action("强制推送") as result:
            s, m = run_command("git push -u origin main --force", cwd=self.cwd)
            if not s:
                result.failed = True
                result.detail = self._parse_push_error(m)
        if s:
            self.publish_release()
```

- [ ] **Step 3: 语法检查**

Run: `python -c "import py_compile; py_compile.compile('src/git_manager.py', doraise=True)"`
Expected: 无输出（通过）

- [ ] **Step 4: Commit**

```bash
git add src/git_manager.py
git commit -m "重构：create_github_repo() 和 force_push() 改用 action() 上下文管理器"
```

---

### Task 8: 更新 _parse_push_error() 译文

**Files:**
- Modify: `src/git_manager.py:361-379`

- [ ] **Step 1: 替换"失败"为"异常"**

将：

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

替换为：

```python
    def _parse_push_error(self, msg):
        m = msg.lower()
        if "recv failure" in m or "connection" in m or "failed to connect" in m:
            return "网络连接异常，请检查网络或代理设置"
        if "could not resolve host" in m:
            return "DNS 解析异常，无法连接到 GitHub"
        if "timeout" in m:
            return "连接超时，网络可能不稳定"
        if "authentication failed" in m or "403" in m:
            return "认证异常，请检查 GitHub 登录状态"
        if "repository not found" in m or "404" in m:
            return "仓库不存在或没有访问权限"
        if "schannel" in m or "certificate" in m or "ssl" in m:
            return "SSL 证书验证异常，请检查系统根证书或代理设置"
        if "rejected" in m and "non-fast-forward" in m:
            return "推送被拒绝，远程仓库有更新未同步"
        if "everything up-to-date" in m:
            return "无需推送，所有内容已是最新"
        return f"未知错误: {msg}"
```

- [ ] **Step 2: 语法检查**

Run: `python -c "import py_compile; py_compile.compile('src/git_manager.py', doraise=True)"`
Expected: 无输出（通过）

- [ ] **Step 3: Commit**

```bash
git add src/git_manager.py
git commit -m "重构：_parse_push_error() 译文从「失败」改为「异常」"
```

---

### Task 9: 改造 app.py — remove_from_github() 和 push_to_github()

**Files:**
- Modify: `src/app.py:366-458`

- [ ] **Step 1: 改造 remove_from_github()**

将：

```python
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
```

替换为：

```python
    def remove_from_github(self, item_name):
        with self.git.action(f"删除: {item_name}") as result:
            s, m = run_command(f'git ls-files "{item_name}"', cwd=self.git.cwd)
            if s and m.strip():
                s, m = run_command(f'git rm -r --cached "{item_name}"', cwd=self.git.cwd)
                if not s:
                    result.failed = True
                    result.detail = m
                    return

            self.add_to_gitignore(item_name)
            run_command('git add .gitignore', cwd=self.git.cwd)

            msg = f"Delete: {item_name}"
            s, m = run_command(f'git commit -m "{msg}"', cwd=self.git.cwd)
            if not s and "nothing to commit" not in m.lower() and "no changes added to commit" not in m.lower():
                result.failed = True
                result.detail = m
                return

            if s:
                status = self.git.get_status()
                branch = status.get("branch", "main")
                if branch == "未知" or not branch:
                    branch = "main"

                s, m = run_command(f"git push origin {branch}", cwd=self.git.cwd)
                if not s:
                    result.failed = True
                    result.detail = m

        self.refresh_file_list()
        self.git.updated_items[item_name] = 'D'
```

- [ ] **Step 2: 改造 push_to_github()**

将：

```python
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
```

替换为：

```python
    def push_to_github(self, item_name):
        with self.git.action(f"推送: {item_name}") as result:
            self.remove_from_gitignore(item_name)
            run_command('git add .gitignore', cwd=self.git.cwd)
            run_command(f'git add "{item_name}"', cwd=self.git.cwd)

            msg = f"Add: {item_name}"
            s, m = run_command(f'git commit -m "{msg}"', cwd=self.git.cwd)
            if not s and "nothing to commit" not in m.lower() and "no changes added to commit" not in m.lower():
                result.failed = True
                result.detail = m
                self.refresh_file_list()
                return

            if not s:
                result.failed = True
                result.detail = "没有新文件需要推送"
                self.refresh_file_list()
                return

            status = self.git.get_status()
            branch = status.get("branch", "main")
            if branch == "未知" or not branch:
                branch = "main"

            s, m = run_command(f"git push origin {branch}", cwd=self.git.cwd)
            if s:
                self.git.updated_items[item_name] = 'A'
            else:
                result.failed = True
                result.detail = m

        self.refresh_file_list()
```

- [ ] **Step 3: 语法检查**

Run: `python -c "import py_compile; py_compile.compile('src/app.py', doraise=True)"`
Expected: 无输出（通过）

- [ ] **Step 4: Commit**

```bash
git add src/app.py
git commit -m "重构：remove_from_github() 和 push_to_github() 改用 action() 上下文管理器"
```

---

### Task 10: 改造 app.py — 其他 log 调用

**Files:**
- Modify: `src/app.py:399-481`

- [ ] **Step 1: 改造 add_to_gitignore() 中的 log 调用**

将：

```python
            self.git.log(f"添加忽略失败: {e}", "ERROR")
```

替换为：

```python
            self.git.log(f"添加忽略异常: {e}", "NOTE")
```

- [ ] **Step 2: 改造 confirm_delete() 中的 log 调用**

将：

```python
        self.git.log(f"确定删除 '{item_name}' 吗？(按回车确认，Esc/Q 取消)", "WARN")
```

替换为：

```python
        self.git.log(f"确定删除 '{item_name}' 吗？(按回车确认，Esc/Q 取消)", "NOTE")
```

将：

```python
                self.git.log(f"从本地磁盘物理删除成功: {item_name}", "SUCCESS")
```

替换为：

```python
                with self.git.action(f"物理删除: {item_name}"):
                    if os.path.isdir(path):
                        shutil.rmtree(path)
                    else:
                        os.remove(path)
```

注意：需要把 `try` 块内的删除逻辑移入 action 上下文。完整替换 confirm_delete() 为：

```python
    def confirm_delete(self, item_name):
        path = os.path.join(self.git.cwd, item_name)
        self.git.log(f"确定删除 '{item_name}' 吗？(按回车确认，Esc/Q 取消)", "NOTE")
        if self._live:
            self._live.update(self.build_screen())

        key = get_key()
        if key == KEY_ENTER:
            with self.git.action(f"物理删除: {item_name}") as result:
                try:
                    if os.path.isdir(path):
                        shutil.rmtree(path)
                    else:
                        os.remove(path)
                    self.refresh_file_list()
                except Exception as e:
                    result.failed = True
                    result.detail = str(e)
        else:
            self.git.log("取消删除操作", "NOTE")
```

- [ ] **Step 3: 改造 remove_from_gitignore() 中的 log 调用**

将：

```python
            self.git.log(f"移除忽略失败: {e}", "ERROR")
```

替换为：

```python
            self.git.log(f"移除忽略异常: {e}", "NOTE")
```

- [ ] **Step 4: 改造 open_remote() 中的 log 调用**

将：

```python
            self.git.log(f"打开成功: {remote_url}", "SUCCESS")
        else:
            self.git.log("未配置远程仓库", "WARN")
```

替换为：

```python
            with self.git.action("打开远程仓库") as result:
                result.detail = remote_url
                webbrowser.open(remote_url)
        else:
            self.git.log("未配置远程仓库", "NOTE")
```

注意：需要把 `webbrowser.open(remote_url)` 移入 action 上下文，并删除方法顶部的 `import webbrowser`（已在 GitManager 中导入，但 app.py 中也需要保留因为这里直接使用）。完整替换 open_remote() 为：

```python
    def open_remote(self):
        import webbrowser
        status = self.git.get_status()
        if status["initialized"] and status["remote"] != "未配置":
            remote_url = status["remote"]
            if not remote_url.startswith("http"):
                remote_url = f"https://{remote_url.replace('git@', '').replace(':', '/')}"
            with self.git.action("打开远程仓库") as result:
                result.detail = remote_url
                webbrowser.open(remote_url)
        else:
            self.git.log("未配置远程仓库", "NOTE")
```

- [ ] **Step 5: 改造 refresh_file_list() 中的 log 调用**

将：

```python
            self.git.log(f"刷新文件列表失败: {e}", "ERROR")
```

替换为：

```python
            self.git.log(f"刷新文件列表异常: {e}", "NOTE")
```

- [ ] **Step 6: 语法检查**

Run: `python -c "import py_compile; py_compile.compile('src/app.py', doraise=True)"`
Expected: 无输出（通过）

- [ ] **Step 7: Commit**

```bash
git add src/app.py
git commit -m "重构：app.py 所有 log 调用改用 action() 或 NOTE/FAIL 级别"
```

---

### Task 11: 更新 app.py 中 build_log_text() 的导入

**Files:**
- Modify: `src/app.py:12-18`

- [ ] **Step 1: 更新导入**

确认 `app.py` 的导入中已包含 `LEVEL_STYLES` 和 `LEVEL_LABELS`（当前已有），无需修改导入语句。`build_log_text()` 方法使用 `LEVEL_LABELS.get(level, level)` 和 `LEVEL_STYLES.get(level, STYLE_WHITE)` 动态查找，已兼容新的级别常量，无需修改逻辑。

- [ ] **Step 2: 全项目语法检查**

Run: `python -c "import py_compile; py_compile.compile('src/config.py', doraise=True); py_compile.compile('src/git_manager.py', doraise=True); py_compile.compile('src/app.py', doraise=True)"`
Expected: 无输出（全部通过）

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "重构：日志时态词体系重设计完成"
```

---

### Task 12: 更新 AGENTS.md 和 changelog.md

**Files:**
- Modify: `AGENTS.md`
- Modify: `changelog.md`

- [ ] **Step 1: 更新 AGENTS.md 中的日志级别描述**

在 AGENTS.md 的 `config.py` 部分和 `git_manager.py` 部分更新相关描述：

将 `config.py` 描述中的：
```
├── LEVEL_STYLES/LABELS  # 日志级别样式和中文标签
```
替换为：
```
├── LEVEL_STYLES/LABELS  # 日志级别样式和时态标签（正在/完成/失败/注意）
```

将 `git_manager.py` 描述中的：
```
    ├── log()            # 结构化日志：(timestamp, level, message) 元组
```
替换为：
```
    ├── log()            # 结构化日志：(timestamp, level, message) 元组
    ├── action()         # 上下文管理器：进入时记录"正在"，退出时原地替换为"完成"或"失败"
```

将错误处理部分的：
```
- `GitManager._parse_push_error()` 将 Git 推送错误翻译为中文提示，大小写不敏感匹配关键词：
  - `recv failure` / `connection` / `failed to connect` → 网络连接失败
  - `could not resolve host` → DNS 解析失败
  - `timeout` → 连接超时
  - `authentication failed` / `403` → 认证失败
  - `repository not found` / `404` → 仓库不存在
  - `rejected` + `non-fast-forward` → 推送被拒绝
  - `schannel` / `certificate` / `ssl` → SSL 证书验证失败
  - `everything up-to-date` → 无需推送
```
替换为：
```
- `GitManager._parse_push_error()` 将 Git 推送错误翻译为中文提示，大小写不敏感匹配关键词：
  - `recv failure` / `connection` / `failed to connect` → 网络连接异常
  - `could not resolve host` → DNS 解析异常
  - `timeout` → 连接超时
  - `authentication failed` / `403` → 认证异常
  - `repository not found` / `404` → 仓库不存在
  - `rejected` + `non-fast-forward` → 推送被拒绝
  - `schannel` / `certificate` / `ssl` → SSL 证书验证异常
  - `everything up-to-date` → 无需推送
```

- [ ] **Step 2: 更新 changelog.md**

写入：

```markdown
# 优化

- **日志时态词体系**: 将日志标签从"信息/成功/错误/警告"替换为"正在/完成/失败/注意"，消息体去掉时态词由标签承担时态表达，同一动作的"正在"行在完成/失败时原地替换
- **动作上下文管理器**: 新增 `GitManager.action()` 上下文管理器，自动追踪动作生命周期，确保每条"完成/失败"必有前置"正在"
- **推送错误译文**: `_parse_push_error()` 译文从"失败"改为"异常"，避免与标签"失败"重复
```

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md changelog.md
git commit -m "文档：更新 AGENTS.md 和 changelog.md 反映日志时态词体系重设计"
```
