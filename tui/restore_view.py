"""拉取视图：本地历史提交列表，首个 Enter 对齐远程，其余恢复历史版本。

导航栏「拉取」的入口。列表 = 本地最近提交（最新在前，短 hash + 时间）。
光标默认停在第一个（最新提交），Enter 即对齐远程（fetch + reset --hard
origin/<branch>，丢弃本地差异）——第一个就是"最新的对齐"，无需单独列出
对齐项；其余提交 Enter 为恢复到该历史版本（reset --hard，无二次确认）。
↑↓ 循环移动，Backspace/Esc 返回主屏。
光标样式与文件视图一致：选中行 › + #636363 底色框选，未选中行 3 空格占位；
无操作提示行（与文件视图一致）。

两种渲染模式：
- render_body 提供（InteractiveApp 整屏重绘）：列表渲染进内容区视图块；
- 缺省：独立 DiffRenderer 块刷新（兼容独立使用与测试）。
"""
from __future__ import annotations

from typing import Callable

from core.config import (COLOR_CYAN, COLOR_MENU_ACTIVE_BG, KEY_BACKSPACE,
                         KEY_DOWN, KEY_ENTER, KEY_ESC, KEY_UP)
from core.i18n import tr
from core.protocols import GitProvider
from core.restore_service import RestoreService
from core.utils import get_key

from .renderer import DiffRenderer, markup_to_ansi


class RestoreView:
    """拉取视图：首个（最新提交）Enter 对齐远程，其余恢复历史提交。

    列表内容均为安全文本（hash / 时间），不含方括号或反斜杠，无需 markup 转义。
    """

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
        self._remote_head: str | None = None  # origin/<branch> 指向的提交 hash

    def _items(self) -> list[tuple[str, str]]:
        """[(hash, time)] 列表，最新在前；顺带记录远程跟踪引用指向的提交。"""
        self._remote_head = self.git.remote_head(self.git.current_branch())
        return [(c["hash"], c["time"])
                for c in self.git.get_recent_commits(20)]

    def _render_label(self, hash_: str, time_: str) -> str:
        """单行文本：hash 段命中远程一致版本时包青色 markup，否则原样。"""
        text = f"{hash_[:8]}  {time_}"
        if self._remote_head and hash_ == self._remote_head:
            return f"[{COLOR_CYAN}]{hash_[:8]}[/]  {time_}"
        return text

    def run(self) -> None:
        items = self._items()
        if not items:
            # 无历史提交：无可对齐也无可恢复，提示后直接返回
            msg = tr("没有提交历史。", "No commits.")
            if self._render_body is not None:
                self._render_body(msg)
                self._render_body(None)  # 交还主循环重新生成主屏视图
            else:
                self._out(msg)
            return
        block = DiffRenderer(self._out) if self._render_body is None else None
        index = 0
        while True:
            # 窗口滚动：只渲染选中项附近若干条，防止列表超屏触发终端滚动
            visible = len(items)
            if self._max_rows is not None:
                visible = max(3, min(self._max_rows - 1, len(items)))
            half = visible // 2
            start = max(0, min(index - half, len(items) - visible))
            window = items[start:start + visible]
            lines: list[str] = []
            for i, (h, t) in enumerate(window):
                label = self._render_label(h, t)
                if start + i == index:
                    # 与导航栏/文件视图光标同款：› 箭头 + #636363 底色框选
                    lines.append(markup_to_ansi(
                        f"[bold on {COLOR_MENU_ACTIVE_BG}] › {label} [/]"))
                else:
                    # 统一经 markup_to_ansi：青色命中行在未选中时也能正确着色
                    lines.append(markup_to_ansi(f"   {label} "))
            text = "\n".join(lines)
            if self._render_body is not None:
                self._render_body(text)
            else:
                block.render(text)
            key = self._key()
            if key == KEY_BACKSPACE or key == KEY_ESC:
                if self._render_body is not None:
                    self._render_body(None)  # 交还主循环重新生成主屏视图
                else:
                    block.clear()
                return
            if key == KEY_UP:
                index = (index - 1) % len(items)
            elif key == KEY_DOWN:
                index = (index + 1) % len(items)
            elif key == KEY_ENTER:
                # Enter 直接执行选中项（无二次确认，用户已确认）
                if self._render_body is None:
                    block.clear()
                commit_hash, _ = items[index]
                if index == 0:
                    # 光标默认首个（最新提交）= 最新的对齐：fetch + reset origin/branch
                    self.restore.restore_remote()
                else:
                    self.restore.restore(commit_hash)
                if self._render_body is not None:
                    self._render_body(None)  # 执行完成，交还主循环
                else:
                    block.clear()
                return
