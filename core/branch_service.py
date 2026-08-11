"""BranchService：切换 / 新建 / 合并到 main。

脏区（porcelain 非空，即有未提交变更）一律拒绝切换与合并；
合并到 main = switch main → merge 原分支 → push，任何一步失败
自动复原（merge --abort + 切回原分支），不留半截合并状态。
push 失败是例外：合并已完成，停在 main 报失败。
"""
from __future__ import annotations

from .events import ActionLog, DomainEventBus
from .i18n import tr
from .protocols import GitProvider

_DIRTY_MSG = ("有未提交的变更，请先推送", "Uncommitted changes; push first")


class BranchService:
    """分支用例服务：CLI 与 TUI 共用。"""

    def __init__(self, git: GitProvider, bus: DomainEventBus):
        self.git = git
        self.bus = bus

    def is_dirty(self) -> bool:
        """脏区 = 工作区或暂存区有未提交变更（porcelain 非空）。"""
        return bool(self.git.get_porcelain().strip())

    def switch(self, name: str, create: bool = False) -> tuple[bool, str]:
        """切换分支（create=True 新建并切换）；返回 (成功, 失败原因或空串)。"""
        if self.is_dirty():
            msg = tr(*_DIRTY_MSG)
            self.bus.publish(ActionLog("FAIL", msg))
            return False, msg
        ok, out = self.git.switch_branch(name, create=create)
        if ok:
            self.bus.publish(ActionLog(
                "DONE", tr(f"已切换到 {name}", f"Switched to {name}")))
            return True, ""
        msg = tr(f"切换分支失败: {out}", f"Failed to switch branch: {out}")
        self.bus.publish(ActionLog("FAIL", msg))
        return False, msg

    def merge_to_main(self) -> tuple[bool, str]:
        """当前分支合并到 main 并推送；返回 (成功, 失败原因或空串)。"""
        source = self.git.current_branch()
        if source == "main":
            return False, tr("已在 main 分支", "Already on main")
        if self.is_dirty():
            msg = tr(*_DIRTY_MSG)
            self.bus.publish(ActionLog("FAIL", msg))
            return False, msg
        self.bus.publish(ActionLog(
            "ACTION", tr(f"合并 {source} 到 main",
                         f"Merging {source} into main")))
        ok, out = self.git.switch_branch("main")
        if not ok:
            msg = tr(f"切换到 main 失败: {out}",
                     f"Failed to switch to main: {out}")
            self.bus.publish(ActionLog("FAIL", msg))
            return False, msg
        ok, out = self.git.merge(source)
        if not ok:
            # 冲突/失败：abort + 切回原分支，保证不留半截合并状态
            self.git.merge_abort()
            self.git.switch_branch(source)
            msg = tr(f"合并冲突或失败: {out}",
                     f"Merge conflict or failure: {out}")
            self.bus.publish(ActionLog("FAIL", msg))
            return False, msg
        ok, out = self.git.push("main")
        if not ok:
            msg = tr(f"推送 main 失败: {out}", f"Failed to push main: {out}")
            self.bus.publish(ActionLog("FAIL", msg))
            return False, msg  # 合并已完成，不 abort，停在 main
        self.bus.publish(ActionLog(
            "DONE", tr(f"已合并 {source} 到 main 并推送",
                       f"Merged {source} into main and pushed")))
        return True, ""
