"""应用层：RestoreService —— 版本恢复用例。"""

from __future__ import annotations

from ..domain.events import ActionLog, DomainEventBus, RestoreCompleted
from ..domain.protocols import GitProvider


class RestoreService:
    def __init__(self, git: GitProvider, bus: DomainEventBus):
        self.git = git
        self.bus = bus

    def restore(self, commit_hash: str) -> bool:
        """恢复到指定 commit（reset --hard）。成功返回 True"""
        short = commit_hash[:8]
        self.bus.publish(ActionLog("ACTION", f"恢复到 {short}"))
        ok = self.git.restore_to_commit(commit_hash)
        if ok:
            self.bus.publish(ActionLog("DONE", f"已恢复到 {short}"))
            self.bus.publish(RestoreCompleted(commit_hash))
        else:
            self.bus.publish(ActionLog("FAIL", "恢复失败"))
        return ok
