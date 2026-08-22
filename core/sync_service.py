"""SyncService：全量同步编排（初始化 → 暂存 → 提交 → 推送 → Release）。

推送语义（1:1，已批准行为变更）：本地目录是唯一事实来源；
推送目标为当前分支（仅建仓初始化时改名一次 main，此后不动分支名）；
普通 push 被拒（分叉）时自动强制推送，丢弃远程独有提交，不再抛错。
"""
from __future__ import annotations

import os
from datetime import datetime

from .events import ActionLog, DomainEventBus, SyncCompleted, SyncFailed
from .exceptions import (PushRejectedError, RepoNotFoundError, SyncError,
                         classify_push_error)
from .i18n import tr
from .protocols import GitProvider, GitHubProvider
from .release_service import ReleaseService


class SyncService:
    """全量同步服务：CLI push 子命令与交互模式共用。"""

    def __init__(self, git: GitProvider, gh: GitHubProvider,
                 bus: DomainEventBus, repo_path: str, release: ReleaseService):
        self.git = git
        self.gh = gh
        self.bus = bus
        self.repo_path = repo_path
        self.release = release

    def run(self) -> SyncCompleted:
        """执行完整同步流程。分叉时自动强推（本地 1:1 覆盖远程）。"""
        try:
            return self._run()
        except SyncError as e:
            self.bus.publish(SyncFailed(e.message))
            raise

    # ── 主流程 ──
    def _run(self) -> SyncCompleted:
        git = self.git
        git.create_ignore()
        # changelog.md 不入库：gitignore 隔离新文件（Release 仍读本地文件发布，
        # 见下方 maybe_publish）；历史已入库的残留由 stage 后 rm_cached 清理
        git.ensure_gitignore_entry("changelog.md")

        st = git.get_status()
        if not st["initialized"]:
            self.bus.publish(ActionLog("ACTION", tr("初始化 Git 仓库",
                                                    "Initializing git repository"),
                                       stage="init"))
            git.init_repo()
            # 仅建仓时改名一次 main；此后同步不动分支名（推当前分支）
            git.branch_to_main()
            self.bus.publish(ActionLog("DONE", tr("仓库已初始化",
                                                  "Repository initialized"),
                                       stage="init"))
        if not git.remote_url():
            self._configure_remote()

        self.bus.publish(ActionLog("ACTION", tr("扫描更改", "Scanning changes"),
                                   stage="scan"))
        ok, out = git.stage_all()
        if not ok:
            raise SyncError(tr("暂存文件失败", "Failed to stage files"), out)
        self.bus.publish(ActionLog("DONE", tr("扫描完成", "Scanning complete"),
                                   stage="scan"))

        # 已跟踪的 changelog.md（旧版入库残留）：从索引移除（本地文件保留），
        # 本次提交删除并推送，远端清掉残留；从未跟踪/已清理的仓库此检查跳过
        if git.is_tracked("changelog.md"):
            git.rm_cached("changelog.md")

        updated_items = self._collect_updated_items()
        if updated_items:
            self.bus.publish(ActionLog(
                "PROGRESS",
                tr(f"{len(updated_items)} 项更改",
                   f"{len(updated_items)} change(s)"),
                stage="scan"))
        committed = 0
        if updated_items:
            committed = self._commit(updated_items)
            if committed:
                self.bus.publish(ActionLog(
                    "PROGRESS",
                    tr(f"已提交 {len(updated_items)} 项更改",
                       f"Committed {len(updated_items)} change(s)"),
                    stage="commit"))
        else:
            self.bus.publish(ActionLog("NOTE", tr("没有需要提交的更改",
                                                  "No changes to commit"),
                                       stage="commit"))

        self.bus.publish(ActionLog("ACTION", tr("推送到 GitHub",
                                                "Pushing to GitHub"),
                                   stage="push"))
        self._push_with_recovery()
        self.bus.publish(ActionLog("DONE", tr("推送完成", "Push completed"),
                                   stage="push"))

        # 推送后发布 Release：从本地读取 changelog.md 内容发布；
        # changelog.md 不入库（gitignore 隔离），远端无残留，无需提交删除
        self.release.maybe_publish()

        result = SyncCompleted(pushed=True, committed=committed,
                               updated_items=updated_items)
        self.bus.publish(result)
        return result

    # ── 子步骤 ──
    def _configure_remote(self) -> None:
        """按 GitHub 用户名 + 目录名自动配置 origin。"""
        username = self.gh.get_username()
        if not username:
            raise SyncError(tr("无法获取 GitHub 用户名，请先 gh auth login",
                               "Unable to determine GitHub username; run gh auth login"))
        repo_name = os.path.basename(self.repo_path.rstrip("\\/"))
        url = f"https://github.com/{username}/{repo_name}"
        self.bus.publish(ActionLog("ACTION", tr(f"配置远程仓库 {url}",
                                                f"Configuring remote {url}"),
                                   stage="config"))
        self.git.set_remote(url)
        self.bus.publish(ActionLog("DONE", tr("远程仓库已配置",
                                              "Remote configured"),
                                   stage="config"))

    def _collect_updated_items(self) -> dict[str, str]:
        """从 porcelain 提取顶层变化项：{顶层路径: 'A'/'D'}。"""
        items: dict[str, str] = {}
        for line in self.git.get_porcelain().splitlines():
            if len(line) <= 3:
                continue
            status_char = line[0] if line[0] != " " else line[1]
            path = line[3:].strip().strip('"')
            if " -> " in path:
                path = path.split(" -> ")[-1].strip().strip('"')
            top = path.replace("\\", "/").split("/")[0]
            if not top:
                continue
            items[top] = "D" if status_char == "D" else "A"
        return items

    def _commit(self, updated_items: dict[str, str]) -> int:
        """提交暂存内容；身份缺失时自动配置后重试一次。返回提交数（0/1）。"""
        message = f"Update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        ok, detail = self.git.commit(message)
        if not ok and detail and self._is_identity_error(detail):
            self.git.ensure_identity(self.gh.get_username() or "User")
            ok, detail = self.git.commit(message)
        if not ok:
            if detail:
                raise SyncError(tr("提交失败", "Commit failed"), detail)
            return 0  # 无暂存内容
        self.bus.publish(ActionLog(
            "DONE", tr(f"已提交 {len(updated_items)} 项更改",
                       f"Committed {len(updated_items)} change(s)"),
            stage="commit"))
        return 1

    @staticmethod
    def _is_identity_error(detail: str) -> bool:
        m = detail.lower()
        return "author identity" in m or "user.name" in m

    def _push_with_recovery(self) -> None:
        """推送与失败恢复：建仓引导 / 分叉自动强推；其余错误分类抛出。"""
        branch = self.git.current_branch()

        def on_progress(text: str) -> None:
            self.bus.publish(ActionLog("PROGRESS", text, stage="push"))

        ok, out = self.git.push(branch, upstream=True, on_progress=on_progress)
        if ok:
            return
        err = classify_push_error(out)
        if isinstance(err, RepoNotFoundError):
            # 仓库不存在：浏览器引导建仓 + 轮询，成功后重推
            repo_name = os.path.basename(self.repo_path.rstrip("\\/"))
            url = self.gh.ensure_repo_created(repo_name)
            if not url:
                raise err
            self.git.set_remote(url)
            self.bus.publish(ActionLog("ACTION", tr("重新推送",
                                                    "Retrying push"),
                                       stage="push"))
            ok, out = self.git.push(branch, upstream=True,
                                    on_progress=on_progress)
            if ok:
                return
            raise classify_push_error(out)
        if isinstance(err, PushRejectedError):
            # 分叉：本地 1:1 覆盖远程，自动强推
            self.bus.publish(ActionLog("ACTION", tr(
                "检测到分叉，强制推送（丢弃远程独有提交）",
                "Diverged; force pushing (discarding remote-only commits)"),
                stage="push"))
            ok, out = self.git.push(branch, upstream=True, force=True,
                                    on_progress=on_progress)
            if ok:
                return
            raise classify_push_error(out)
        raise err
