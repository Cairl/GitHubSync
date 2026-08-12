"""GitCLIProvider：git 子进程适配器（GitProvider 协议的真实实现）。"""
from __future__ import annotations

import os

from .command import DEFAULT_TIMEOUT, run_command

# 创建仓库时的默认 .gitignore 内容
_DEFAULT_GITIGNORE = (
    "__pycache__/\n*.pyc\n.env\n.DS_Store\n.vscode/\n.idea/\n"
    "dist/\nbuild/\n*.spec\nvenv/\nrun_sync.bat\n"
)


class GitCLIProvider:
    """通过 git CLI 操作 repo_path 下的仓库。"""

    def __init__(self, repo_path: str):
        self.cwd = repo_path

    # ── 仓库状态 ──
    def get_status(self) -> dict:
        if not os.path.exists(os.path.join(self.cwd, ".git")):
            return {"initialized": False, "branch": "main"}
        ok, branch = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                                 cwd=self.cwd)
        if not ok or branch == "HEAD":
            ok, branch = run_command(["git", "branch", "--show-current"],
                                     cwd=self.cwd)
        branch = branch.strip() if ok and branch.strip() else "main"
        return {"initialized": True, "branch": branch}

    def current_branch(self) -> str:
        branch = self.get_status().get("branch", "")
        return branch if branch else "main"

    def remote_url(self) -> str | None:
        ok, out = run_command(["git", "remote", "get-url", "origin"],
                              cwd=self.cwd)
        return out.strip() if ok and out.strip() else None

    def fetch(self) -> bool:
        ok, _ = run_command(["git", "fetch", "origin", "--quiet"],
                            cwd=self.cwd, timeout=DEFAULT_TIMEOUT)
        return ok

    def ahead_behind_upstream(self) -> tuple[int, int] | None:
        ok, out = run_command(
            ["git", "rev-list", "--left-right", "--count", "HEAD...@{u}"],
            cwd=self.cwd)
        if not ok or not out:
            return None
        parts = out.split()
        if len(parts) != 2:
            return None
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            return None

    # ── 初始化与远程配置 ──
    def init_repo(self) -> None:
        run_command(["git", "init"], cwd=self.cwd)

    def branch_to_main(self) -> None:
        run_command(["git", "branch", "-M", "main"], cwd=self.cwd)

    def set_remote(self, url: str) -> None:
        ok, _ = run_command(["git", "remote", "add", "origin", url],
                            cwd=self.cwd)
        if not ok:
            run_command(["git", "remote", "set-url", "origin", url],
                        cwd=self.cwd)

    def ensure_identity(self, username: str = "User") -> None:
        run_command(["git", "config", "user.name", username], cwd=self.cwd)
        run_command(["git", "config", "user.email",
                     f"{username}@users.noreply.github.com"], cwd=self.cwd)

    # ── gitignore 管理 ──
    def _gitignore_path(self) -> str:
        return os.path.join(self.cwd, ".gitignore")

    def create_ignore(self) -> None:
        path = self._gitignore_path()
        if os.path.exists(path):
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(_DEFAULT_GITIGNORE)
        except OSError:
            pass

    def has_gitignore(self) -> bool:
        return os.path.exists(self._gitignore_path())

    def read_gitignore(self) -> str:
        try:
            with open(self._gitignore_path(), "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""

    def ensure_gitignore_entry(self, entry: str) -> None:
        path = self._gitignore_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = {line.strip() for line in f if line.strip()}
            if entry not in existing:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(f"\n{entry}\n")
        except OSError:
            pass

    def add_to_gitignore_file(self, entry: str) -> None:
        try:
            with open(self._gitignore_path(), "a", encoding="utf-8") as f:
                f.write(f"\n{entry}\n")
        except OSError:
            pass

    def remove_from_gitignore_file(self, entry: str) -> None:
        path = self._gitignore_path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        except OSError:
            return
        kept = [line for line in lines if line.strip().rstrip("/") != entry]
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(kept) + "\n")
        except OSError:
            pass

    # ── 暂存与提交 ──
    def stage_all(self) -> tuple[bool, str]:
        return run_command(["git", "add", "."], cwd=self.cwd)

    def stage_paths(self, *paths: str) -> None:
        run_command(["git", "add", "--", *paths], cwd=self.cwd)

    def is_tracked(self, filename: str) -> bool:
        ok, _ = run_command(["git", "ls-files", "--error-unmatch", filename],
                            cwd=self.cwd)
        return ok

    def tracked_files(self) -> set[str]:
        ok, out = run_command(["git", "ls-files"], cwd=self.cwd)
        if not ok:
            return set()
        return {line for line in out.splitlines() if line.strip()}

    def rm_cached(self, filename: str) -> tuple[bool, str]:
        return run_command(["git", "rm", "--cached", filename], cwd=self.cwd)

    def reset_path(self, filename: str) -> None:
        run_command(["git", "reset", "HEAD", "--", filename], cwd=self.cwd)

    def exclude_from_index(self, filename: str) -> None:
        if not os.path.exists(os.path.join(self.cwd, filename)):
            return
        if self.is_tracked(filename):
            self.rm_cached(filename)
        else:
            self.reset_path(filename)

    def commit(self, message: str) -> tuple[bool, str | None]:
        ok, out = run_command(["git", "commit", "-m", message], cwd=self.cwd)
        if ok:
            return True, ""
        if "nothing to commit" in out.lower():
            return False, None
        return False, out

    def push(self, branch: str, upstream: bool = False,
             force: bool = False) -> tuple[bool, str]:
        cmd = ["git", "push"]
        if upstream:
            cmd.append("-u")
        cmd += ["origin", branch]
        if force:
            cmd.append("--force")
        return run_command(cmd, cwd=self.cwd, timeout=DEFAULT_TIMEOUT)

    # ── 查询与恢复 ──
    def get_change_count(self) -> int:
        out = self.get_porcelain()
        if not out:
            return 0
        return len([line for line in out.splitlines() if line.strip()])

    def get_porcelain(self) -> str:
        # -c core.quotepath=false：非 ASCII 路径原样 UTF-8 输出，避免
        # 默认 quotepath 八进制转义（"\\ooo"）导致中文文件名乱码/推送路径错误
        ok, out = run_command(["git", "-c", "core.quotepath=false",
                               "status", "--porcelain"], cwd=self.cwd)
        return out if ok else ""

    def get_recent_commits(self, limit: int = 20) -> list[dict]:
        ok, out = run_command(["git", "log", f"-{limit}", "--format=%H %ai"],
                              cwd=self.cwd)
        if not ok or not out:
            return []
        commits = []
        for line in out.splitlines():
            if not line.strip():
                continue
            h, _, t = line.partition(" ")
            commits.append({"hash": h, "time": t[:19]})
        return commits

    def diff_name_status(self, base: str, head: str) -> str:
        """git diff --name-status <base>...<head>（三点：merge-base 到 head 的变更）。

        带 -c core.quotepath=false：与 get_porcelain 一致，非 ASCII 路径
        原样 UTF-8 输出，避免中文文件名八进制转义（AHEAD 推送页文件列表）。
        """
        ok, out = run_command(["git", "-c", "core.quotepath=false",
                               "diff", "--name-status",
                               f"{base}...{head}"], cwd=self.cwd)
        return out if ok else ""

    def remote_head(self, branch: str) -> str | None:
        ok, out = run_command(["git", "rev-parse", f"origin/{branch}"],
                              cwd=self.cwd)
        return out.strip() if ok and out.strip() else None

    def restore_to_commit(self, commit_hash: str) -> bool:
        ok, _ = run_command(["git", "reset", "--hard", commit_hash],
                            cwd=self.cwd)
        return ok

    def restore_to_tag(self, tag: str) -> bool:
        ok, _ = run_command(["git", "fetch", "origin"], cwd=self.cwd,
                            timeout=DEFAULT_TIMEOUT)
        if not ok:
            return False
        ok, _ = run_command(["git", "reset", "--hard", tag], cwd=self.cwd)
        return ok

    def clean_untracked(self) -> bool:
        """git clean -fd：删除未跟踪文件与目录（不传 -x，保留被 gitignore 的文件）。"""
        ok, _ = run_command(["git", "clean", "-fd"], cwd=self.cwd)
        return ok

    # ── 分支管理 ──
    def list_branches(self) -> list[str]:
        ok, out = run_command(["git", "branch", "--format=%(refname:short)"],
                              cwd=self.cwd)
        if not ok:
            return []
        return [line.strip() for line in out.splitlines() if line.strip()]

    def switch_branch(self, name: str, create: bool = False) -> tuple[bool, str]:
        cmd = ["git", "switch"]
        if create:
            cmd.append("-c")
        cmd.append(name)
        return run_command(cmd, cwd=self.cwd)

    def merge(self, branch: str) -> tuple[bool, str]:
        return run_command(["git", "merge", branch], cwd=self.cwd)

    def merge_abort(self) -> None:
        run_command(["git", "merge", "--abort"], cwd=self.cwd)
