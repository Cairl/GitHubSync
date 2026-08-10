"""RestoreService：恢复到指定 commit / 本地对齐远程。"""
from __future__ import annotations

from .events import ActionLog, DomainEventBus, RestoreCompleted
from .i18n import tr
from .protocols import GitProvider


class RestoreService:
    """恢复服务：reset --hard 语义的两种入口。"""

    def __init__(self, git: GitProvider, bus: DomainEventBus):
        self.git = git
        self.bus = bus

    def restore(self, commit_hash: str) -> bool:
        """恢复到指定 commit（支持短 hash 前缀）。"""
        short = commit_hash[:8]
        self.bus.publish(ActionLog("ACTION", tr(f"恢复到 {short}",
                                                f"Restoring to {short}")))
        ok = self.git.restore_to_commit(commit_hash)
        if ok:
            self.bus.publish(ActionLog("DONE", tr(f"已恢复到 {short}",
                                                  f"Restored to {short}")))
            self.bus.publish(RestoreCompleted(commit_hash))
        else:
            self.bus.publish(ActionLog("FAIL", tr("恢复失败",
                                                  "Restore failed")))
        return ok

    def restore_remote(self) -> bool:
        """本地对齐远程：fetch 后 reset --hard origin/<branch>。"""
        branch = self.git.current_branch()
        self.bus.publish(ActionLog("ACTION", tr(f"对齐远程 origin/{branch}",
                                                f"Aligning with origin/{branch}")))
        if not self.git.fetch():
            self.bus.publish(ActionLog("FAIL", tr("获取远程状态失败",
                                                  "Failed to fetch remote")))
            return False
        ok = self.git.restore_to_commit(f"origin/{branch}")
        if ok:
            self.bus.publish(ActionLog("DONE", tr(f"已对齐 origin/{branch}",
                                                  f"Aligned with origin/{branch}")))
            self.bus.publish(RestoreCompleted(f"origin/{branch}"))
        else:
            self.bus.publish(ActionLog("FAIL", tr("对齐远程失败",
                                                  "Failed to align with remote")))
        return ok
