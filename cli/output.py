"""CLI 输出层：双 Console 分流 + 纯函数渲染。

POSIX 分层契约：
- 结果数据走 stdout（status_line / diff 行 / info 字段 / --json）
- 诊断走 stderr（[OK]/[X]/[!]/> 前缀日志、ActionLog、错误消息）
- 着色由 Rich Console 按 isatty 自动决定，管道/重定向时无 ANSI
"""
from __future__ import annotations

import sys
from dataclasses import asdict

from rich.console import Console

from core.config import (COLOR_BRANCH, COLOR_ERROR, COLOR_GRAY, COLOR_SUCCESS,
                         COLOR_WARN, STYLE_GRAY, STYLE_GREEN, STYLE_RED,
                         STYLE_YELLOW)
from core.events import ActionLog
from core.i18n import tr
from core.status import RepoInfo, RepoStatus

# 不指定 file：Rich 在写入时动态取 sys.stdout/sys.stderr，
# 使 redirect_stdout/redirect_stderr 与管道检测（isatty）均正确工作。
stdout_console = Console(highlight=False)
stderr_console = Console(stderr=True, highlight=False)
console = stderr_console  # 兼容别名：诊断语义

# 状态语义色：仅成功/警告/错误/次要
_STATUS_COLOR = {
    RepoStatus.CLEAN: COLOR_SUCCESS,
    RepoStatus.CHANGED: COLOR_WARN,
    RepoStatus.AHEAD: COLOR_WARN,
    RepoStatus.BEHIND: COLOR_WARN,
    RepoStatus.DIVERGED: COLOR_ERROR,
    RepoStatus.ERROR: COLOR_ERROR,
    RepoStatus.NO_REPO: COLOR_GRAY,
    RepoStatus.NO_REMOTE: COLOR_GRAY,
}


def _changes_segment(info: RepoInfo) -> str:
    """变化计数段：3 changes (+1 ~2) / 3 处变化 (+1 ~2)。"""
    parts = []
    if info.added:
        parts.append(f"+{info.added}")
    if info.modified:
        parts.append(f"~{info.modified}")
    if info.deleted:
        parts.append(f"-{info.deleted}")
    detail = f" ({' '.join(parts)})" if parts else ""
    return tr(f"{info.change_count} 处变化{detail}",
              f"{info.change_count} changes{detail}")


def status_line(info: RepoInfo) -> str:
    """单行纯文本状态：main · synced / main · 3 changes (+1 ~2)。"""
    if info.status == RepoStatus.ERROR:
        return tr(f"错误: {info.error}", f"error: {info.error}")
    if info.status == RepoStatus.NO_REPO:
        return tr("不是 git 仓库", "not a git repository")
    if info.status == RepoStatus.NO_REMOTE:
        return f"{info.branch} · {tr('未配置远程', 'no remote')}"
    segs = [info.branch]
    if info.status == RepoStatus.DIVERGED:
        segs.append(tr(f"分叉 (领先 {info.ahead}, 落后 {info.behind})",
                       f"diverged (ahead {info.ahead}, behind {info.behind})"))
    elif info.status == RepoStatus.AHEAD:
        segs.append(tr(f"领先 {info.ahead}", f"ahead {info.ahead}"))
    elif info.status == RepoStatus.BEHIND:
        segs.append(tr(f"落后 {info.behind}", f"behind {info.behind}"))
    elif info.status == RepoStatus.CHANGED:
        segs.append(_changes_segment(info))
    else:  # CLEAN
        segs.append(tr("已同步", "synced"))
    return " · ".join(segs)


def status_markup(info: RepoInfo) -> str:
    """status_line 的 Rich markup 着色版（剥离标签后文本完全一致）。"""
    color = _STATUS_COLOR[info.status]
    line = status_line(info)
    if info.status in (RepoStatus.NO_REPO, RepoStatus.ERROR):
        return f"[{color}]{line}[/]"
    branch, sep, rest = line.partition(" · ")
    if not sep:
        return f"[{COLOR_BRANCH}]{line}[/]"
    return f"[{COLOR_BRANCH}]{branch}[/] · [{color}]{rest}[/]"


# porcelain 两位状态码 → 单字母（R/T/U/C 归并到 M/A）
_DIFF_LETTERS = {"?": "A", "A": "A", "C": "A", "D": "D",
                 "R": "M", "M": "M", "T": "M", "U": "M"}


def format_diff(porcelain: str) -> list[str]:
    """porcelain → ["M  src/main.py", ...] 单字母变化列表。

    兼容 run_command 整体 strip 导致首行丢失前导空格的退化形式（"M a.py"）。
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


def info_to_dict(info: RepoInfo) -> dict:
    """RepoInfo → 可 JSON 序列化字典（status 为枚举名）。"""
    d = asdict(info)
    d["status"] = info.status.name
    return d


# ── 诊断输出（全部走 stderr）──
def print_success(msg: str) -> None:
    stderr_console.print(f"[OK] {msg}", style=STYLE_GREEN, markup=False)


def print_warn(msg: str) -> None:
    stderr_console.print(f"[!] {msg}", style=STYLE_YELLOW, markup=False)


def print_error(msg: str) -> None:
    stderr_console.print(f"[X] {msg}", style=STYLE_RED, markup=False)


def print_step(msg: str) -> None:
    stderr_console.print(f"> {msg}", style=STYLE_GRAY, markup=False)


def print_action_log(event: ActionLog, quiet: bool = False) -> None:
    """ActionLog → 单行最小日志（DONE/FAIL 始终显示，其余受 quiet 抑制）。"""
    if event.level == "DONE":
        print_success(event.message)
    elif event.level == "FAIL":
        print_error(event.message)
    elif not quiet:
        print_step(event.message)
