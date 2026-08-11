"""仓库状态模型：CLI 与交互模式的统一状态语言。"""
from __future__ import annotations

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
