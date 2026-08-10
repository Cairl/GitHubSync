"""StatusService：CLI 与交互模式的唯一状态来源。"""
from __future__ import annotations

from .protocols import GitProvider
from .status import RepoInfo, RepoStatus, decide_status, parse_porcelain


class StatusService:
    """组合 porcelain / fetch / ahead_behind 计算 RepoInfo。"""

    def __init__(self, git: GitProvider, repo_path: str):
        self.git = git
        self.repo_path = repo_path

    def get_status(self, fetch: bool = True) -> RepoInfo:
        """获取仓库状态快照；任何异常降级为 ERROR 状态而非抛出。"""
        try:
            return self._build(fetch)
        except Exception as e:
            return RepoInfo(status=RepoStatus.ERROR, branch="",
                            path=self.repo_path, error=str(e))

    def _build(self, fetch: bool) -> RepoInfo:
        st = self.git.get_status()
        if not st["initialized"]:
            return RepoInfo(status=RepoStatus.NO_REPO, branch="main",
                            path=self.repo_path)
        branch = st["branch"]
        remote = self.git.remote_url()
        if not remote:
            return RepoInfo(status=RepoStatus.NO_REMOTE, branch=branch,
                            path=self.repo_path)
        if fetch:
            self.git.fetch()  # 只读；失败静默降级为本地状态
        ahead, behind = 0, 0
        ab = self.git.ahead_behind(branch)
        if ab:
            ahead, behind = ab
        added, modified, deleted = parse_porcelain(self.git.get_porcelain())
        status = decide_status(ahead=ahead, behind=behind,
                               changes=added + modified + deleted)
        return RepoInfo(status=status, branch=branch, path=self.repo_path,
                        added=added, modified=modified, deleted=deleted,
                        ahead=ahead, behind=behind, remote_url=remote)
