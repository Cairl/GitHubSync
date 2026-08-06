"""基础设施：GitCLIProvider —— 领域协议 GitProvider 的 git CLI 实现。

纯命令执行层：无日志、无 UI、无重试决策（重试由上层决定），
所有 git 操作集中在此，消除旧实现中 App 层裸调 git 命令的问题。
"""

from __future__ import annotations

import os

from .command import PUSH_TIMEOUT, run_command

DEFAULT_GITIGNORE = (
    "__pycache__/\n*.pyc\n.env\n.DS_Store\n.vscode/\n.idea/\ndist/\nbuild/\n"
    "*.spec\nvenv/\nrun_sync.bat\nchangelog.md\n"
)


class GitCLIProvider:
    def __init__(self, cwd: str):
        self.cwd = cwd

    # ── 仓库状态 ──
    def get_status(self) -> dict:
        if not os.path.exists(os.path.join(self.cwd, ".git")):
            return {"initialized": False, "branch": "main", "remote": "未配置"}

        ok, branch = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=self.cwd)
        if not ok or branch == "HEAD":
            ok, branch = run_command(["git", "branch", "--show-current"], cwd=self.cwd)
        branch = branch.strip() if ok and branch.strip() else "main"

        remote = "未配置"
        ok, remote_out = run_command(["git", "remote", "-v"], cwd=self.cwd)
        if ok and remote_out:
            for line in remote_out.splitlines():
                if line.startswith("origin"):
                    parts = line.split()
                    if len(parts) >= 2:
                        remote = parts[1]
                        break
        return {"initialized": True, "branch": branch, "remote": remote}

    def init_repo(self) -> None:
        run_command(["git", "init"], cwd=self.cwd)

    def current_branch(self) -> str:
        branch = self.get_status().get("branch", "")
        return branch if branch and branch != "未知" else "main"

    def branch_to_main(self) -> None:
        run_command(["git", "branch", "-M", "main"], cwd=self.cwd)

    def set_remote(self, url: str) -> None:
        ok, _ = run_command(["git", "remote", "add", "origin", url], cwd=self.cwd)
        if not ok:
            run_command(["git", "remote", "set-url", "origin", url], cwd=self.cwd)

    # ── gitignore 文件操作 ──
    def create_ignore(self) -> None:
        gitignore_path = os.path.join(self.cwd, ".gitignore")
        if os.path.exists(gitignore_path):
            return
        with open(gitignore_path, "w", encoding="utf-8") as f:
            f.write(DEFAULT_GITIGNORE)

    def has_gitignore(self) -> bool:
        return os.path.exists(os.path.join(self.cwd, ".gitignore"))

    def read_gitignore(self) -> str:
        gitignore_path = os.path.join(self.cwd, ".gitignore")
        if not os.path.exists(gitignore_path):
            return ""
        with open(gitignore_path, "r", encoding="utf-8") as f:
            return f.read()

    def ensure_gitignore_entry(self, entry: str) -> None:
        gitignore_path = os.path.join(self.cwd, ".gitignore")
        if not os.path.exists(gitignore_path):
            return
        with open(gitignore_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        existing = {line.strip() for line in lines if line.strip()}
        if entry not in existing:
            with open(gitignore_path, "a", encoding="utf-8") as f:
                f.write(f"\n{entry}\n")

    def add_to_gitignore_file(self, entry: str) -> None:
        gitignore_path = os.path.join(self.cwd, ".gitignore")
        with open(gitignore_path, "a", encoding="utf-8") as f:
            f.write(f"\n{entry}\n")

    def remove_from_gitignore_file(self, entry: str) -> None:
        gitignore_path = os.path.join(self.cwd, ".gitignore")
        with open(gitignore_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        new_lines = []
        for line in lines:
            stripped = line.rstrip()
            if not stripped or stripped.startswith("#") or stripped.startswith("!"):
                new_lines.append(line)
                continue
            pat = stripped.rstrip("/")
            if pat == entry:
                continue  # 删除匹配的行
            new_lines.append(line)
        with open(gitignore_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

    # ── 索引与提交 ──
    def stage_all(self) -> tuple[bool, str]:
        return run_command(["git", "add", "."], cwd=self.cwd)

    def stage_paths(self, *paths: str) -> None:
        if paths:
            run_command(["git", "add", *paths], cwd=self.cwd)

    def exclude_from_index(self, filename: str) -> None:
        """从索引排除文件：已跟踪则 rm --cached（保留本地），未跟踪则 reset"""
        filepath = os.path.join(self.cwd, filename)
        if not os.path.exists(filepath):
            return
        ok_tracked, _ = run_command(["git", "ls-files", "--error-unmatch", filename], cwd=self.cwd)
        if ok_tracked:
            run_command(["git", "rm", "--cached", filename], cwd=self.cwd)
        else:
            run_command(["git", "reset", "HEAD", "--", filename], cwd=self.cwd)

    def is_tracked(self, filename: str) -> bool:
        ok, _ = run_command(["git", "ls-files", "--error-unmatch", filename], cwd=self.cwd)
        return ok

    def rm_cached(self, filename: str) -> tuple[bool, str]:
        return run_command(["git", "rm", "-r", "--cached", filename], cwd=self.cwd)

    def reset_path(self, filename: str) -> None:
        run_command(["git", "reset", "HEAD", "--", filename], cwd=self.cwd)

    def commit(self, message: str) -> tuple[bool, str | None]:
        """提交。返回 (True, detail) 成功；(False, None) 无需提交；(False, detail) 真实错误"""
        ok, out = run_command(["git", "commit", "-m", message], cwd=self.cwd)
        if ok:
            return True, out
        lower = out.lower()
        if "nothing to commit" in lower or "no changes added to commit" in lower:
            return False, None
        if "author identity" in lower or "user.name" in lower:
            self._auto_configure_identity(out)
            ok, out = run_command(["git", "commit", "-m", message], cwd=self.cwd)
            if ok:
                return True, out
        return False, out

    # ── 推送 ──
    def push(self, branch: str, upstream: bool = False, force: bool = False) -> tuple[bool, str]:
        cmd = ["git", "push"]
        if upstream:
            cmd.append("-u")
        cmd += ["origin", branch]
        if force:
            cmd.append("--force")
        return run_command(cmd, cwd=self.cwd, timeout=PUSH_TIMEOUT)

    # ── 提交历史与恢复 ──
    def get_change_count(self) -> int:
        ok, out = run_command(["git", "status", "--porcelain"], cwd=self.cwd)
        if not ok or not out:
            return 0
        return len([line for line in out.splitlines() if line.strip()])

    def get_porcelain(self) -> str:
        ok, out = run_command(["git", "status", "--porcelain"], cwd=self.cwd)
        return out if ok else ""

    def get_recent_commits(self, limit: int = 20) -> list[dict]:
        ok, out = run_command(["git", "log", f"-{limit}", "--format=%H %ai"], cwd=self.cwd)
        if not ok or not out:
            return []
        commits = []
        for line in out.splitlines():
            if not line.strip():
                continue
            h, _, t = line.partition(" ")
            commits.append({"hash": h, "time": t[:19]})
        return commits

    def restore_to_commit(self, commit_hash: str) -> bool:
        ok, _ = run_command(["git", "reset", "--hard", commit_hash], cwd=self.cwd)
        return ok

    def restore_to_tag(self, tag: str) -> bool:
        ok, _ = run_command(["git", "fetch", "origin"], cwd=self.cwd)
        if not ok:
            return False
        ok, _ = run_command(["git", "reset", "--hard", tag], cwd=self.cwd)
        return ok

    # ── Git 身份 ──
    def _auto_configure_identity(self, error_output: str) -> None:
        """从 git 错误输出提取可用用户名，或退回默认身份。"""
        username = "User"
        for line in error_output.splitlines():
            if "email" in line.lower():
                continue
            if "user.name" in line.lower() or "身份" in line:
                continue
        self.ensure_identity(username)

    def ensure_identity(self, username: str = "User") -> None:
        run_command(["git", "config", "user.name", username], cwd=self.cwd)
        run_command(
            ["git", "config", "user.email", f"{username}@users.noreply.github.com"],
            cwd=self.cwd,
        )
