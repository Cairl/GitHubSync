"""恢复视图：最近 commit 列表，回车选择 + y 确认后 reset --hard。

两种渲染模式：
- render_body 提供（InteractiveApp 整屏重绘）：列表渲染进内容区视图块；
- 缺省：独立 DiffRenderer 块刷新（兼容独立使用与测试）。
"""
from __future__ import annotations

from typing import Callable

from core.config import KEY_BACKSPACE, KEY_DOWN, KEY_ENTER, KEY_ESC, KEY_UP
from core.i18n import tr
from core.protocols import GitProvider
from core.restore_service import RestoreService
from core.utils import get_key

from .renderer import DiffRenderer


class RestoreView:
    """主循环内按 [r] 进入的恢复视图；Backspace/Esc 返回主屏。块级差异刷新。"""

    def __init__(self, restore: RestoreService, git: GitProvider,
                 key_source: Callable[[], bytes] = get_key,
                 out: Callable[[str], None] = print,
                 render_body: Callable[[str | None], None] | None = None,
                 max_rows: int | None = None):
        self.restore = restore
        self.git = git
        self._key = key_source
        self._out = out
        self._render_body = render_body
        self._max_rows = max_rows  # 列表可见窗口高度（None = 全部）

    def run(self) -> None:
        commits = self.git.get_recent_commits(20)
        if not commits:
            if self._render_body is not None:
                self._render_body(tr("没有提交历史。", "No commits."))
                self._render_body(None)  # 交还主循环重新生成主屏视图
            else:
                self._out(tr("\n没有提交历史。\n", "\nNo commits.\n"))
            return
        block = DiffRenderer(self._out) if self._render_body is None else None
        index = 0
        while True:
            # 窗口滚动：只渲染选中项附近若干条，防止列表超屏触发终端滚动
            visible = len(commits)
            if self._max_rows is not None:
                visible = max(3, self._max_rows - 2)  # 预留空行 + 标题行
                if visible > len(commits):
                    visible = len(commits)
            half = visible // 2
            start = max(0, min(index - half, len(commits) - visible))
            window = commits[start:start + visible]
            lines = ["", tr("恢复  (↑↓ 移动, Enter 选择, Backspace 返回)",
                            "Restore  (↑↓ move, Enter select, Backspace back)")]
            for i, c in enumerate(window):
                cursor = ">" if start + i == index else " "
                lines.append(f"{cursor} {c['hash'][:8]}  {c['time']}")
            text = "\n".join(lines)
            if self._render_body is not None:
                self._render_body(text)
            else:
                block.render(text)
            key = self._key()
            lower = key.lower() if isinstance(key, bytes) else key
            if key == KEY_BACKSPACE or key == KEY_ESC:
                if self._render_body is not None:
                    self._render_body(None)  # 交还主循环重新生成主屏视图
                else:
                    block.clear()
                return
            if key == KEY_UP:
                index = (index - 1) % len(commits)
            elif key == KEY_DOWN:
                index = (index + 1) % len(commits)
            elif key == KEY_ENTER:
                if self._render_body is None:
                    # 先清块：确认提示与恢复日志在下方自然滚动
                    block.clear()
                target = commits[index]["hash"]
                prompt = tr(f"硬重置到 {target[:8]}? [y/N]",
                            f"Reset --hard to {target[:8]}? [y/N]")
                if self._render_body is not None:
                    self._render_body(prompt)
                else:
                    self._out(prompt)
                confirm = self._key()
                if isinstance(confirm, bytes) and confirm.lower() == b"y":
                    self.restore.restore(target)
                if self._render_body is not None:
                    self._render_body(None)  # 恢复完成，交还主循环
                else:
                    block.clear()
                return
