"""领域层协议（接口）：GitProvider / GitHubProvider。

接口定义在领域层、实现在基础设施层（依赖倒置）。
上层（应用层/表现层）只依赖本协议，换实现不影响任何上层代码。
"""

from __future__ import annotations

from typing import Protocol, Sequence


class GitProvider(Protocol):
    """本地 Git 仓库操作抽象。"""

    cwd: str

    def get_status(self) -> dict:
        """返回 {"initialized": bool, "branch": str, "remote": str}"""
        ...

    def init_repo(self) -> None:
        """初始化 Git 仓库（git init）"""
        ...

    def create_ignore(self) -> None:
        """若不存在则创建默认 .gitignore"""
        ...

    def ensure_gitignore_entry(self, entry: str) -> None:
        """确保 .gitignore 包含指定条目（已有则跳过）"""
        ...

    def exclude_from_index(self, filename: str) -> None:
        """从索引排除文件：已跟踪则 rm --cached（保留本地），未跟踪则 reset"""
        ...

    def get_change_count(self) -> int:
        """工作区变更文件数（git status --porcelain）"""
        ...

    def get_porcelain(self) -> str:
        """git status --porcelain 原始输出（供变更解析）"""
        ...

    def get_recent_commits(self, limit: int = 20) -> list[dict]:
        """最近的提交列表：[{"hash": str, "time": str}]"""
        ...

    def restore_to_commit(self, commit_hash: str) -> bool:
        """硬恢复到指定 commit"""
        ...

    def restore_to_tag(self, tag: str) -> bool:
        """fetch 后硬恢复到指定 tag"""
        ...

    def current_branch(self) -> str:
        """当前分支名，回退 main"""
        ...

    def stage_all(self) -> tuple[bool, str]:
        """git add . 全部暂存"""
        ...

    def stage_paths(self, *paths: str) -> None:
        """暂存指定路径"""
        ...

    def commit(self, message: str) -> tuple[bool, str]:
        """提交。返回 (ok, detail)；(False, None) 表示无需提交"""
        ...

    def push(self, branch: str, upstream: bool = False, force: bool = False) -> tuple[bool, str]:
        """推送到 origin。force 为 True 时追加 --force"""
        ...

    def branch_to_main(self) -> None:
        """git branch -M main"""
        ...

    def set_remote(self, url: str) -> None:
        """设置 origin 远程地址（已存在则 set-url）"""
        ...

    def is_tracked(self, filename: str) -> bool:
        """文件是否已被 Git 跟踪"""
        ...

    def rm_cached(self, filename: str) -> tuple[bool, str]:
        """git rm -r --cached（从索引移除，保留本地）"""
        ...

    def reset_path(self, filename: str) -> None:
        """git reset HEAD -- 取消暂存"""
        ...

    def ensure_identity(self) -> None:
        """自动配置 Git 用户身份（name/email）"""
        ...

    def add_to_gitignore_file(self, entry: str) -> None:
        """向 .gitignore 追加条目"""
        ...

    def remove_from_gitignore_file(self, entry: str) -> None:
        """从 .gitignore 移除指定条目"""
        ...

    def has_gitignore(self) -> bool:
        """.gitignore 是否存在"""
        ...

    def read_gitignore(self) -> str:
        """读取 .gitignore 内容（不存在返回空串）"""
        ...


class GitHubProvider(Protocol):
    """GitHub 远程操作抽象（gh CLI / API 可替换）。"""

    def get_username(self) -> str | None:
        """获取 GitHub 用户名（gh api → git remote → 邻近仓库兜底）"""
        ...

    def get_repo_slug(self) -> str | None:
        """获取仓库 slug（owner/repo）"""
        ...

    def get_latest_release(self) -> dict | None:
        """最新 Release：{"tag": str, "published_at": str} 或 None"""
        ...

    def get_all_releases(self, limit: int = 20) -> list[str]:
        """全部 Release 标签列表"""
        ...

    def publish_release(self, tag: str, notes_body: str) -> bool:
        """创建/更新 Release（notes 为 changelog 正文），成功返回 True"""
        ...

    def repo_exists(self, slug: str) -> bool:
        """检查仓库是否存在"""
        ...
