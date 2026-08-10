"""FileOpsService：文件级 include/exclude 与 gitignore 管理。

交互模式 [f] 文件视图的数据来源：扫描目录，结合 gitignore 匹配与
跟踪状态生成列表；push_file / remove_file 执行单文件纳入/排除同步。
"""
from __future__ import annotations

import os

from .events import ActionLog, DomainEventBus
from .gitignore_parser import GitignoreMatcher
from .i18n import tr
from .protocols import GitProvider

# 永不纳入文件列表的目录
_SKIP_NAMES = {".git"}


class FileOpsService:
    """文件级操作服务。"""

    def __init__(self, git: GitProvider, bus: DomainEventBus, repo_path: str):
        self.git = git
        self.bus = bus
        self.repo_path = repo_path

    def refresh_file_list(self) -> list[dict]:
        """扫描仓库目录，返回 [{name, ignored, tracked, is_dir, action_text}]。

        tracked 判断用一次 git ls-files 批量获取，避免逐文件子进程。
        """
        matcher = GitignoreMatcher(
            self.git.read_gitignore() if self.git.has_gitignore() else "")
        tracked = self.git.tracked_files()
        try:
            names = sorted(os.listdir(self.repo_path))
        except OSError:
            return []
        items = []
        for name in names:
            if name in _SKIP_NAMES:
                continue
            is_dir = os.path.isdir(os.path.join(self.repo_path, name))
            ignored = matcher.is_ignored(name, is_dir=is_dir)
            items.append({
                "name": name,
                "ignored": ignored,
                "tracked": name in tracked,
                "is_dir": is_dir,
                "action_text": (tr("纳入同步", "Include") if ignored
                                else tr("排除同步", "Exclude")),
            })
        return items

    def push_file(self, filename: str) -> None:
        """把被忽略的文件重新纳入同步：移出 gitignore → 暂存 → 提交 → 推送。"""
        self.bus.publish(ActionLog("ACTION", tr(f"推送 {filename}",
                                                f"Pushing {filename}")))
        self.git.remove_from_gitignore_file(filename)
        self.git.stage_paths(filename)
        ok, detail = self.git.commit(tr(f"添加 {filename}", f"Add {filename}"))
        if not ok and detail:
            self.bus.publish(ActionLog("FAIL", detail))
            return
        self._push()

    def remove_file(self, filename: str) -> None:
        """把文件排除出同步：加入 gitignore → 移除跟踪 → 提交 → 推送。"""
        self.bus.publish(ActionLog("ACTION", tr(f"排除 {filename}",
                                                f"Excluding {filename}")))
        self.git.add_to_gitignore_file(filename)
        self.git.exclude_from_index(filename)
        ok, detail = self.git.commit(tr(f"排除 {filename}",
                                        f"Exclude {filename}"))
        if not ok and detail:
            self.bus.publish(ActionLog("FAIL", detail))
            return
        self._push()

    def _push(self) -> None:
        branch = self.git.current_branch()
        ok, out = self.git.push(branch, upstream=True)
        if ok:
            self.bus.publish(ActionLog("DONE", tr("已推送到 GitHub",
                                                  "Pushed to GitHub")))
        else:
            self.bus.publish(ActionLog("FAIL", out))
