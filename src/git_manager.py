import os
import re
import time
import tempfile
from datetime import datetime
from .utils import run_command
from contextlib import contextmanager


class _ActionResult:
    __slots__ = ('failed', 'detail')

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

    def _run_cmd(self, msg, command, cwd=None):
        """Run a command inside an action context; return (success, stdout)."""
        with self.action(msg) as result:
            ok, out = run_command(command, cwd=cwd or self.cwd)
            if not ok:
                result.failed = True
                result.detail = out
        return ok, out

    def get_status(self):
        if not os.path.exists(os.path.join(self.cwd, ".git")):
            return {"initialized": False, "branch": "main", "remote": "未配置"}

        s, branch = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=self.cwd)
        if not s or branch == "HEAD":
            s, branch = run_command(["git", "branch", "--show-current"], cwd=self.cwd)
        branch = branch.strip() if s and branch.strip() else "main"

        s, remote_out = run_command(["git", "remote", "-v"], cwd=self.cwd)
        remote = "未配置"
        if s and remote_out:
            for line in remote_out.splitlines():
                if line.startswith("origin"):
                    parts = line.split()
                    if len(parts) >= 2:
                        remote = parts[1]
                        break

        return {"initialized": True, "branch": branch, "remote": remote}

    def init_repo(self):
        self._run_cmd("初始化 Git 仓库", ["git", "init"])

    def create_ignore(self):
        gitignore_path = os.path.join(self.cwd, ".gitignore")
        if os.path.exists(gitignore_path):
            return

        content = "__pycache__/\n*.pyc\n.env\n.DS_Store\n.vscode/\n.idea/\ndist/\nbuild/\n*.spec\nvenv/\nrun_sync.bat\nchangelog.md\n"
        with self.action("创建 .gitignore") as result:
            try:
                with open(gitignore_path, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception as e:
                result.failed = True
                result.detail = str(e)

    @staticmethod
    def _extract_gh_user(remote_output):
        """从 git remote -v 输出中提取 GitHub 用户名"""
        if "github.com" not in remote_output:
            return None
        match = re.search(r"github\.com[:/]([^/ \n\r]+)/", remote_output)
        if match:
            user = match.group(1).split('@')[-1]
            return user if user and user != "git" else None
        return None

    def get_github_username(self):
        s, m = run_command(["gh", "api", "user", "-q", ".login"])
        if s and m and len(m) < 40:
            return m.strip()

        s, m = run_command(["git", "remote", "-v"], cwd=self.cwd)
        user = self._extract_gh_user(m)
        if user:
            return user

        try:
            parent_dir = os.path.dirname(self.cwd)
            for folder in os.listdir(parent_dir):
                folder_path = os.path.join(parent_dir, folder)
                if not os.path.isdir(folder_path) or folder.startswith('.'):
                    continue
                try:
                    if os.path.exists(os.path.join(folder_path, ".git")):
                        s, m = run_command(["git", "-C", folder_path, "remote", "-v"])
                        user = self._extract_gh_user(m)
                        if user:
                            return user
                except Exception:
                    continue
        except Exception:
            pass

        return None

    def _ensure_gitignore_entry(self, entry):
        """确保 .gitignore 包含指定条目（已有则跳过）"""
        gitignore_path = os.path.join(self.cwd, ".gitignore")
        if not os.path.exists(gitignore_path):
            return
        try:
            with open(gitignore_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            existing = {line.strip() for line in lines if line.strip()}
            if entry not in existing:
                with open(gitignore_path, "a", encoding="utf-8") as f:
                    f.write(f"\n{entry}\n")
        except OSError:
            pass

    def _exclude_from_index(self, filename):
        """从 Git 索引中排除指定文件：已跟踪则移除跟踪（保留本地），未跟踪则取消暂存"""
        filepath = os.path.join(self.cwd, filename)
        if not os.path.exists(filepath):
            return
        s_tracked, _ = run_command(["git", "ls-files", "--error-unmatch", filename], cwd=self.cwd)
        if s_tracked:
            run_command(["git", "rm", "--cached", filename], cwd=self.cwd)
        else:
            run_command(["git", "reset", "HEAD", "--", filename], cwd=self.cwd)

    def get_repo_slug(self):
        s, m = run_command(["git", "remote", "-v"], cwd=self.cwd)
        if s and "github.com" in m:
            match = re.search(r"github\.com[:/]([^/ \n\r]+)/([^/ \n\r]+?)(?:\.git)?(?:\s|$)", m)
            if match:
                return f"{match.group(1)}/{match.group(2)}"
        return None

    def get_latest_release(self):
        repo_slug = self.get_repo_slug()
        if not repo_slug:
            return None
        s, m = run_command(["gh", "release", "list", "--repo", repo_slug, "--limit", "1"])
        if s and m:
            parts = m.split()
            if parts:
                return parts[0]
        return None

    def get_all_releases(self):
        repo_slug = self.get_repo_slug()
        if not repo_slug:
            return []
        s, m = run_command(["gh", "release", "list", "--repo", repo_slug, "--limit", "20"])
        if not s or not m:
            return []
        return [line.split()[0] for line in m.splitlines() if line.strip()]

    def get_recent_commits(self, limit=20):
        """获取最近的 git commits"""
        s, m = run_command(["git", "log", f"-{limit}", "--format=%H %ai"], cwd=self.cwd)
        if not s or not m:
            return []
        commits = []
        for line in m.splitlines():
            if not line.strip():
                continue
            h, _, t = line.partition(" ")
            commits.append({"hash": h, "time": t[:19]})
        return commits

    def restore_to_tag(self, tag):
        if not self.get_repo_slug():
            self.log("无法获取仓库信息", "NOTE")
            return False
        s, _ = self._run_cmd(f"拉取 {tag}", ["git", "fetch", "origin"])
        if not s:
            return False
        s, _ = self._run_cmd(f"恢复到 {tag}", ["git", "reset", "--hard", tag])
        return s

    def restore_to_commit(self, commit_hash):
        """恢复到指定的 commit"""
        s, _ = self._run_cmd(f"恢复到 {commit_hash[:8]}", ["git", "reset", "--hard", commit_hash])
        return s

    @staticmethod
    def _increment_alpha(seq):
        """Excel风格字母递增: a→b, z→aa, az→ba, zz→aaa"""
        s = list(seq)
        i = len(s) - 1
        while i >= 0:
            if s[i] < 'z':
                s[i] = chr(ord(s[i]) + 1)
                return ''.join(s)
            s[i] = 'a'
            i -= 1
        return 'a' + ''.join(s)

    def calculate_next_version(self):
        latest = self.get_latest_release()
        now = datetime.now()
        yy = now.strftime("%y")
        iso_cal = now.isocalendar()
        week = iso_cal[1]
        current_prefix = f"{yy}w{week:02d}"

        if not latest:
            return f"{current_prefix}a"

        m = re.match(r'^(\d{2}w\d{2})([a-z]+)$', latest)
        if not m:
            return f"{current_prefix}a"

        prev_prefix = m.group(1)
        prev_seq = m.group(2)

        if prev_prefix == current_prefix:
            next_seq = self._increment_alpha(prev_seq)
            return f"{current_prefix}{next_seq}"
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
                s, m = run_command(["gh", "release", "create", tag, "--repo", repo_slug, "--target", "main", "--notes-file", tmp_file])
                if not s:
                    if "already exist" in m.lower():
                        with self.action("更新 Release") as update_result:
                            s, m = run_command(["gh", "release", "edit", tag, "--repo", repo_slug, "--notes-file", tmp_file])
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

    def _current_branch(self):
        """获取当前分支名，回退到 main"""
        branch = self.get_status().get("branch", "")
        return branch if branch and branch != "未知" else "main"

    def configure_remote(self):
        username = self.get_github_username()
        if not username:
            self.log("无法获取 GitHub 用户名", "NOTE")
            return

        url = f"https://github.com/{username}/{os.path.basename(self.cwd)}"
        with self.action("配置远程仓库") as result:
            for cmd in [["git", "remote", "add", "origin", url],
                        ["git", "remote", "set-url", "origin", url]]:
                s, m = run_command(cmd, cwd=self.cwd)
                if s:
                    result.detail = url
                    return
            result.failed = True
            result.detail = m

    def sync(self):
        self.create_ignore()
        self._ensure_gitignore_entry("changelog.md")

        status = self.get_status()
        if not status["initialized"]:
            self.init_repo()
            status = self.get_status()

        s, m = self._run_cmd("扫描", ["git", "add", "."])
        if not s:
            return

        # changelog.md 仅用于 Release 发布，不进入 Git 历史
        self._exclude_from_index("changelog.md")

        s, st = run_command(["git", "status", "--porcelain"], cwd=self.cwd)
        self.updated_items = {}
        if st:
            for line in st.splitlines():
                if len(line) <= 3:
                    continue
                status_char = line[0] if line[0] != ' ' else line[1]
                path = line[3:].strip().strip('"')
                if " -> " in path:
                    path = path.split(" -> ")[-1].strip().strip('"')
                parts = re.split(r'[\\/]', path)
                if parts:
                    if parts[0] == "changelog.md":
                        continue
                    self.updated_items[parts[0]] = 'D' if status_char == 'D' else 'A'

            msg = f"Update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            with self.action("提交") as result:
                s, m = run_command(["git", "commit", "-m", msg], cwd=self.cwd)
                if not s:
                    if "author identity" in m.lower() or "user.name" in m.lower():
                        self._configure_git_identity()
                        s, m = run_command(["git", "commit", "-m", msg], cwd=self.cwd)
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

        run_command(["git", "branch", "-M", "main"], cwd=self.cwd)
        with self.action("推送 GitHub") as result:
            s, m = run_command(["git", "push", "-u", "origin", "main"], cwd=self.cwd)
            if not s:
                result.failed = True
                result.detail = self._parse_push_error(m)

        if s:
            self.publish_release()
        else:
            if "repository not found" in m.lower() or "does not exist" in m.lower() or "404" in m:
                if self.create_github_repo():
                    with self.action("重新推送") as result:
                        s, m = run_command(["git", "push", "-u", "origin", "main"], cwd=self.cwd)
                        if not s:
                            result.failed = True
                            result.detail = m
                    if s:
                        self.publish_release()
                        return

            # 只有在推送被拒绝（非快进）时才尝试强制推送
            error_lower = m.lower()
            if "non-fast-forward" in error_lower or "rejected" in error_lower or "failed to push" in error_lower:
                self.force_push()

    def create_github_repo(self):
        import webbrowser

        repo_name = os.path.basename(self.cwd)
        username = self.get_github_username()

        url = f"https://github.com/new?name={repo_name}" if username else "https://github.com/new"
        webbrowser.open(url)

        with self.action("等待仓库创建") as result:
            remote_url = f"https://github.com/{username}/{repo_name}" if username else ""
            if not remote_url:
                result.failed = True
                result.detail = "无法确定仓库地址"
                return False

            for _ in range(100):  # 100 × 3s = 300s = 5min
                time.sleep(3)
                s, _ = run_command(["gh", "repo", "view", f"{username}/{repo_name}"])
                if s:
                    break
                if self.on_log:
                    self.on_log()
            else:
                result.failed = True
                result.detail = "等待超时（5分钟）"
                return False

        s, _ = run_command(["git", "remote", "add", "origin", remote_url], cwd=self.cwd)
        if not s:
            run_command(["git", "remote", "set-url", "origin", remote_url], cwd=self.cwd)

        return True

    def force_push(self):
        with self.action("强制推送") as result:
            s, m = run_command(["git", "push", "-u", "origin", "main", "--force"], cwd=self.cwd)
            if not s:
                result.failed = True
                result.detail = self._parse_push_error(m)
                return
        self.publish_release()

    def _configure_git_identity(self):
        username = self.get_github_username() or "User"
        run_command(["git", "config", "user.name", username], cwd=self.cwd)
        run_command(["git", "config", "user.email", f"{username}@users.noreply.github.com"], cwd=self.cwd)
        self.log(f"自动配置 Git 身份: {username}", "NOTE")

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
        if "rejected" in m and ("non-fast-forward" in m or "fetch first" in m):
            return "推送被拒绝，远程仓库有更新未同步"
        if "everything up-to-date" in m:
            return "无需推送，所有内容已是最新"
        return f"未知错误: {msg}"
