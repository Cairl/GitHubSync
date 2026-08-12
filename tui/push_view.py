"""推送标签页：待推清单 + 推送状态机（[·] 上传中 / [✓] 完成 / [✕] 失败）。

切入显示待推文件清单（activate 首次扫描 porcelain，懒加载缓存）。
Enter 执行推送：先渲染全 [·]（零 fetch，一瞬反馈）→ fetch 刷新顶栏 →
sync.run() → [✓]/[✕] 结果锁定常驻。锁定期间 activate 不重扫；
切出标签（deactivate）或空推送（Enter 且无可推内容）时清除锁定。
"""
from __future__ import annotations

from typing import Callable

from core.config import (COLOR_ERROR, COLOR_PLACEHOLDER, COLOR_PUSH_PENDING,
                         COLOR_SUCCESS_SOFT, COLOR_WARN, KEY_ENTER)
from core.exceptions import SyncError
from core.i18n import tr
from core.protocols import GitProvider
from core.status import (RepoInfo, append_local_changelog, changelog_pending,
                         format_diff)
from core.sync_service import SyncService

from .renderer import markup_to_ansi
from .view_base import ViewBase

# 单字母状态 → 符号标记（TUI 显示用；core.status.format_diff 保持字母契约不变）
_CHANGE_CN = {"A": "[+]", "M": "[~]", "D": "[-]", "R": "[→]"}
# 符号语义色：新增=柔和浅绿 / 修改=警告黄 / 删除=错误红 / 重命名=警告黄
_CHANGE_COLOR = {"A": COLOR_SUCCESS_SOFT, "M": COLOR_WARN, "D": COLOR_ERROR,
                 "R": COLOR_WARN}
# 推送状态符号 → 语义色：上传中=暗灰 / 完成=柔和浅绿 / 失败=错误红
_PUSH_COLOR = {"·": COLOR_PUSH_PENDING, "✓": COLOR_SUCCESS_SOFT, "✕": COLOR_ERROR}


def _is_changelog_row(row: str) -> bool:
    """format_diff 行是否为根目录 changelog.md（"L  changelog.md"）。"""
    return len(row) >= 3 and row[1] == " " and row[3:] == "changelog.md"


def _changelog_bottom(rows: list[str]) -> list[str]:
    """changelog.md 行置底并前置一空行（仅当列表还有其他行）。

    rows 为 format_diff 原始行（"L  path"）；空行以 "" 表示，由渲染与
    推送状态两条路径各自处理。无 changelog.md 或仅剩它时原样返回。
    """
    if not rows:
        return rows
    changelog = [r for r in rows if _is_changelog_row(r)]
    rest = [r for r in rows if not _is_changelog_row(r)]
    if not changelog or not rest:
        return rows
    return rest + [""] + changelog


def _ahead_placeholder(ahead: int) -> str:
    """AHEAD 且工作区干净时的占位行：表达待推送的本地提交数。"""
    return tr(f"推送 {ahead} 个本地提交", f"Pushing {ahead} local commit(s)")


class PushView(ViewBase):
    """推送标签页。结果锁定期间 activate/invalidate 均不重扫（render 持续输出结果）。"""

    id = "push"

    def __init__(self, sync: SyncService, git: GitProvider,
                 get_info: Callable[[], RepoInfo],
                 refresh_status: Callable[[bool], RepoInfo],
                 paint: Callable[[str], None],
                 executor=None, on_loaded=None):
        super().__init__(executor=executor, on_loaded=on_loaded)
        self.sync = sync
        self.git = git
        self._get_info = get_info
        self._refresh_status = refresh_status
        self._paint = paint
        self._lines: list[str] = []              # 待推清单（_load 缓存）
        self._push_state: dict[str, str] | None = None  # {路径: 状态符号}
        self._push_paths: list[str] = []
        self._push_result = False                # 结果锁定：常驻至切出/空推送

    # ── 生命周期 ──
    def activate(self) -> None:
        if self._push_result:
            return  # 结果锁定期间不重扫（[✓]/[✕] 常驻）
        super().activate()

    def deactivate(self) -> None:
        """切出推送页：清除结果锁定与推送上下文，下次切入重扫。"""
        self._push_result = False
        self._push_state = None
        self._push_paths = []
        self.invalidate()

    def _load(self) -> None:
        self._lines = self._diff_lines()

    # ── 渲染（纯函数，只读缓存）──
    def _render(self) -> str:
        if self._push_state is not None:
            return "\n".join(self._render_push_lines())
        lines = "\n".join(self._lines)
        if not lines:
            return markup_to_ansi(  # 无待推内容占位
                f"[{COLOR_PLACEHOLDER}]none[/]")
        return lines

    # ── 键处理 ──
    def handle_key(self, key: bytes) -> list[str]:
        if self._loading:
            return []  # loading 期间无数据，Enter 不得触发推送流程
        if key != KEY_ENTER:
            return []
        had_result = self._push_result
        paths = self._begin_push()
        if not paths and had_result:
            # 结果锁定期间空推送 = 清除旧结果，不再执行 sync
            self.deactivate()
            return ["push"]
        # fetch 刷新远程状态（分叉/落后检测可靠），频率低可接受
        self._refresh_status(True)
        self._push(paths)
        return ["pull"]  # 提交历史已变

    # ── 内部 ──
    def _changelog_rows(self) -> list[str]:
        """porcelain format_diff 行 + 本地 changelog 注入 + 置底。

        changelog.md 不入库（gitignore 隔离），porcelain 无行；本地存在
        非空 changelog.md 时由 append_local_changelog 注入显示（Release
        待发布提示），并经 _changelog_bottom 置底 + 前置空行。
        """
        return _changelog_bottom(append_local_changelog(
            format_diff(self.git.get_porcelain()), self.sync.repo_path))

    def _ahead_files(self) -> list[tuple[str, str]]:
        """本地领先提交涉及的文件 [(状态字母, 路径)]；查询失败返回空。"""
        branch = self.git.current_branch()
        out = self.git.diff_name_status(f"origin/{branch}", "HEAD")
        files = []
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                # 普通行 "M\tpath"；rename/copy 行 "R100\told\tnew"（三字段，取新路径）
                files.append((parts[0][:1], parts[-1]))
        return files

    def _diff_lines(self) -> list[str]:
        """文件级变化列表，符号标记（[+]/[~]/[-]）按语义着色，文件名纯文本。

        符号单独经 markup 着色，文件名保持纯文本（防止仓库文件名中的方括号
        被 markup 误解析）。changelog.md 置底并前置空行。
        """
        lines = []
        for line in self._changelog_rows():
            if len(line) >= 3 and line[1] == " ":
                label = _CHANGE_CN.get(line[0], line[0])
                color = _CHANGE_COLOR.get(line[0])
                if color:
                    label = markup_to_ansi(f"[{color}]{label}[/]")
                lines.append(f"{label} {line[3:]}")
            else:
                lines.append(line)
        if not lines and self._get_info().ahead > 0:
            # AHEAD 且工作区干净：显示本地领先提交涉及的文件，避免空白与 *推送* 标记矛盾
            ahead_lines = []
            for status, path in self._ahead_files():
                label = _CHANGE_CN.get(status, status)
                color = _CHANGE_COLOR.get(status)
                if color:
                    label = markup_to_ansi(f"[{color}]{label}[/]")
                ahead_lines.append(f"{label} {path}")
            lines = ahead_lines or [_ahead_placeholder(self._get_info().ahead)]
            # 本地 changelog 待发布：AHEAD 干净场景同样显示（不入库仅展示）
            if changelog_pending(self.sync.repo_path) and not any(
                    "changelog.md" in line for line in lines):
                lines = _changelog_bottom(lines + ["A  changelog.md"])
        return lines

    def _render_push_lines(self) -> list[str]:
        """推送状态行：[·]/[✓]/[✕] 按语义着色；方括号反斜杠转义防 markup 误解析。"""
        lines = []
        for path in self._push_paths:
            if not path:
                lines.append("")
                continue
            sym = (self._push_state or {}).get(path, "·")
            label = markup_to_ansi(f"[{_PUSH_COLOR[sym]}]\\[{sym}][/]")
            lines.append(f"{label} {path}")
        return lines

    def _begin_push(self) -> list[str]:
        """渲染 [·] 视图（零 fetch，Enter 一瞬反馈）；返回待推路径（空=无可推）。

        changelog.md 置底，保留空行标记（""）以维持与清单一致的分隔；
        本地待发布的 changelog.md（porcelain 干净）也纳入待推路径。
        """
        paths = []
        for line in self._changelog_rows():
            if not line:
                paths.append("")
            elif len(line) >= 3 and line[1] == " ":
                paths.append(line[3:])
        info = self._get_info()
        if not paths and info.ahead > 0:
            # AHEAD 且工作区干净：以领先提交涉及的文件为待推清单，取不到才用占位行
            paths = [path for _status, path in self._ahead_files()]
            if not paths:
                paths = [_ahead_placeholder(info.ahead)]
        # 工作区干净 + 本地 changelog 待发布：纳入待推路径，Enter 发布 Release
        if changelog_pending(self.sync.repo_path) and "changelog.md" not in paths:
            paths.append("changelog.md")
        if paths:
            self._push_paths = paths
            self._push_state = {p: "·" for p in paths}
            self._paint("\n".join(self._render_push_lines()))
        return paths

    def _push(self, paths: list[str]) -> None:
        """执行同步；有路径时渲染 [✓]/[✕] 并锁定结果（无路径为空同步，不设锁定）。"""
        try:
            self.sync.run()
            state = "✓"
        except SyncError:
            state = "✕"
        if paths:
            self._push_state = {p: state for p in paths}
            self._paint("\n".join(self._render_push_lines()))
            self._push_result = True
