"""ReleaseService：changelog.md → YYwWWa 版本号 GitHub Release。

版本号规则：<年两位>w<ISO周两位><字母序列>，如 26w32a；
同周递增字母（a→b→…→z→aa），跨周重置为 a；无法识别的历史 tag 重置。
"""
from __future__ import annotations

import os
import re
from datetime import datetime

from .events import ActionLog, DomainEventBus, ReleasePublished
from .i18n import tr
from .protocols import GitHubProvider


def _increment_alpha(seq: str) -> str:
    """Excel 风格字母递增：a→b，z→aa，az→ba，zz→aaa。"""
    s = list(seq)
    i = len(s) - 1
    while i >= 0:
        if s[i] < "z":
            s[i] = chr(ord(s[i]) + 1)
            return "".join(s)
        s[i] = "a"
        i -= 1
    return "a" + "".join(s)


class ReleaseService:
    """检测 changelog.md 并发布 Release，成功后删除本地 changelog。"""

    def __init__(self, gh: GitHubProvider, bus: DomainEventBus, repo_path: str):
        self.gh = gh
        self.bus = bus
        self.repo_path = repo_path

    @staticmethod
    def calculate_next_version(latest: dict | None,
                               now: datetime | None = None) -> str:
        """根据最新 Release tag 计算下一版本号（纯函数）。"""
        now = now or datetime.now()
        prefix = f"{now.strftime('%y')}w{now.isocalendar()[1]:02d}"
        if not latest:
            return f"{prefix}a"
        m = re.match(r"^(\d{2}w\d{2})([a-z]+)$", latest.get("tag", ""))
        if not m or m.group(1) != prefix:
            return f"{prefix}a"
        return f"{prefix}{_increment_alpha(m.group(2))}"

    def maybe_publish(self) -> bool:
        """存在非空 changelog.md 时发布 Release 并删除该文件。"""
        changelog = os.path.join(self.repo_path, "changelog.md")
        if not os.path.exists(changelog):
            return False
        try:
            with open(changelog, "r", encoding="utf-8") as f:
                body = f.read().strip()
        except OSError:
            return False
        if not body:
            return False
        tag = self.calculate_next_version(self.gh.get_latest_release())
        self.bus.publish(ActionLog("ACTION", tr(f"发布 Release {tag}",
                                                f"Publishing release {tag}")))
        if not self.gh.publish_release(tag, body):
            self.bus.publish(ActionLog("FAIL", tr("Release 发布失败",
                                                  "Release publish failed")))
            return False
        try:
            os.remove(changelog)
        except OSError:
            pass
        self.bus.publish(ActionLog("DONE", tr(f"已发布 {tag}",
                                              f"Published {tag}")))
        self.bus.publish(ReleasePublished(tag, body))
        return True
