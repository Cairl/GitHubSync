"""分支标签页：首行固定「合并到 main」操作项，下方本地分支列表 Enter 切换。

切入即显示（activate 首次扫描本地分支，懒加载缓存）。↑/↓ 循环移动，
Enter 执行选中项（无二次确认）：首行 = 合并当前分支到 main 并推送，
分支行 = 切换。脏区（有未提交变更）Enter 行首标 [!] 拒绝；执行失败标 [✕]。
切换/合并成功返回全部视图 id（分支变了，所有缓存作废）由主循环统一失效。
光标样式与拉取页一致：选中行 › + #636363 底色框选（不加粗），未选中行 3 空格。
当前分支名包 #ABDFA7（COLOR_CYAN，与 [✓] 同色）。
git refname 禁止 [ 与 \\，分支名无 markup 注入风险，无需转义。
"""
from __future__ import annotations

from typing import Callable

from core.branch_service import BranchService
from core.config import (COLOR_CYAN, COLOR_ERROR, COLOR_MENU_ACTIVE_BG,
                         KEY_DOWN, KEY_ENTER, KEY_UP)
from core.i18n import tr
from core.protocols import GitProvider

from .renderer import markup_to_ansi
from .view_base import ViewBase

_MERGE_KEY = "@merge"  # 合并操作项的行标识（@ 前缀不会与分支名冲突）
_ALL_VIEWS = ["push", "pull", "files", "branch"]  # 切换/合并成功后全量失效


class BranchView(ViewBase):
    """分支标签页：首行「合并到 main」（仅当前 ≠ main），下方本地分支列表。"""

    id = "branch"

    def __init__(self, branch: BranchService, git: GitProvider,
                 max_rows: Callable[[], int]):
        super().__init__()
        self.branch = branch
        self.git = git
        self._max_rows = max_rows  # 列表可见窗口高度
        self._branches: list[str] = []
        self._current: str = ""
        self._index = 0
        self._blocked: set[str] = set()  # 脏区拦截的行（[!]）
        self._failed: set[str] = set()   # 执行失败的行（[✕]）

    def _load(self) -> None:
        """缓存当前分支与本地分支列表；光标按行数钳位保留。"""
        self._current = self.git.current_branch()
        self._branches = self.git.list_branches()
        self._index = max(0, min(self._index, len(self._rows()) - 1))

    def _rows(self) -> list[tuple[str, str]]:
        """行模型 [(行标识, 文本)]：当前非 main 且有分支时首行为合并项。"""
        rows: list[tuple[str, str]] = []
        if self._current != "main" and self._branches:
            rows.append((_MERGE_KEY, tr("合并到 main", "Merge into main")))
        rows += [(b, b) for b in self._branches]
        return rows

    def render(self) -> str:
        rows = self._rows()
        if not rows:
            return markup_to_ansi(tr("没有本地分支。", "No local branches."))
        # 窗口滚动（与拉取页同款）：防止列表超屏触发终端滚动
        visible = max(3, min(self._max_rows() - 1, len(rows)))
        half = visible // 2
        start = max(0, min(self._index - half, len(rows) - visible))
        lines: list[str] = []
        for i, (key, text) in enumerate(rows[start:start + visible]):
            label = self._render_label(key, text)
            if start + i == self._index:
                lines.append(markup_to_ansi(
                    f"[on {COLOR_MENU_ACTIVE_BG}] › {label} [/]"))
            else:
                lines.append(markup_to_ansi(f"   {label} "))
        return "\n".join(lines)

    def handle_key(self, key: bytes) -> list[str]:
        rows = self._rows()
        if not rows:
            return []
        if key == KEY_UP:
            self._index = (self._index - 1) % len(rows)
        elif key == KEY_DOWN:
            self._index = (self._index + 1) % len(rows)
        elif key == KEY_ENTER:
            row_key, _ = rows[self._index]
            if row_key == self._current:
                return []  # 当前分支行无操作（合并项标识不会等于分支名）
            if self.branch.is_dirty():
                self._blocked.add(row_key)
                return []
            if row_key == _MERGE_KEY:
                ok, _ = self.branch.merge_to_main()
            else:
                ok, _ = self.branch.switch(row_key)
            if ok:
                return list(_ALL_VIEWS)  # 分支已变，全部缓存作废
            self._failed.add(row_key)
        return []

    def _render_label(self, key: str, text: str) -> str:
        """行文本 markup：[!] 脏区拦截 / [✕] 失败（错误红）；当前分支名浅绿。"""
        if key in self._blocked:
            return f"[{COLOR_ERROR}]\\[!][/] {text}"
        if key in self._failed:
            return f"[{COLOR_ERROR}]\\[✕][/] {text}"
        if key == self._current:
            return f"[{COLOR_CYAN}]{text}[/]"
        return text
