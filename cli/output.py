"""CLI 输出层：stdout/stderr 分流 + 纯函数渲染。

POSIX 分层契约：
- 结果数据走 stdout（status_line / diff 行 / info 字段 / --json）
- 诊断走 stderr（[OK]/[X]/[!]/> 前缀日志、ActionLog、错误消息）
- 着色按 isatty 自动决定，管道/重定向时无 ANSI（见 core/ansi.py）
"""
from __future__ import annotations

import sys
from dataclasses import asdict

from core.ansi import RESET, fg_sgr, render_markup, supports_color
from core.config import (COLOR_BRANCH, COLOR_ERROR, COLOR_GRAY, COLOR_SUCCESS,
                         COLOR_WARN)
from core.events import ActionLog
from core.i18n import tr
from core.status import RepoInfo, RepoStatus

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
    """status_line 的 markup 着色版（剥离标签后文本完全一致，语法见 core/ansi）。"""
    color = _STATUS_COLOR[info.status]
    line = status_line(info)
    if info.status in (RepoStatus.NO_REPO, RepoStatus.ERROR):
        return f"[{color}]{line}[/]"
    branch, sep, rest = line.partition(" · ")
    if not sep:
        return f"[{COLOR_BRANCH}]{line}[/]"
    return f"[{COLOR_BRANCH}]{branch}[/] · [{color}]{rest}[/]"


def info_to_dict(info: RepoInfo) -> dict:
    """RepoInfo → 可 JSON 序列化字典（status 为枚举名）。"""
    d = asdict(info)
    d["status"] = info.status.name
    return d


# ── 行输出（动态取 sys.stdout/sys.stderr，redirect 与 isatty 检测均正确）──
def echo(msg: str = "", *, markup: bool = False) -> None:
    """结果行输出走 stdout；markup=True 时解析着色标签（tty 才上色）。"""
    stream = sys.stdout
    if markup:
        msg = render_markup(msg, supports_color(stream))
    stream.write(msg + "\n")


def err(msg: str = "", *, markup: bool = False) -> None:
    """诊断行输出走 stderr；markup=True 时解析着色标签（tty 才上色）。"""
    stream = sys.stderr
    if markup:
        msg = render_markup(msg, supports_color(stream))
    stream.write(msg + "\n")


def _err_colored(msg: str, color: str) -> None:
    """单色诊断行：tty 时整行着 fg 色，否则纯文本。

    消息本体不经标签解析（直接拼 SGR 序列），含方括号的消息安全。
    """
    if supports_color(sys.stderr):
        err(f"{fg_sgr(color)}{msg}{RESET}")
    else:
        err(msg)


# ── 诊断输出（全部走 stderr）──
def print_success(msg: str) -> None:
    _err_colored(f"[OK] {msg}", COLOR_SUCCESS)


def print_warn(msg: str) -> None:
    _err_colored(f"[!] {msg}", COLOR_WARN)


def print_error(msg: str) -> None:
    _err_colored(f"[X] {msg}", COLOR_ERROR)


def print_step(msg: str) -> None:
    _err_colored(f"> {msg}", COLOR_GRAY)


def print_action_log(event: ActionLog, quiet: bool = False) -> None:
    """ActionLog → 单行最小日志（DONE/FAIL 始终显示，其余受 quiet 抑制）。"""
    if event.level == "DONE":
        print_success(event.message)
    elif event.level == "FAIL":
        print_error(event.message)
    elif not quiet:
        print_step(event.message)
