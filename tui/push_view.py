"""推送标签页：推送会话阶段行累积回显（每阶段一行，完成留痕）。

开屏即一屏框架，Enter 推送前后不跳界面：
- 无会话：单行显示本次变更数（`  3 change(s)`，无变更时为空行），
  按 Enter 前即可确认本次是否有变更；
- 推送中：每个阶段一行（初始化/配置/扫描/提交/推送/发布），按出现
  顺序累积——进行中行 `> 当前动作`，完成行 `✓ 结果` 保留不覆盖，
  失败行 `✕ 原因`；push 阶段实时进度（百分比 + 对象数）拼在当前
  动作行尾并覆盖旧进度，如 `> 推送到 GitHub 42% (12/29) · 1.20 MiB`；
- 结束后：所有阶段行保留可回溯；整体失败在末尾追加 `✕ 失败原因`。

事件驱动：core 服务发布 ActionLog（带 stage 标识），表现层按 stage
定位行——新阶段追加一行，已有阶段更新该行；PROGRESS 拼到该行文本
（进行中动作行后拼最新进度、完成行后拼附注，重复消息自动去重）。
CLI 等纯文本消费者忽略 stage 字段，零影响。

每次 Enter 开启新会话（清空上一会话阶段行）；切出保留当前会话可切回查看。
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
    """推送标签页：推送会话阶段行累积回显。"""

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
        self._max_rows = max_rows    # 内容区可用行数；超出后阶段行截断保留最新
        self._session: str | None = None  # None（无会话）/ running / done / failed
        self._stage: dict[str, tuple[str, str]] = {}  # stage → (level, message)
        self._stage_order: list[str] = []             # stage 出现顺序（渲染行序）
        self._stage_title: dict[str, str] = {}        # stage → ACTION 标题（进度拼接基准）
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
        """当前视图的 markup 行列表：无会话为变更数行，会话为阶段行累积。

        无会话：单行变更数（`  3 change(s)`，无变更时为空列表）；
        推送中/结束：每个阶段一行按出现顺序累积，完成留痕、失败红色，
        超出内容区可用行数时截断保留末尾（最新阶段）。
        """
        with self._lock:
            session = self._session
            order = list(self._stage_order)
            stage = dict(self._stage)
        if session is None:
            # 无会话：变更数行（无变更则空）
            info = self._get_info()
            if info is not None and info.change_count:
                return ["  " + f"[{COLOR_GRAY}]"
                        + tr(f"{info.change_count} 处变化",
                             f"{info.change_count} change(s)") + "[/]"]
            return []
        lines = [self._log_markup(level, message)
                 for key in order for level, message in [stage[key]]]
        limit = self._max_rows() if self._max_rows is not None else None
        if limit is not None and len(lines) > limit:
            lines = lines[-limit:]
        return lines

    def _log_markup(self, level: str, message: str) -> str:
        """阶段行 markup：`  前缀 消息`，按级别着色。"""
        prefix, color = _LOG_STYLE.get(level, (">", COLOR_GRAY))
        return f"  {prefix} [{color}]{message}[/]"

    def _set_stage(self, stage: str, level: str, message: str) -> None:
        """按 stage 更新阶段行（已持锁调用）。

        - 新阶段：追加一行（level 决定前缀与颜色），ACTION 同时记录标题；
        - 已有阶段：ACTION/DONE/FAIL/NOTE 整行替换（前缀随新级别），
          ACTION 替换时更新标题；
          PROGRESS 拼到该行文本后并保留原级别前缀——进行中动作行
          （原 ACTION）为「标题 + 最新进度」覆盖式更新不累积旧进度，
          完成行（DONE/NOTE）为追加附注且消息已含于文本时跳过（去重）。
        """
        key = stage or f"__{level}:{message}"
        if level == "PROGRESS" and key in self._stage:
            prev_level, text = self._stage[key]
            if prev_level == "ACTION" and self._stage_title.get(key):
                # 进行中动作行：标题 + 最新进度（覆盖旧进度，不累积）
                self._stage[key] = ("ACTION",
                                    f"{self._stage_title[key]} {message}")
            elif message not in text:
                # 完成行附注（如扫描完成后的变更数）：追加 + 去重
                self._stage[key] = (prev_level,
                                    f"{text} {message}" if text else message)
            return
        self._stage[key] = (level, message)
        if level == "ACTION":
            self._stage_title[key] = message
        if key not in self._stage_order:
            self._stage_order.append(key)

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
        """开启推送会话：fetch 刷新远程状态 → 清空阶段行 → 执行同步。

        会话视图先行渲染（空阶段行），随后事件驱动逐阶段追加刷新。
        """
        self._refresh_status(True)  # fetch 刷新远程状态（分叉/落后检测可靠）
        with self._lock:
            self._session = "running"
            self._stage.clear()
            self._stage_order.clear()
            self._stage_title.clear()
        self._refresh()  # 行数变化（变更数 → 空会话）：整区重绘
        try:
            self.sync.run()  # 动作事件经订阅覆盖刷新视图
        except SyncError:
            pass  # SyncFailed 事件已标记失败（_on_sync_failed）

    def _refresh(self) -> None:
        """增量刷新：行数不变则定点更新差异行（不清屏），否则整区重绘。

        阶段行累积只在阶段切换时行数增长（整区重绘）；PROGRESS 拼进度
        行数不变，走定点更新避免推送过程中反复 \x1b[J 清屏重绘的闪烁。
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
        """按 stage 更新对应阶段行：新阶段追加、已有阶段更新、PROGRESS 拼进度。"""
        if self._session is None:
            return
        with self._lock:
            self._set_stage(event.stage, event.level, event.message)
        self._refresh()

    def _on_sync_failed(self, event: SyncFailed) -> None:
        """会话失败：末尾追加失败原因行（阶段行保留可回溯）。"""
        with self._lock:
            self._session = "failed"
            key = "__fail"
            self._stage[key] = ("FAIL", event.message)
            if key not in self._stage_order:
                self._stage_order.append(key)
        self._refresh()

    def _on_sync_completed(self, event: SyncCompleted) -> None:
        """会话完成：仅更新状态（完成消息由 push 阶段 DONE 事件表达）。"""
        with self._lock:
            self._session = "done"
        self._refresh()
