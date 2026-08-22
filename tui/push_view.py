"""推送标签页：推送会话单行动作回显（全程一屏，无阶段行）。

开屏即一屏框架，Enter 推送前后不跳界面：
- 无会话：单行显示本次变更数（`  3 change(s)`，无变更时为空行），
  按 Enter 前即可确认本次是否有变更；
- 推送中：同一行覆盖式显示当前动作（`> 推送到 GitHub`），不累积、
  不滚动；结束即显示最后结果（`✓ 推送完成（N 项更改）` / `✕ 失败原因`）。

事件驱动：core 服务发布 ActionLog（带 stage 标识），表现层按级别着色
覆盖动作行；PROGRESS 实时进度只更新内部状态不渲染，避免刷屏。CLI 等
纯文本消费者忽略 stage 字段，零影响。

每次 Enter 开启新会话（覆盖上一次结果视图）；切出保留当前会话可切回查看。
"""
from __future__ import annotations

import threading
from typing import Callable

from core.config import (COLOR_ERROR, COLOR_GRAY, COLOR_PUSH_PENDING,
                         COLOR_SUCCESS_SOFT, KEY_ENTER)
from core.events import (ActionLog, DomainEventBus, SyncCompleted, SyncFailed)
from core.exceptions import SyncError
from core.i18n import tr
from core.protocols import GitProvider
from core.status import RepoInfo
from core.sync_service import SyncService

from .renderer import markup_to_ansi
from .view_base import ViewBase

# 事件级别 → (前缀, 语义色)
_LOG_STYLE = {
    "ACTION": (">", COLOR_PUSH_PENDING),
    "DONE": ("✓", COLOR_SUCCESS_SOFT),
    "FAIL": ("✕", COLOR_ERROR),
    "NOTE": (">", COLOR_GRAY),
    "PROGRESS": (">", COLOR_PUSH_PENDING),
}


class PushView(ViewBase):
    """推送标签页：推送会话单行动作回显（无阶段行）。"""

    id = "push"

    def __init__(self, sync: SyncService, git: GitProvider, bus: DomainEventBus,
                 get_info: Callable[[], RepoInfo],
                 refresh_status: Callable[[bool], RepoInfo],
                 paint: Callable[[str], None],
                 patch: Callable[[int, str], None] | None = None,
                 max_rows: Callable[[], int] | None = None,
                 executor=None, on_loaded=None):
        super().__init__(executor=executor, on_loaded=on_loaded)
        self.sync = sync
        self.git = git
        self._get_info = get_info
        self._refresh_status = refresh_status
        self._paint = paint
        self._patch = patch          # 定点更新单行（行号 1-based）；None 时退化为整区重绘
        self._max_rows = max_rows    # 内容区可用行数；状态行占 1 行，其余空行
        self._session: str | None = None  # None（无会话）/ running / done / failed
        self._log_line: str = ""      # 当前动作行（markup，覆盖式不累积滚动）
        self._last_lines: list[str] | None = None  # 上次渲染行（markup，增量对比基准）
        self._lock = threading.Lock()
        # 事件订阅：sync.run() 主线程同步发布，回调可直绘
        bus.subscribe(ActionLog, self._on_action_log)
        bus.subscribe(SyncFailed, self._on_sync_failed)
        bus.subscribe(SyncCompleted, self._on_sync_completed)

    # ── 生命周期 ──
    def _load(self) -> None:
        """动作回显事件驱动，无需扫描；空实现（激活即就绪，零 I/O）。"""

    # ── 渲染（纯函数，只读缓存）──
    def _render(self) -> str:
        return markup_to_ansi("\n".join(self._render_lines()))

    def _render_lines(self) -> list[str]:
        """当前视图的 markup 行列表：单行状态 + 空行占位。

        行数恒定 = 1（状态行）+ 空行占位。无会话时状态行显示本次变更数
        （`  3 change(s)`，无变更时为空）；推送过程中同一行覆盖式显示
        当前动作，不累积、不滚动，结束即显示最后结果。
        """
        with self._lock:
            session = self._session
            log_line = self._log_line
        if session is None:
            # 无会话：状态行 = 变更数（无变更则空）
            info = self._get_info()
            if info is not None and info.change_count:
                log_line = ("  " + f"[{COLOR_GRAY}]"
                            + tr(f"{info.change_count} 处变化",
                                 f"{info.change_count} change(s)") + "[/]")
            else:
                log_line = ""
        limit = self._max_rows() if self._max_rows is not None else None
        lines = [log_line]
        if limit is not None:
            lines += [""] * max(0, limit - len(lines))
        return lines

    def _log_markup(self, level: str, message: str) -> str:
        """动作行 markup：`  前缀 消息`，按级别着色。"""
        prefix, color = _LOG_STYLE.get(level, (">", COLOR_GRAY))
        return f"  {prefix} [{color}]{message}[/]"

    def _set_log(self, level: str, message: str) -> None:
        """覆盖式设置当前动作行（已持锁调用）；不累积、不滚动。"""
        self._log_line = self._log_markup(level, message)

    # ── 键处理 ──
    def handle_key(self, key: bytes) -> list[str]:
        if self._loading:
            return []  # loading 期间无数据，Enter 不得触发推送流程
        if key != KEY_ENTER:
            return []
        self._start_push()
        return ["pull"]  # 提交历史已变

    # ── 推送会话 ──
    def _start_push(self) -> None:
        """开启推送会话：fetch 刷新远程状态 → 执行同步。

        会话视图先行渲染（空动作行），随后事件驱动覆盖刷新。
        """
        self._refresh_status(True)  # fetch 刷新远程状态（分叉/落后检测可靠）
        with self._lock:
            self._session = "running"
            self._log_line = ""
        self._refresh()  # 行数变化（变更数 → 空动作行）：整区重绘
        try:
            self.sync.run()  # 动作事件经订阅覆盖刷新视图
        except SyncError:
            pass  # SyncFailed 事件已标记失败（_on_sync_failed）

    def _refresh(self) -> None:
        """增量刷新：行数不变则定点更新差异行（不清屏），否则整区重绘。

        动作行变化通常只改单行文本，定点更新避免推送过程中反复
        \x1b[J 清屏重绘的闪烁；会话开始/结束等行数变化场景整区重绘。
        """
        lines = self._render_lines()
        with self._lock:
            prev = self._last_lines
            self._last_lines = list(lines)
        if (self._patch is not None and prev is not None
                and len(lines) == len(prev)):
            dirty = [i for i in range(len(lines)) if lines[i] != prev[i]]
            if dirty:
                for i in dirty:
                    self._patch(i + 1, markup_to_ansi(lines[i]))
            return  # 无变化行则零输出
        self._paint(markup_to_ansi("\n".join(lines)))

    # ── 事件驱动（主线程同步回调）──
    def _on_action_log(self, event: ActionLog) -> None:
        """里程碑消息（非 PROGRESS）覆盖动作行；PROGRESS 忽略不渲染。"""
        if self._session is None:
            return
        if event.level != "PROGRESS":
            with self._lock:
                self._set_log(event.level, event.message)
            self._refresh()

    def _on_sync_failed(self, event: SyncFailed) -> None:
        """会话失败：失败原因覆盖动作行。"""
        with self._lock:
            self._session = "failed"
            self._set_log("FAIL", event.message)
        self._refresh()

    def _on_sync_completed(self, event: SyncCompleted) -> None:
        """会话完成：仅更新状态（完成消息由 push 阶段 DONE 事件表达）。"""
        with self._lock:
            self._session = "done"
        self._refresh()
