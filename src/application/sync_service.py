"""应用层：SyncService —— 核心同步用例。

迁移自旧 GitManager.sync：扫描 → 排除 changelog.md → 提交 → 推送 →
失败分类处理（仓库不存在则引导创建重试 / 非快进则强制推送）→ Release。
通过事件总线发布进度，通过领域异常体系分类错误，无任何 UI 依赖。
"""

from __future__ import annotations

import os
import re
from datetime import datetime

from ..domain.events import (
    ActionLog, DomainEventBus, SyncCompleted, SyncFailed, SyncStarted,
)
from ..domain.exceptions import (
    PushRejectedError, RepoNotFoundError, SyncError, classify_push_error,
)
from ..domain.protocols import GitProvider, GitHubProvider
from .release_service import ReleaseService


class SyncService:
    def __init__(
        self,
        git: GitProvider,
        gh: GitHubProvider,
        bus: DomainEventBus,
        repo_path: str,
        release_service: ReleaseService,
    ):
        self.git = git
        self.gh = gh
        self.bus = bus
        self.repo_path = repo_path
        self.release_service = release_service

    def run(self) -> SyncCompleted:
        """执行完整同步流程。成功返回 SyncCompleted；失败抛 SyncError 子类。"""
        self.bus.publish(SyncStarted())
        try:
            self._prepare()
            updated = self._scan_changes()
            committed = self._commit(updated)
            pushed = self._push()
            release_published = False
            if pushed:
                release_published = self.release_service.maybe_publish()
            result = SyncCompleted(
                committed=committed,
                pushed=pushed,
                release_published=release_published,
                updated_items=updated,
            )
            self.bus.publish(result)
            self.bus.publish(ActionLog("DONE", "同步完成"))
            return result
        except SyncError as e:
            self.bus.publish(ActionLog("FAIL", str(e)))
            self.bus.publish(SyncFailed(message=str(e)))
            raise

    # ── 准备：初始化 / gitignore / 远程 ──
    def _prepare(self) -> None:
        self.git.create_ignore()
        self.git.ensure_gitignore_entry("changelog.md")

        status = self.git.get_status()
        if not status["initialized"]:
            self.bus.publish(ActionLog("ACTION", "初始化 Git 仓库"))
            self.git.init_repo()
            status = self.git.get_status()

        self.bus.publish(ActionLog("ACTION", "扫描变更"))
        ok, out = self.git.stage_all()
        if not ok:
            raise SyncError("git add 失败", out)

        # changelog.md 仅用于 Release 发布，不进入 Git 历史
        self.git.exclude_from_index("changelog.md")

        if status["remote"] == "未配置":
            self._configure_remote()

    def _configure_remote(self) -> None:
        username = self.gh.get_username()
        if not username:
            self.bus.publish(ActionLog("NOTE", "无法获取 GitHub 用户名"))
            raise SyncError("无法获取 GitHub 用户名")
        url = f"https://github.com/{username}/{os.path.basename(self.repo_path)}"
        self.bus.publish(ActionLog("ACTION", "配置远程仓库"))
        self.git.set_remote(url)

    # ── 变更解析与提交 ──
    def _scan_changes(self) -> dict:
        """解析 git status --porcelain 为 {顶层路径: 'A'|'D'}，跳过 changelog.md"""
        st = self.git.get_porcelain()
        updated: dict = {}
        if not st:
            return updated
        for line in st.splitlines():
            if len(line) <= 3:
                continue
            status_char = line[0] if line[0] != " " else line[1]
            path = line[3:].strip().strip('"')
            if " -> " in path:
                path = path.split(" -> ")[-1].strip().strip('"')
            parts = re.split(r"[\\/]", path)
            if parts:
                if parts[0] == "changelog.md":
                    continue
                updated[parts[0]] = "D" if status_char == "D" else "A"
        return updated

    def _commit(self, updated: dict) -> int:
        if not updated:
            self.bus.publish(ActionLog("NOTE", "没有更改需要提交"))
            return 0
        msg = f"Update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        self.bus.publish(ActionLog("ACTION", "提交"))
        ok, detail = self.git.commit(msg)
        if not ok:
            if detail:
                raise SyncError("提交失败", detail)
            return 0
        return len(updated)

    # ── 推送与失败恢复 ──
    def _push(self) -> bool:
        self.git.branch_to_main()
        self.bus.publish(ActionLog("ACTION", "推送 GitHub"))
        ok, out = self.git.push("main", upstream=True)
        if ok:
            return True
        return self._recover_push_failure(out)

    def _recover_push_failure(self, out: str) -> bool:
        """按错误类型决定恢复策略；无法恢复时抛出分类异常。"""
        err = classify_push_error(out)

        if isinstance(err, RepoNotFoundError):
            # 仓库不存在：引导浏览器创建，完成后重推
            repo_name = os.path.basename(self.repo_path)
            remote_url = self.gh.ensure_repo_created(repo_name)
            if remote_url:
                self.git.set_remote(remote_url)
                self.bus.publish(ActionLog("ACTION", "重新推送"))
                ok, out2 = self.git.push("main", upstream=True)
                if ok:
                    return True
                raise classify_push_error(out2)
            raise err

        if isinstance(err, PushRejectedError):
            # 非快进：强制推送
            self.bus.publish(ActionLog("ACTION", "强制推送"))
            ok, out2 = self.git.push("main", upstream=True, force=True)
            if ok:
                return True
            raise classify_push_error(out2)

        raise err
