"""拉取标签页：本地历史提交列表，首个 Enter 对齐远程，其余恢复历史版本。

切入即显示（activate 首次扫描 remote_head + 最近 20 条提交，懒加载缓存）。
↑/↓ 循环移动，Enter 执行选中项（无二次确认），返回 ["pull", "push"] 由主循环
失效重扫。光标样式：选中行 › + #636363 底色框选（不加粗），未选中行 3 空格占位。
列表内容均为安全文本（hash/时间），不含方括号或反斜杠，无需 markup 转义。
"""
from __future__ import annotations

from typing import Callable

from core.config import (COLOR_CYAN, COLOR_MENU_ACTIVE_BG, COLOR_PLACEHOLDER,
                         KEY_DOWN, KEY_ENTER, KEY_UP)
from core.protocols import GitProvider
from core.restore_service import RestoreService

from .renderer import markup_to_ansi
from .view_base import ViewBase


class PullView(ViewBase):
    """拉取标签页：首个（最新提交）Enter 对齐远程，其余恢复历史提交。"""

    id = "pull"

    def __init__(self, restore: RestoreService, git: GitProvider,
                 max_rows: Callable[[], int]):
        super().__init__()
        self.restore = restore
        self.git = git
        self._max_rows = max_rows  # 列表可见窗口高度
        self._items: list[tuple[str, str]] = []
        self._remote_head: str | None = None  # origin/<branch> 指向的提交 hash
        self._index = 0

    def _load(self) -> None:
        """[(hash, time)] 最新在前；顺带记录远程跟踪引用；光标按长度钳位保留。"""
        self._remote_head = self.git.remote_head(self.git.current_branch())
        self._items = [(c["hash"], c["time"])
                       for c in self.git.get_recent_commits(20)]
        self._index = max(0, min(self._index, len(self._items) - 1))

    def render(self) -> str:
        if not self._items:
            return markup_to_ansi(  # 无提交历史占位
                f"[{COLOR_PLACEHOLDER}]none[/]")
        # 窗口滚动：只渲染选中项附近若干条，防止列表超屏触发终端滚动
        visible = max(3, min(self._max_rows() - 1, len(self._items)))
        half = visible // 2
        start = max(0, min(self._index - half, len(self._items) - visible))
        window = self._items[start:start + visible]
        lines: list[str] = []
        for i, (h, t) in enumerate(window):
            label = self._render_label(h, t)
            if start + i == self._index:
                # › 箭头 + #636363 底色框选（不加粗，与历史定案一致）
                lines.append(markup_to_ansi(
                    f"[on {COLOR_MENU_ACTIVE_BG}] › {label} [/]"))
            else:
                # 统一经 markup_to_ansi：青色命中行未选中时也能正确着色
                lines.append(markup_to_ansi(f"   {label} "))
        return "\n".join(lines)

    def handle_key(self, key: bytes) -> list[str]:
        if not self._items:
            return []
        if key == KEY_UP:
            self._index = (self._index - 1) % len(self._items)
        elif key == KEY_DOWN:
            self._index = (self._index + 1) % len(self._items)
        elif key == KEY_ENTER:
            # Enter 直接执行选中项（无二次确认）
            commit_hash, _ = self._items[self._index]
            if self._index == 0:
                # 首个（最新提交）= 最新的对齐：fetch + reset origin/branch
                self.restore.restore_remote()
            else:
                self.restore.restore(commit_hash)
            return ["pull", "push"]  # 历史与工作区都已变
        return []

    def _render_label(self, hash_: str, time_: str) -> str:
        """单行文本：hash 段命中远程一致版本时包 #ABDFA7 markup，否则原样。"""
        text = f"{hash_[:8]}  {time_}"
        if self._remote_head and hash_ == self._remote_head:
            return f"[{COLOR_CYAN}]{hash_[:8]}[/]  {time_}"
        return text
