"""StatusService：CLI 与交互模式的唯一状态来源。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from .protocols import GitProvider
from .status import (RepoInfo, RepoStatus, changelog_pending, decide_status,
                     parse_porcelain)


class StatusService:
    """组合 porcelain / fetch / ahead_behind 计算 RepoInfo。

    fetch 只与纯本地读（remote_url / porcelain）一波并行：refs 在 fetch
    末尾才更新，ahead_behind_upstream 必须在 fetch 完成后执行，否则
    rev-list 读到旧 refs，远程有新提交时误报 CLEAN/AHEAD（破坏 CLI
    输出契约与退出码）。fetch=False（TUI 启动路径）无此依赖，remote /
    porcelain / ahead_behind 三调用保持一波并行。remote 缺失时 fetch
    失败静默降级（fetch 只读，失败不影响本地状态判定）。
    """

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
        with ThreadPoolExecutor(max_workers=4) as ex:
            f_remote = ex.submit(self.git.remote_url)
            f_porcelain = ex.submit(self.git.get_porcelain)
            f_fetch = ex.submit(self.git.fetch) if fetch else None
            # fetch=True：ahead/behind 依赖 fetch 后的最新 refs，串行等待；
            # fetch=False：无顺序依赖，与本地读同波并行
            f_ab = ex.submit(self.git.ahead_behind_upstream) if not fetch else None
            remote = f_remote.result()
            if not remote:
                return RepoInfo(status=RepoStatus.NO_REMOTE, branch=branch,
                                path=self.repo_path)
            if f_fetch is not None:
                f_fetch.result()  # 只读；失败静默降级为本地状态
                ab = self.git.ahead_behind_upstream()
            else:
                ab = f_ab.result()
            ahead, behind = 0, 0
            if ab:
                ahead, behind = ab
            added, modified, deleted = parse_porcelain(f_porcelain.result())
        status = decide_status(ahead=ahead, behind=behind,
                               changes=added + modified + deleted)
        return RepoInfo(status=status, branch=branch, path=self.repo_path,
                        added=added, modified=modified, deleted=deleted,
                        ahead=ahead, behind=behind, remote_url=remote,
                        release_pending=changelog_pending(self.repo_path))
