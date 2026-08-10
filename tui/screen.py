"""交互模式渲染：纯函数，RepoInfo → Rich markup 文本。零 I/O、零子进程。

顶栏布局：项目/分支·状态/主页 / 空行 / 菜单块（#292929 背景三行）/ 空行。
"""
from __future__ import annotations

import re

from core.config import (COLOR_BRANCH_NAME, COLOR_LABEL, COLOR_MENU_BG,
                         COLOR_URL)
from core.i18n import tr
from core.status import RepoInfo, RepoStatus
from core.utils import get_display_width

_MARKUP_RE = re.compile(r"\[/?[^\]]*\]")


def recommended_action(info: RepoInfo) -> tuple[str, str]:
    """状态 → (action_id, 标签)。action_id ∈ push/restore_remote/diff/refresh。"""
    if info.status in (RepoStatus.CHANGED, RepoStatus.AHEAD,
                       RepoStatus.NO_REPO, RepoStatus.NO_REMOTE):
        return "push", tr("推送", "Push")
    if info.status == RepoStatus.BEHIND:
        return "restore_remote", tr("对齐远程", "Restore")
    if info.status == RepoStatus.DIVERGED:
        return "diff", tr("查看差异", "Diff")
    return "refresh", tr("刷新", "Refresh")


def _status_detail(info: RepoInfo) -> str:
    """状态详情（括号内文案）；CHANGED 无变化时返回空串（隐藏括号）。"""
    if info.status == RepoStatus.CHANGED:
        # 顶栏仅显示变化文件总数，具体文件由内容区变更列表展示
        return f"+{info.change_count}" if info.change_count else ""
    if info.status == RepoStatus.AHEAD:
        return tr(f"领先远程 {info.ahead} 个提交",
                  f"{info.ahead} commit(s) to push")
    if info.status == RepoStatus.BEHIND:
        return tr(f"远程有 {info.behind} 个新提交",
                  f"{info.behind} commit(s) to pull")
    if info.status == RepoStatus.DIVERGED:
        return tr(f"分叉: {info.ahead} 个提交待推送, {info.behind} 个待拉取",
                  f"diverged: {info.ahead} commit(s) to push, {info.behind} to pull")
    if info.status == RepoStatus.CLEAN:
        return tr("已同步，工作区干净。", "Synced, working tree clean.")
    if info.status == RepoStatus.NO_REPO:
        return tr("尚未初始化 git 仓库。", "Not a git repository yet.")
    if info.status == RepoStatus.NO_REMOTE:
        return tr("未配置远程仓库。", "No remote configured.")
    return tr(f"状态检测失败: {info.error}", f"Status check failed: {info.error}")


def render_menu(info: RepoInfo, active: str | None = None) -> str:
    """菜单行（纯文本 markup，背景由 _menu_block 统一添加）。方括号经反斜杠转义。

    只列出带快捷键的操作项：Enter 为默认执行键不标注，退出直接关闭窗口。
    active: 最近按下的选项键（d/f/r/i/o）；命中时该键转全大写且整项加粗。
    """
    if info.status == RepoStatus.DIVERGED:
        items = [("r", tr('恢复', 'Restore')), ("f", tr('强制推送', 'Force push'))]
    else:
        items = [("d", tr('详情', 'Details')), ("f", tr('文件', 'Files')),
                 ("r", tr('恢复', 'Restore')), ("i", tr('信息', 'Info'))]
    parts = []
    for key, text in items:
        if active == key:
            parts.append(f"[bold]\\[{key.upper()}] {text}[/]")
        else:
            parts.append(f"\\[{key}] {text}")
    return "  ".join(parts)


def _strip_git_suffix(url: str) -> str:
    """去掉远程 URL 的 .git 后缀。"""
    return url[:-4] if url.endswith(".git") else url


def _project_line(info: RepoInfo, project_name: str) -> str:
    """主屏首行：项目名，有远程 URL 时附括号显示（URL 深灰次要，去 .git 后缀）。"""
    url = f" ({_strip_git_suffix(info.remote_url)})" if info.remote_url else ""
    return f"{project_name}[{COLOR_URL}]{url}[/]"


def render_status_line(info: RepoInfo) -> str:
    """状态段：「分支: main (状态)」。标签 #666666，分支名 #CDD6F4，括号内容默认色。"""
    detail = _status_detail(info)
    suffix = f" ({detail})" if detail else ""
    return (f"[{COLOR_LABEL}]{tr('分支: ', 'branch: ')}[/]"
            f"[{COLOR_BRANCH_NAME}]{info.branch}[/]{suffix}")


def _top_line(info: RepoInfo, project_name: str) -> str:
    """顶栏信息区三行（行首统一缩进 2 空格）：项目: 名 / 分支: main (+N) / 主页: URL。"""
    lines = [f"  [{COLOR_LABEL}]{tr('项目: ', 'Project: ')}[/]{project_name}",
             f"  {render_status_line(info)}"]
    if info.remote_url:
        lines.append(f"  [{COLOR_LABEL}]{tr('主页: ', 'Home: ')}[/]"
                     f"[{COLOR_URL}]{_strip_git_suffix(info.remote_url)}[/]")
    return "\n".join(lines)


def _visible_width(markup: str) -> int:
    """Rich markup 文本剥离标签后的显示宽度（反斜杠转义方括号还原为 [）。"""
    text = markup.replace("\\[", "\x00")
    text = _MARKUP_RE.sub("", text).replace("\x00", "[")
    return get_display_width(text)


def render_menu_line(info: RepoInfo, active: str | None, width: int) -> str:
    """菜单行完整渲染（#292929 背景 + 行首缩进 2 空格 + 延伸至右缘），供定点重绘。"""
    menu = render_menu(info, active)
    pad = max(0, width - 2 - _visible_width(menu))
    return f"[on {COLOR_MENU_BG}]  {menu}{' ' * pad}[/]"


def _menu_block(info: RepoInfo, width: int, active: str | None = None) -> str:
    """菜单块：菜单行上下各一行 #292929 背景空行，背景延伸至终端右缘，行首缩进 2 空格。"""
    blank = f"[on {COLOR_MENU_BG}]{' ' * width}[/]"
    return "\n".join([blank, render_menu_line(info, active, width), blank])


def render_main(info: RepoInfo, project_name: str) -> str:
    """主屏三行：项目名(URL) / 分支·状态详情 / 菜单。"""
    line3 = render_menu(info)
    return "\n".join([_project_line(info, project_name),
                      render_status_line(info), line3])


def render_header(info: RepoInfo, project_name: str, width: int = 80,
                  active: str | None = None) -> str:
    """顶部常驻栏：项目 / 分支·状态 / 主页 / 空行 / 菜单块 / 空行。

    固定在屏幕顶部；内容区（变更列表、日志、各视图）在其下方刷新。
    """
    return "\n".join([_top_line(info, project_name), "",
                      _menu_block(info, width, active), ""])
