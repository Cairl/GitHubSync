"""测试共享：FakeProvider —— 内存版 Git/GitHub 协议实现。

让用例服务在不依赖真实 git/gh 与网络的情况下可单测。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class FakeGitProvider:
    """内存 Git 仓库：tracked/staged/files 三态 + 可配置失败模式。"""

    def __init__(self):
        self.cwd = "fake_repo"
        self.initialized = False
        self.remote = None          # None 表示未配置
        self.branch = "main"
        self.files: dict[str, str] = {}   # 工作区文件
        self.tracked: set[str] = set()
        self.staged: set[str] = set()
        self.commits: list[str] = []
        self.gitignore_lines: list[str] = ["__pycache__/", "changelog.md"]
        self.fail_mode = "ok"       # ok | repo_not_found | rejected | network
        self.force_push_calls = 0
        self.force_fail = False     # True 时强推也失败（模拟分支保护）
        self.push_branches: list[str] = []  # 每次 push 的目标分支（推送契约断言）
        self.identity_configured = False
        self.ahead = 0
        self.behind = 0
        self.fetch_ok = True
        self.fetch_calls = 0
        self.reset_to: str | None = None
        self.clean_ok = True
        self.clean_calls = 0
        self.remote_head_hash: str | None = None
        self.porcelain_calls = 0        # get_porcelain 调用计数（懒加载断言）
        self.ahead_diff = ""            # diff_name_status 输出（AHEAD 推送页文件显示注入）
        self.recent_commits_calls = 0   # get_recent_commits 调用计数
        self.branches: list[str] = ["main"]
        self.switch_calls: list[tuple[str, bool]] = []
        self.switch_ok = True
        self.merge_calls: list[str] = []
        self.merge_ok = True
        self.merge_abort_calls = 0
        self.list_branches_calls = 0    # list_branches 调用计数（懒加载断言）

    # ── GitProvider 协议 ──
    def get_status(self) -> dict:
        return {
            "initialized": self.initialized,
            "branch": self.branch,
            "remote": self.remote or "未配置",
        }

    def init_repo(self) -> None:
        self.initialized = True

    def create_ignore(self) -> None:
        if not self.has_gitignore():
            self.gitignore_lines = ["__pycache__/"]

    def ensure_gitignore_entry(self, entry: str) -> None:
        if entry not in self.gitignore_lines:
            self.gitignore_lines.append(entry)

    def has_gitignore(self) -> bool:
        return bool(self.gitignore_lines)

    def read_gitignore(self) -> str:
        return "\n".join(self.gitignore_lines) + "\n"

    def add_to_gitignore_file(self, entry: str) -> None:
        self.gitignore_lines.append(entry)

    def remove_from_gitignore_file(self, entry: str) -> None:
        self.gitignore_lines = [
            line for line in self.gitignore_lines if line.rstrip("/") != entry
        ]

    def exclude_from_index(self, filename: str) -> None:
        self.tracked.discard(filename)
        self.staged.discard(filename)

    def stage_all(self) -> tuple[bool, str]:
        # 与真实 git add . 一致：暂存新增与删除
        self.staged = ((set(self.files) - self.tracked)
                       | (self.tracked - set(self.files)))
        return True, ""

    def stage_paths(self, *paths: str) -> None:
        for p in paths:
            self.staged.add(p)

    def is_tracked(self, filename: str) -> bool:
        return filename in self.tracked

    def tracked_files(self) -> set[str]:
        return set(self.tracked)

    def rm_cached(self, filename: str) -> tuple[bool, str]:
        self.tracked.discard(filename)
        return True, ""

    def reset_path(self, filename: str) -> None:
        self.staged.discard(filename)

    def get_change_count(self) -> int:
        return len(set(self.files) - self.tracked)

    def get_porcelain(self) -> str:
        self.porcelain_calls += 1
        lines = []
        for f in sorted(set(self.files) - self.tracked):
            lines.append(f" M {f}")
        for f in sorted(self.tracked - set(self.files)):
            lines.append(f" D {f}")
        return "\n".join(lines)

    def get_recent_commits(self, limit: int = 20) -> list[dict]:
        self.recent_commits_calls += 1
        return [
            {"hash": c, "time": "2026-01-01 00:00:00"}
            for c in self.commits[-limit:][::-1]
        ]

    def diff_name_status(self, base: str, head: str) -> str:
        return self.ahead_diff

    def commit(self, message: str) -> tuple[bool, str | None]:
        if not self.staged:
            return False, None
        for f in self.staged:
            if f in self.files:
                self.tracked.add(f)
            else:
                self.tracked.discard(f)
        self.staged.clear()
        self.commits.append(f"commit-{len(self.commits) + 1}")
        return True, ""

    def push(self, branch: str, upstream: bool = False, force: bool = False) -> tuple[bool, str]:
        self.push_branches.append(branch)
        if force:
            self.force_push_calls += 1
            if self.force_fail:
                return False, "! [rejected] non-fast-forward"
            return True, ""  # 强制推送总是成功（模拟）
        if self.fail_mode == "repo_not_found":
            self.fail_mode = "ok"  # 首次失败后模拟"仓库已创建"
            return False, "remote: Repository not found."
        if self.fail_mode == "rejected":
            self.fail_mode = "ok"  # 首次失败后模拟"远程已接受"
            return False, "! [rejected] non-fast-forward"
        if self.fail_mode == "network":
            return False, "fatal: unable to access: Failed to connect"
        return True, ""

    def branch_to_main(self) -> None:
        self.branch = "main"

    def set_remote(self, url: str) -> None:
        self.remote = url

    def current_branch(self) -> str:
        return self.branch

    def ensure_identity(self, username: str = "User") -> None:
        self.identity_configured = True

    def fetch(self) -> bool:
        self.fetch_calls += 1
        return self.fetch_ok

    def ahead_behind(self, branch: str) -> tuple[int, int] | None:
        if self.remote is None:
            return None
        return self.ahead, self.behind

    def remote_head(self, branch: str) -> str | None:
        return self.remote_head_hash

    def remote_url(self) -> str | None:
        return self.remote

    def restore_to_commit(self, commit_hash: str) -> bool:
        # 支持 origin/<branch> 对齐与短 hash 前缀匹配
        if commit_hash == f"origin/{self.branch}":
            self.reset_to = commit_hash
            return True
        if any(c.startswith(commit_hash) for c in self.commits):
            self.reset_to = commit_hash
            return True
        return False

    def restore_to_tag(self, tag: str) -> bool:
        return True

    def clean_untracked(self) -> bool:
        self.clean_calls += 1
        return self.clean_ok

    # ── 分支管理 ──
    def list_branches(self) -> list[str]:
        self.list_branches_calls += 1
        return list(self.branches)

    def switch_branch(self, name: str, create: bool = False) -> tuple[bool, str]:
        self.switch_calls.append((name, create))
        if not self.switch_ok:
            return False, "fatal: invalid reference"
        if create and name not in self.branches:
            self.branches.append(name)
        if name not in self.branches:
            return False, f"fatal: invalid reference: {name}"
        self.branch = name
        return True, ""

    def merge(self, branch: str) -> tuple[bool, str]:
        self.merge_calls.append(branch)
        if not self.merge_ok:
            return False, "CONFLICT (content): Merge conflict"
        return True, ""

    def merge_abort(self) -> None:
        self.merge_abort_calls += 1


class FakeGitHubProvider:
    """内存 GitHub：用户名/仓库/Release 全可注入。"""

    def __init__(self, username: str = "octocat", slug: str = "octocat/repo"):
        self.username = username
        self.slug = slug
        self.latest_release: dict | None = None
        self.releases: list[str] = []
        self.published: list[tuple[str, str]] = []
        self.repo_created_url: str | None = None
        self.publish_ok = True

    def get_username(self) -> str | None:
        return self.username

    def get_repo_slug(self) -> str | None:
        return self.slug

    def get_latest_release(self) -> dict | None:
        return self.latest_release

    def get_all_releases(self, limit: int = 20) -> list[str]:
        return self.releases

    def publish_release(self, tag: str, notes_body: str) -> bool:
        self.published.append((tag, notes_body))
        return self.publish_ok

    def repo_exists(self, slug: str) -> bool:
        return self.repo_created_url is not None or slug == self.slug

    def ensure_repo_created(self, repo_name: str) -> str | None:
        self.repo_created_url = f"https://github.com/{self.username}/{repo_name}"
        return self.repo_created_url


def make_services(**git_kw):
    """交互/视图测试共用的 Services 工厂：FakeProvider 组装，支持属性注入。"""
    from core.branch_service import BranchService
    from core.events import DomainEventBus
    from core.file_ops_service import FileOpsService
    from core.release_service import ReleaseService
    from core.restore_service import RestoreService
    from core.services import Services
    from core.status_service import StatusService
    from core.sync_service import SyncService

    bus = DomainEventBus()
    git = FakeGitProvider()
    for k, v in git_kw.items():
        setattr(git, k, v)
    gh = FakeGitHubProvider()
    release = ReleaseService(gh, bus, "fake_repo")
    return Services(
        git=git, gh=gh, bus=bus,
        status=StatusService(git, "fake_repo"),
        sync=SyncService(git, gh, bus, "fake_repo", release),
        restore=RestoreService(git, bus),
        file_ops=FileOpsService(git, bus, "fake_repo"),
        release=release,
        branch=BranchService(git, bus),
    )
