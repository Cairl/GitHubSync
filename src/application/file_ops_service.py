"""应用层：FileOpsService —— 文件级操作用例（推送模式）。

集中旧 App 中散落的文件级逻辑：列表扫描（含完整 gitignore 判断）、
单文件推送/删除、物理删除。经事件总线发布进度，可无 UI 测试。
"""

from __future__ import annotations

import os
import shutil

from ..domain.events import ActionLog, DomainEventBus, FileChanged
from ..domain.exceptions import classify_push_error
from ..domain.protocols import GitProvider
from ..infrastructure.gitignore_parser import GitignoreMatcher


class FileOpsService:
    def __init__(self, git: GitProvider, bus: DomainEventBus, repo_path: str):
        self.git = git
        self.bus = bus
        self.repo_path = repo_path

    # ── 列表扫描 ──
    def refresh_file_list(self) -> list[dict]:
        """扫描目录生成文件列表（完整 gitignore 规范判断）。"""
        items: list[dict] = []
        try:
            entries = os.listdir(self.repo_path)
            dirs = sorted(
                e for e in entries
                if e != ".git" and os.path.isdir(os.path.join(self.repo_path, e))
            )
            files = sorted(
                e for e in entries
                if e != ".git" and not os.path.isdir(os.path.join(self.repo_path, e))
            )
            matcher = GitignoreMatcher(self.git.read_gitignore())
            for name in dirs + files:
                is_dir = os.path.isdir(os.path.join(self.repo_path, name))
                ignored = matcher.is_ignored(name, is_dir)
                items.append({
                    "name": name,
                    "ignored": ignored,
                    "action_text": "推送" if ignored else "删除",
                    "tag_text": "(已忽略)" if ignored else "",
                })
            if not items:
                items.append({"name": "(空目录)", "ignored": False,
                              "action_text": "", "tag_text": ""})
        except Exception as e:
            self.bus.publish(ActionLog("NOTE", f"刷新文件列表异常: {e}"))
        return items

    # ── 文件操作 ──
    def push_file(self, name: str) -> bool:
        """推送文件到 GitHub：移除 gitignore → add → commit → push"""
        self.bus.publish(ActionLog("ACTION", f"推送: {name}"))
        try:
            self.git.remove_from_gitignore_file(name)
        except OSError as e:
            self.bus.publish(ActionLog("NOTE", f"移除忽略异常: {e}"))
        self.git.stage_paths(".gitignore", name)

        ok, detail = self.git.commit(f"Add: {name}")
        if not ok and detail:
            self.bus.publish(ActionLog("FAIL", f"提交失败: {detail}"))
            return False

        branch = self.git.current_branch()
        ok, out = self.git.push(branch)
        if not ok:
            self.bus.publish(ActionLog("FAIL", str(classify_push_error(out))))
            return False
        self.bus.publish(ActionLog("DONE", f"推送完成: {name}"))
        self.bus.publish(FileChanged(name, "A"))
        return True

    def remove_file(self, name: str) -> bool:
        """从 GitHub 删除文件：rm --cached → 加入 gitignore → commit → push"""
        self.bus.publish(ActionLog("ACTION", f"删除: {name}"))
        if self.git.is_tracked(name):
            ok, detail = self.git.rm_cached(name)
            if not ok:
                self.bus.publish(ActionLog("FAIL", detail))
                return False
        try:
            self.git.add_to_gitignore_file(name)
        except OSError as e:
            self.bus.publish(ActionLog("NOTE", f"添加忽略异常: {e}"))
        self.git.stage_paths(".gitignore")

        ok, detail = self.git.commit(f"Delete: {name}")
        if not ok and detail:
            self.bus.publish(ActionLog("FAIL", f"提交失败: {detail}"))
            return False

        branch = self.git.current_branch()
        ok, out = self.git.push(branch)
        if not ok:
            self.bus.publish(ActionLog("FAIL", str(classify_push_error(out))))
            return False
        self.bus.publish(ActionLog("DONE", f"删除完成: {name}"))
        self.bus.publish(FileChanged(name, "D"))
        return True

    def physical_delete(self, name: str) -> bool:
        """物理删除本地文件/目录（由 UI 确认后调用）。"""
        path = os.path.join(self.repo_path, name)
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            self.bus.publish(ActionLog("DONE", f"已物理删除: {name}"))
            return True
        except OSError as e:
            self.bus.publish(ActionLog("FAIL", f"物理删除失败: {e}"))
            return False
