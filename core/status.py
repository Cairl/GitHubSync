"""仓库状态模型：CLI 与交互模式的统一状态语言。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum, auto


class RepoStatus(Enum):
    """仓库同步状态。判定优先级：ERROR > NO_REPO > NO_REMOTE > DIVERGED > BEHIND > AHEAD > CHANGED > CLEAN。"""

    NO_REPO = auto()    # 不是 git 仓库
    NO_REMOTE = auto()  # 本地仓库，未配置远程
    CLEAN = auto()      # 已同步
    CHANGED = auto()    # 有未提交修改
    AHEAD = auto()      # 本地领先远程
    BEHIND = auto()     # 远程领先本地
    DIVERGED = auto()   # 双向分叉
    ERROR = auto()      # 状态检测失败


@dataclass(frozen=True)
class RepoInfo:
    """仓库状态快照。"""

    status: RepoStatus
    branch: str
    path: str
    added: int = 0
    modified: int = 0
    deleted: int = 0
    ahead: int = 0
    behind: int = 0
    remote_url: str | None = None
    error: str | None = None
    release_pending: bool = False  # 本地存在非空 changelog.md（Release 待发布）

    @property
    def change_count(self) -> int:
        """工作区变化文件总数。"""
        return self.added + self.modified + self.deleted


def parse_porcelain(output: str) -> tuple[int, int, int]:
    """git status --porcelain 输出 → (added, modified, deleted) 文件计数。"""
    added = modified = deleted = 0
    for line in output.splitlines():
        if len(line) < 3:
            continue
        x, y = line[0], line[1]
        if x == "?" and y == "?":
            added += 1
        elif x == "D" or y == "D":
            deleted += 1
        elif x == "A" or y == "A":
            added += 1
        else:
            modified += 1
    return added, modified, deleted


def decide_status(*, ahead: int, behind: int, changes: int) -> RepoStatus:
    """由 ahead/behind/changes 判定主状态（不含 NO_REPO/NO_REMOTE/ERROR）。"""
    if ahead and behind:
        return RepoStatus.DIVERGED
    if behind:
        return RepoStatus.BEHIND
    if ahead:
        return RepoStatus.AHEAD
    if changes:
        return RepoStatus.CHANGED
    return RepoStatus.CLEAN


# porcelain 两位状态码 → 单字母（R/T/U/C 归并到 M/A）
_DIFF_LETTERS = {"?": "A", "A": "A", "C": "A", "D": "D",
                 "R": "M", "M": "M", "T": "M", "U": "M"}


def format_diff(porcelain: str) -> list[str]:
    """porcelain → ["M  src/main.py", ...] 单字母变化列表。

    兼容 run_command 整体 strip 导致首行丢失前导空格的退化形式（"M a.py"）。
    CLI diff 子命令与 TUI 推送页共用（通用 porcelain 解析，属 core 层）。
    """
    lines = []
    for raw in porcelain.splitlines():
        if not raw.strip():
            continue
        if len(raw) >= 3 and raw[2] == " ":
            x, y, path = raw[0], raw[1], raw[3:]
        elif len(raw) >= 2:
            # 退化形式：首行前导空格被 strip，仅剩一位状态码
            x, y, path = raw[0], " ", raw[2:]
        else:
            continue
        letter = _DIFF_LETTERS.get(x if x != " " else y, "M")
        path = path.strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ")[-1].strip().strip('"')
        lines.append(f"{letter}  {path}")
    return lines


def changelog_pending(repo_path: str) -> bool:
    """本地存在非空 changelog.md（Release 待发布）。

    与 ReleaseService.maybe_publish 的触发条件一致（存在 + 非空）；
    changelog.md 被 gitignore 隔离，porcelain 不可见，需独立探测。
    """
    try:
        return os.path.getsize(os.path.join(repo_path, "changelog.md")) > 0
    except OSError:
        return False


def _is_changelog_row(row: str) -> bool:
    """format_diff 行是否为根目录 changelog.md（"X  changelog.md"）。"""
    return len(row) >= 3 and row[1] == " " and row[3:] == "changelog.md"


def append_local_changelog(rows: list[str], repo_path: str) -> list[str]:
    """format_diff 行末尾追加 "A  changelog.md"（本地待发布且行中未列出）。

    changelog.md 不入库（gitignore 隔离），推送列表通过此函数保持可见；
    仅追加不置底，置底由调用方处理。行中已含 changelog（如用户手动纳入
    同步）时不重复追加。
    """
    if any(_is_changelog_row(r) for r in rows):
        return rows
    if not changelog_pending(repo_path):
        return rows
    return rows + ["A  changelog.md"]
