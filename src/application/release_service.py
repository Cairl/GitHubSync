"""应用层：ReleaseService —— 版本号计算与 Release 发布用例。"""

from __future__ import annotations

import os
from datetime import datetime

from ..domain.events import ActionLog, DomainEventBus, ReleasePublished
from ..domain.protocols import GitHubProvider


class ReleaseService:
    def __init__(self, gh: GitHubProvider, bus: DomainEventBus, repo_path: str):
        self.gh = gh
        self.bus = bus
        self.repo_path = repo_path

    def maybe_publish(self) -> bool:
        """检测到 changelog.md 时自动发布 Release 并删除本地文件。成功返回 True"""
        releases_path = os.path.join(self.repo_path, "changelog.md")
        if not os.path.exists(releases_path):
            return False

        self.bus.publish(ActionLog("ACTION", "读取 changelog.md"))
        try:
            with open(releases_path, "r", encoding="utf-8") as f:
                body = f.read().strip()
        except OSError as e:
            self.bus.publish(ActionLog("FAIL", f"读取 changelog.md 失败: {e}"))
            return False
        if not body:
            return False

        tag = self.calculate_next_version(self.gh.get_latest_release())
        if not self.gh.get_repo_slug():
            self.bus.publish(ActionLog("NOTE", "跳过 Release 发布"))
            return False

        self.bus.publish(ActionLog("ACTION", f"发布 Release {tag}"))
        ok = self.gh.publish_release(tag, body)
        if not ok:
            self.bus.publish(ActionLog("FAIL", "gh release create/edit 失败"))
            return False

        self.bus.publish(ReleasePublished(tag))
        try:
            os.remove(releases_path)
            self.bus.publish(ActionLog("DONE", "删除 changelog.md"))
        except OSError as e:
            self.bus.publish(ActionLog("NOTE", f"删除 changelog.md 失败: {e}"))
        return True

    # ── 纯逻辑：版本号计算（可单测）──
    @staticmethod
    def _increment_alpha(seq: str) -> str:
        """Excel风格字母递增: a→b, z→aa, az→ba, zz→aaa"""
        s = list(seq)
        i = len(s) - 1
        while i >= 0:
            if s[i] < "z":
                s[i] = chr(ord(s[i]) + 1)
                return "".join(s)
            s[i] = "a"
            i -= 1
        return "a" + "".join(s)

    @staticmethod
    def calculate_next_version(latest: dict | None, now: datetime | None = None) -> str:
        """计算下一版本号（YYwWWa 格式，周内递增字母）。latest 为最新 Release 或 None"""
        import re

        now = now or datetime.now()
        yy = now.strftime("%y")
        week = now.isocalendar()[1]
        current_prefix = f"{yy}w{week:02d}"

        if not latest:
            return f"{current_prefix}a"

        m = re.match(r"^(\d{2}w\d{2})([a-z]+)$", latest.get("tag", ""))
        if not m:
            return f"{current_prefix}a"

        prev_prefix, prev_seq = m.group(1), m.group(2)
        if prev_prefix == current_prefix:
            return f"{current_prefix}{ReleaseService._increment_alpha(prev_seq)}"
        return f"{current_prefix}a"
