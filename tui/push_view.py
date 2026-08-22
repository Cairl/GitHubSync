"""推送标签页：推送会话一页流视图（竖排阶段行 + 实时日志流，全程一屏）。

开屏即一页流框架，Enter 推送前后不跳界面：
- 阶段行：竖排展示全部阶段，每阶段一行 `  ✓ Scan`（状态符号 + 英文短名），
  对齐清楚；无会话时按当前状态预判待执行阶段（`· Scan` / `· Commit`），
  Scan 行显示本次变更数（`· Scan 3 change(s)`），按 Enter 前即可确认；
- 日志流：下方固定行数窗口，ActionLog 里程碑消息（ACTION/DONE/NOTE/FAIL）
  逐行追加滚动，按级别着色；会话整体结果（推送完成 / 失败原因）由日志流表达。

阶段标识由 ActionLog.stage 携带（结构化事件驱动）：core 服务在发布时
标注阶段，表现层按阶段状态机更新，而非解析日志文本。CLI 等纯文本
消费者忽略该字段，零影响。

推送过程中阶段行只显示符号变化（✓/…/✕），不显示进度细节——变更数只在
开屏可见，实时进度（PROGRESS）不进日志流、不占阶段行，避免刷屏。

每次 Enter 开启新会话（覆盖上一次结果视图）；切出保留当前会话可切回查看。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable

from core.config import (COLOR_ERROR, COLOR_GRAY, COLOR_PLACEHOLDER,
                         COLOR_PUSH_PENDING, COLOR_SUCCESS_SOFT, KEY_ENTER)
from core.events import (ActionLog, DomainEventBus, SyncCompleted, SyncFailed)
from core.exceptions import SyncError
from core.i18n import tr
from core.protocols import GitProvider
from core.status import RepoInfo, RepoStatus
from core.sync_service import SyncService

from .renderer import markup_to_ansi
from .view_base import ViewBase

# 阶段英文短名（摘要块），顺序即 sync.run 执行顺序
_STAGE_EN = {
    "init": "Init",
    "config": "Config",
    "scan": "Scan",
    "commit": "Commit",
    "push": "Push",
    "release": "Release",
}

# 阶段状态 → (符号, 语义色)；会话结束仍未执行的状态渲染为跳过 `-`
_STATE_STYLE = {
    "pending": ("·", COLOR_PUSH_PENDING),
    "running": ("…", COLOR_PUSH_PENDING),
    "done": ("✓", COLOR_SUCCESS_SOFT),
    "failed": ("✕", COLOR_ERROR),
    "skipped": ("-", COLOR_PLACEHOLDER),
}

# 日志流级别 → (前缀, 语义色)
_LOG_STYLE = {
    "ACTION": (">", COLOR_PUSH_PENDING),
    "DONE": ("✓", COLOR_SUCCESS_SOFT),
    "FAIL": ("✕", COLOR_ERROR),
    "NOTE": (">", COLOR_GRAY),
    "PROGRESS": (">", COLOR_PUSH_PENDING),
}


@dataclass
class _Stage:
    """推送会话中的单个阶段。"""

    token: str              # 阶段标识（_STAGE_EN 键）
    state: str = "pending"  # pending / running / done / failed / skipped
    detail: str = ""        # 附加信息（无更改 / 失败原因等）

    @property
    def name(self) -> str:
        return _STAGE_EN[self.token]


class PushView(ViewBase):
    """推送标签页：推送会话一页流视图（阶段摘要 + 实时日志流）。"""

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
        self._max_rows = max_rows    # 内容区可用行数；日志流窗口 = 行数 - 2（头+摘要）
        self._stages: list[_Stage] = []   # 当前会话阶段
        self._session: str | None = None  # None（无会话）/ running / done / failed
        self._log_lines: list[str] = []   # 日志流（markup 行，追加滚动）
        self._last_lines: list[str] | None = None  # 上次渲染行（markup，增量对比基准）
        self._lock = threading.Lock()
        # 事件订阅：sync.run() 主线程同步发布，回调可直绘
        bus.subscribe(ActionLog, self._on_action_log)
        bus.subscribe(SyncFailed, self._on_sync_failed)
        bus.subscribe(SyncCompleted, self._on_sync_completed)

    # ── 生命周期 ──
    def _load(self) -> None:
        """一页流事件驱动，无需扫描；空实现（激活即就绪，零 I/O）。"""

    # ── 渲染（纯函数，只读缓存）──
    def _render(self) -> str:
        return markup_to_ansi("\n".join(self._render_lines()))

    def _render_lines(self) -> list[str]:
        """当前视图的 markup 行列表：竖排阶段行 + 日志流窗口。

        行数恒定 = 阶段行数 + 日志窗口（不足补空行占位）。无会话时同样渲染
        一页流框架（按当前状态预判的待执行阶段 + 空日志窗口），与推送会话
        行数一致——开屏即一页流，Enter 后仅增量更新，无整屏跳变。

        变更数只在开屏显示（Scan 行后 `· Scan 3 change(s)`），推送过程中
        阶段行只显示符号变化（✓/…/✕），不显示进度细节。
        """
        with self._lock:
            stages = list(self._stages)
            session = self._session
            logs = list(self._log_lines)
        if session is None:
            # 无会话：一页流框架（预判阶段 + 空日志窗口）
            info = self._get_info()
            stages = self._plan_stages(info) if info is not None else []
            if info is not None and info.change_count:
                scan = next((s for s in stages if s.token == "scan"), None)
                if scan is not None:
                    scan.detail = tr(
                        f"{info.change_count} 处变化",
                        f"{info.change_count} change(s)")
            logs = []
        stage_lines = self._stage_lines(stages, show_detail=(session is None))
        limit = self._max_rows() if self._max_rows is not None else None
        window = max(0, limit - len(stage_lines)) if limit is not None else None
        if window is not None:
            tail = logs[-window:]
            padded = [""] * (window - len(tail)) + tail
        else:
            padded = logs
        return stage_lines + padded

    def _stage_lines(self, stages: list[_Stage],
                     show_detail: bool = False) -> list[str]:
        """阶段行竖排：`  ✓ Scan` 每阶段一行，符号 + 英文名，对齐清楚。

        show_detail（开屏）时显示变更数等 detail；推送过程中不显示
        （进度细节只在开屏可见，推送只表达符号变化）。
        """
        lines = []
        for st in stages:
            sym, color = _STATE_STYLE[st.state]
            label = st.name
            if show_detail and st.detail:
                label += f" {st.detail}"
            lines.append(f"  [{color}]{sym}[/] {label}")
        return lines

    def _log_markup(self, level: str, message: str) -> str:
        """日志流单行 markup：`  前缀 消息`，按级别着色。"""
        prefix, color = _LOG_STYLE.get(level, (">", COLOR_GRAY))
        return f"  {prefix} [{color}]{message}[/]"

    def _append_log(self, level: str, message: str) -> None:
        """追加日志流行（已持锁调用）。"""
        self._log_lines.append(self._log_markup(level, message))

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
        """开启推送会话：fetch 刷新远程状态 → 构建阶段清单 → 执行同步。

        会话视图先行渲染（阶段摘要 + 空日志流），随后事件驱动追加刷新。
        """
        info = self._refresh_status(True)  # fetch 刷新远程状态（分叉/落后检测可靠）
        stages = self._plan_stages(info)
        with self._lock:
            self._stages = stages
            self._session = "running"
            self._log_lines = []
        self._refresh()  # 行数变化（摘要 → 会话）：整区重绘
        try:
            self.sync.run()  # 阶段事件经订阅增量刷新会话视图
        except SyncError:
            pass  # SyncFailed 事件已标记失败（_on_sync_failed）

    def _refresh(self) -> None:
        """增量刷新：行数不变则定点更新差异行（不清屏），否则整区重绘。

        阶段摘要/日志流变化通常只改若干行文本，定点更新避免推送过程中
        反复 \x1b[J 清屏重绘的闪烁；会话开始/结束等行数变化场景整区重绘。
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

    def _plan_stages(self, info: RepoInfo) -> list[_Stage]:
        """按当前状态构建本次推送的阶段清单（与 sync.run 执行顺序一致）。

        用 RepoInfo.release_pending（状态服务已算好的字段），渲染路径零 I/O。
        """
        tokens: list[str] = []
        if info.status == RepoStatus.NO_REPO:
            tokens += ["init", "config"]
        elif not info.remote_url:
            tokens.append("config")
        tokens += ["scan", "commit", "push"]
        if info.release_pending:
            tokens.append("release")
        return [_Stage(token=t) for t in tokens]

    # ── 事件驱动（主线程同步回调）──
    def _on_action_log(self, event: ActionLog) -> None:
        """按阶段标识更新阶段状态；里程碑消息（非 PROGRESS）追加进日志流。

        PROGRESS（实时进度）只更新对应阶段 detail 不翻转状态、不进日志流
        （如 push 的对象写入百分比），避免百分比逐条刷屏占空间。
        """
        if not event.stage or self._session is None:
            return
        with self._lock:
            if event.level != "PROGRESS":
                self._append_log(event.level, event.message)
            st = next((s for s in self._stages if s.token == event.stage), None)
            if st is not None:
                if event.level == "ACTION":
                    st.state = "running"
                elif event.level == "FAIL":
                    st.state = "failed"
                    st.detail = event.message
                elif event.level == "PROGRESS":
                    st.detail = event.message  # 实时进度：仅更新详情
                else:  # DONE / NOTE：阶段完成
                    st.state = "done"
                    if event.level == "NOTE":
                        st.detail = event.message
        self._refresh()

    def _on_sync_failed(self, event: SyncFailed) -> None:
        """会话失败：失败原因进日志流，进行中/未开始的阶段标失败。"""
        with self._lock:
            self._session = "failed"
            self._append_log("FAIL", event.message)
            target = next((s for s in reversed(self._stages)
                           if s.state in ("running", "pending")), None)
            if target:
                target.state = "failed"
        self._refresh()

    def _on_sync_completed(self, event: SyncCompleted) -> None:
        """会话完成：未执行阶段标跳过（完成消息由 push 阶段 DONE 事件表达）。"""
        with self._lock:
            self._session = "done"
            for st in self._stages:
                if st.state in ("pending", "running"):
                    st.state = "skipped"
        self._refresh()
