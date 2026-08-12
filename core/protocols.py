"""Provider 协议：依赖倒置接口。

UI 与服务层只依赖本模块定义的协议；GitCLIProvider / GhCLIProvider /
tests.fakes 的 Fake 实现均为结构式满足（typing.Protocol）。
"""
from __future__ import annotations

from typing import Protocol


class GitProvider(Protocol):
    """git 子进程能力抽象。"""

    # ── 仓库状态 ──
    def get_status(self) -> dict:
        """返回 {"initialized": bool, "branch": str, "remote": str}。"""
        ...

    def current_branch(self) -> str:
        """当前分支名，回退 main。"""
        ...

    def remote_url(self) -> str | None:
        """origin 远程地址，未配置返回 None。"""
        ...

    def fetch(self) -> bool:
        """git fetch origin（只读；网络失败返回 False，调用方降级处理）。"""
        ...

    def ahead_behind(self, branch: str) -> tuple[int, int] | None:
        """相对 origin/<branch> 的 (ahead, behind)；无上游或失败返回 None。"""
        ...

    # ── 初始化与远程配置 ──
    def init_repo(self) -> None: ...

    def branch_to_main(self) -> None:
        """git branch -M main。"""
        ...

    def set_remote(self, url: str) -> None:
        """配置 origin（add 失败回退 set-url）。"""
        ...

    def ensure_identity(self, username: str = "User") -> None:
        """自动配置 git user.name / user.email。"""
        ...

    # ── gitignore 管理 ──
    def create_ignore(self) -> None:
        """创建默认 .gitignore（已存在则跳过）。"""
        ...

    def has_gitignore(self) -> bool: ...

    def read_gitignore(self) -> str: ...

    def ensure_gitignore_entry(self, entry: str) -> None:
        """确保 .gitignore 包含指定条目（已有则跳过）。"""
        ...

    def add_to_gitignore_file(self, entry: str) -> None: ...

    def remove_from_gitignore_file(self, entry: str) -> None: ...

    # ── 暂存与提交 ──
    def stage_all(self) -> tuple[bool, str]:
        """git add . → (成功, 输出)。"""
        ...

    def stage_paths(self, *paths: str) -> None: ...

    def is_tracked(self, filename: str) -> bool: ...

    def tracked_files(self) -> set[str]:
        """全部已跟踪文件集合（一次 git ls-files，避免逐文件子进程）。"""
        ...

    def rm_cached(self, filename: str) -> tuple[bool, str]:
        """git rm --cached（保留本地文件，移除跟踪）。"""
        ...

    def reset_path(self, filename: str) -> None:
        """git reset HEAD -- <file>（取消暂存）。"""
        ...

    def exclude_from_index(self, filename: str) -> None:
        """从索引排除：已跟踪则 rm --cached，未跟踪则取消暂存。"""
        ...

    def commit(self, message: str) -> tuple[bool, str | None]:
        """git commit；无暂存内容返回 (False, None)。"""
        ...

    def push(self, branch: str, upstream: bool = False,
             force: bool = False) -> tuple[bool, str]:
        """git push → (成功, 输出)。"""
        ...

    # ── 查询与恢复 ──
    def get_change_count(self) -> int: ...

    def get_porcelain(self) -> str:
        """git status --porcelain 原始输出。"""
        ...

    def diff_name_status(self, base: str, head: str) -> str:
        """git diff --name-status <base>...<head> 原始输出（本地领先提交涉及的文件）。"""
        ...

    def get_recent_commits(self, limit: int = 20) -> list[dict]:
        """[{"hash": str, "time": str}]，新的在前。"""
        ...

    def remote_head(self, branch: str) -> str | None:
        """远程跟踪引用 origin/<branch> 指向的 commit hash；无远程/失败返回 None。"""
        ...

    def restore_to_commit(self, commit_hash: str) -> bool:
        """git reset --hard <hash>（支持 origin/<branch>）。"""
        ...

    def restore_to_tag(self, tag: str) -> bool: ...

    def clean_untracked(self) -> bool:
        """git clean -fd：删除未跟踪文件与目录（被 gitignore 的保留）。"""
        ...

    # ── 分支管理 ──
    def list_branches(self) -> list[str]:
        """本地分支列表（含当前分支）；无仓库返回 []。"""
        ...

    def switch_branch(self, name: str, create: bool = False) -> tuple[bool, str]:
        """git switch [-c] <name> → (成功, 输出)。"""
        ...

    def merge(self, branch: str) -> tuple[bool, str]:
        """git merge <branch>（合入当前分支）→ (成功, 输出)。"""
        ...

    def merge_abort(self) -> None:
        """git merge --abort（冲突复原，不留半截合并状态）。"""
        ...


class GitHubProvider(Protocol):
    """gh 子进程能力抽象。"""

    def get_username(self) -> str | None:
        """GitHub 用户名（gh api → 本仓库 remote → 邻近仓库 remote）。"""
        ...

    def get_repo_slug(self) -> str | None:
        """owner/repo，无法确定返回 None。"""
        ...

    def get_latest_release(self) -> dict | None:
        """{"tag": str, "published_at": str} 或 None。"""
        ...

    def get_all_releases(self, limit: int = 20) -> list[str]: ...

    def publish_release(self, tag: str, notes_body: str) -> bool: ...

    def repo_exists(self, slug: str) -> bool: ...

    def ensure_repo_created(self, repo_name: str) -> str | None:
        """引导浏览器创建仓库并轮询等待，成功返回仓库 URL，超时返回 None。"""
        ...
