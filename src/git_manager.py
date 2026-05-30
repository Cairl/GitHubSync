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
