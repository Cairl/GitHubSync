import os
import re
import time
import tempfile
from datetime import datetime
from .utils import run_command
from contextlib import contextmanager


class _ActionResult:
    def __init__(self):
        self.failed = False
        self.detail = None


class GitManager:
    def __init__(self, repo_path, on_log=None):
        self.cwd = repo_path
        self.logs = []
        self.on_log = on_log
        self.frozen_changes = None
        self.updated_items = {}

    def log(self, msg, type="NOTE"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.logs.append((timestamp, type, msg))
        if self.on_log:
            self.on_log()

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
        with self.action("初始化 Git 仓库") as result:
            s, m = run_command("git init", cwd=self.cwd)
            if not s:
                result.failed = True
                result.detail = m

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

    def get_all_releases(self):
        repo_slug = self.get_repo_slug()
        if not repo_slug:
            return []
        s, m = run_command(f"gh release list --repo {repo_slug} --limit 20")
        if not s or not m:
            return []
        releases = []
        for line in m.splitlines():
            parts = line.split()
            if parts:
                releases.append(parts[0])
        return releases

    def get_recent_commits(self, limit=20):
        """获取最近的 git commits"""
        s, m = run_command(f'git log --oneline -{limit} --format="%H %s"', cwd=self.cwd)
        if not s or not m:
            return []
        commits = []
        for line in m.splitlines():
            if line.strip():
                parts = line.split(" ", 1)
                if len(parts) >= 2:
                    commits.append({"hash": parts[0], "message": parts[1]})
                elif len(parts) == 1:
                    commits.append({"hash": parts[0], "message": ""})
        return commits

    def restore_to_tag(self, tag):
        repo_slug = self.get_repo_slug()
        if not repo_slug:
            self.log("无法获取仓库信息", "NOTE")
            return False
        with self.action(f"拉取 {tag}") as result:
            s, m = run_command("git fetch origin", cwd=self.cwd)
            if not s:
                result.failed = True
                result.detail = m
                return False
        with self.action(f"恢复到 {tag}") as result:
            s, m = run_command(f"git reset --hard {tag}", cwd=self.cwd)
            if not s:
                result.failed = True
                result.detail = m
                return False
        return True

    def restore_to_commit(self, commit_hash):
        """恢复到指定的 commit"""
        with self.action(f"恢复到 {commit_hash[:8]}") as result:
            s, m = run_command(f"git reset --hard {commit_hash}", cwd=self.cwd)
            if not s:
                result.failed = True
                result.detail = m
                return False
        return True

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
                self.log("版本序列已达上限 z，将使用 z", "NOTE")
                next_char = 'z'
            return f"{current_prefix}{next_char}"
        else:
            return f"{current_prefix}a"

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
                result.detail = self._parse_push_error(m)

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

    def force_push(self):
        with self.action("强制推送") as result:
            s, m = run_command("git push -u origin main --force", cwd=self.cwd)
            if not s:
                result.failed = True
                result.detail = self._parse_push_error(m)
        if s:
            self.publish_release()

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
