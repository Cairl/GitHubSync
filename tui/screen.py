"""交互模式渲染：纯函数，RepoInfo → Rich markup 文本。零 I/O、零子进程。

顶栏布局：项目/分支·状态/主页 / 空行 / 菜单块（#292929 背景三行）/ 空行。
"""
from __future__ import annotations

import re

from core.config import (COLOR_BRANCH_NAME, COLOR_LABEL, COLOR_MENU_ACTIVE_BG,
                         COLOR_MENU_BG, COLOR_URL)
from core.i18n import tr
from core.status import RepoInfo, RepoStatus
from core.utils import get_display_width

_MARKUP_RE = re.compile(r"\[/?[^\]]*\]")

# 导航栏固定三项：顺序即 ← → 光标的移动顺序
MENU_ITEMS: list[tuple[str, str]] = [
    ("push", tr("推送", "Push")),
    ("pull", tr("拉取", "Pull")),
    ("files", tr("文件", "Files")),
]


def menu_for_action(action: str) -> str:
    """推荐动作 → 初始光标落点菜单项（diff/refresh 无对应菜单项，落推送）。"""
    return {"push": "push", "restore_remote": "pull"}.get(action, "push")


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
        return tr("尚未提交完成", "not fully synced")
    if info.status == RepoStatus.BEHIND:
        return tr("有新的提交", "new commits to pull")
    if info.status == RepoStatus.DIVERGED:
        return tr("有新的提交和拉取", "new commits to push and pull")
    if info.status == RepoStatus.CLEAN:
        return tr("已同步，工作区干净。", "Synced, working tree clean.")
    if info.status == RepoStatus.NO_REPO:
        return tr("尚未初始化 git 仓库。", "Not a git repository yet.")
    if info.status == RepoStatus.NO_REMOTE:
        return tr("未配置远程仓库。", "No remote configured.")
    return tr(f"状态检测失败: {info.error}", f"Status check failed: {info.error}")


def _has_sync(info: RepoInfo, item_id: str) -> bool:
    """菜单项是否有待处理同步：推送 = 有待推变更，拉取 = 有新提交（分叉两者都有）。"""
    if item_id == "push":
        return info.status in (RepoStatus.CHANGED, RepoStatus.AHEAD,
                               RepoStatus.NO_REPO, RepoStatus.NO_REMOTE,
                               RepoStatus.DIVERGED)
    if item_id == "pull":
        return info.status in (RepoStatus.BEHIND, RepoStatus.DIVERGED)
    return False


def render_menu(info: RepoInfo, active: str | None = None) -> str:
    """菜单行（纯文本 markup，背景由 _menu_block 统一添加）。

    导航栏固定三项：推送 / 拉取 / 文件（任何状态下一致），用 ← → 移动光标、
    Enter 执行选中项。active: 当前光标选中的菜单项 id（push/pull/files）。
    每项固定格式：前缀 1 格 + `[文本]` + 后缀 1 格，选中/未选中文本位置一致，
    光标移动不跳动；推送/拉取有待处理同步时文本两侧加 `*`（如 `[*推送*]`，
    同一状态下所有项定宽渲染，布局稳定）。选中项底色覆盖 ` [文本] `（左右
    各冗余 1 格，不顶格）；未选中项无底色。方括号经 `\[` 转义，星号为字面
    字符（Rich 15 不解析 `*` 斜体简写，无需转义）。
    """
    parts = []
    for item_id, text in MENU_ITEMS:
        label = f"*{text}*" if _has_sync(info, item_id) else text
        # Rich markup 转义：\[ 显示 [；* 为字面字符（Rich 15 不解析 * 斜体简写）
        bracketed = "\\[" + label + "]"
        if active == item_id:
            parts.append(f"[bold on {COLOR_MENU_ACTIVE_BG}] {bracketed} [/]")
        else:
            parts.append(f" {bracketed} ")
    return "".join(parts)


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
    """Rich markup 文本剥离标签后的显示宽度（反斜杠转义的 [ * 还原为原字符）。"""
    text = markup.replace("\\[", "\x00").replace("\\*", "\x00")
    text = _MARKUP_RE.sub("", text).replace("\x00", " ")
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


def render_main(info: RepoInfo, project_name: str,
                active: str | None = None) -> str:
    """主屏三行：项目名(URL) / 分支·状态详情 / 菜单。"""
    line3 = render_menu(info, active)
    return "\n".join([_project_line(info, project_name),
                      render_status_line(info), line3])


def render_header(info: RepoInfo, project_name: str, width: int = 80,
                  active: str | None = None) -> str:
    """顶部常驻栏：项目 / 分支·状态 / 主页 / 空行 / 菜单块 / 空行。

    固定在屏幕顶部；内容区（变更列表、日志、各视图）在其下方刷新。
    """
    return "\n".join([_top_line(info, project_name), "",
                      _menu_block(info, width, active), ""])
