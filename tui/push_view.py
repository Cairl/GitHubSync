"""推送标签页：推送会话一页流视图（阶段摘要 + 实时日志流，非分步回显）。

Enter 执行推送时，内容区在一页内展示完整推送会话：
- 会话头：整体状态（推送中… / 推送完成（N 项更改）/ 推送失败：原因）；
- 阶段摘要：一行横排展示全部阶段状态（`[✓ Scan] [✓ Commit] [… Push]`
  状态符号 + 英文短名，一目了然）；
- 日志流：下方固定行数窗口，ActionLog 消息逐行追加滚动（ACTION/DONE/
  NOTE/FAIL/PROGRESS 全量落流，按级别着色），回显详细、自然滚动。

阶段标识由 ActionLog.stage 携带（结构化事件驱动）：core 服务在发布时
标注阶段，表现层按阶段状态机更新，而非解析日志文本。CLI 等纯文本
消费者忽略该字段，零影响。

实时进度（PROGRESS）：scan/commit/push 阶段进行中发布实时详情——
扫描到 N 项更改、已提交 N 项更改、push 对象写入百分比（git push
--progress 流式解析），既更新阶段摘要 detail，也追加进日志流。

空态（无会话）：差异摘要 + 「按 Enter 推送」提示（见 _summary）。
每次 Enter 开启新会话（覆盖上一次结果视图）；切出保留当前会话可切回查看。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable

from core.config import (COLOR_ERROR, COLOR_GRAY, COLOR_PLACEHOLDER,
                         COLOR_PUSH_PENDING, COLOR_SUCCESS_SOFT, COLOR_WARN,
                         KEY_ENTER)
from core.events import (ActionLog, DomainEventBus, SyncCompleted, SyncFailed)
from core.exceptions import SyncError
from core.i18n import tr
from core.protocols import GitProvider
from core.status import (RepoInfo, RepoStatus, changelog_pending)
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
        self._header = ""                 # 会话头（markup）
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
        """当前视图的 markup 行列表：会话头 + 阶段摘要行 + 日志流窗口。

        会话中行数恒定 = 2 + 日志窗口（不足补空行占位），日志追加/阶段
        变化只改内容不改行数，增量刷新可走定点更新不清屏。
        """
        with self._lock:
            stages = list(self._stages)
            session = self._session
            header = self._header
            logs = list(self._log_lines)
        if session is None:
            return self._idle_lines()
        limit = self._max_rows() if self._max_rows is not None else None
        window = max(1, limit - 2) if limit is not None else None
        if window is not None:
            tail = logs[-window:]
            padded = [""] * (window - len(tail)) + tail
        else:
            padded = logs
        return [header, self._stage_summary_line(stages)] + padded

    def _idle_lines(self) -> list[str]:
        """无会话：差异摘要（状态色）+ Enter 提示行（灰色）。"""
        lines = []
        summary = self._summary()
        if summary:
            lines.append(summary)
        lines.append(
            f"[{COLOR_PLACEHOLDER}]{tr('按 Enter 推送', 'Press Enter to push')}[/]")
        return lines

    def _stage_summary_line(self, stages: list[_Stage]) -> str:
        """阶段摘要行：`  [✓ Scan] [… Push]` 横排，全部阶段一屏可见。"""
        blocks = []
        for st in stages:
            sym, color = _STATE_STYLE[st.state]
            blocks.append(f"[{color}][{sym} {st.name}][/]")
        return "  " + " ".join(blocks)

    def _log_markup(self, level: str, message: str) -> str:
        """日志流单行 markup：`  前缀 消息`，按级别着色。"""
        prefix, color = _LOG_STYLE.get(level, (">", COLOR_GRAY))
        return f"  {prefix} [{color}]{message}[/]"

    def _append_log(self, level: str, message: str) -> None:
        """追加日志流行（已持锁调用）。"""
        self._log_lines.append(self._log_markup(level, message))

    def _summary(self) -> str:
        """推送前差异摘要行：按当前状态表达（与 CLI status_line 观感一致）。"""
        info = self._get_info()
        if info is None:
            return ""
        st = info.status
        if st == RepoStatus.ERROR:
            return f"[{COLOR_ERROR}]{tr(f'错误: {info.error}', f'error: {info.error}')}[/]"
        if st == RepoStatus.NO_REPO:
            return f"[{COLOR_PLACEHOLDER}]{tr('不是 git 仓库', 'not a git repository')}[/]"
        if st == RepoStatus.NO_REMOTE:
            return f"[{COLOR_PLACEHOLDER}]{tr('未配置远程', 'no remote')}[/]"
        if st == RepoStatus.DIVERGED:
            return (f"[{COLOR_ERROR}]{tr(f'分叉 (领先 {info.ahead}, 落后 {info.behind})',
                                         f'diverged (ahead {info.ahead}, behind {info.behind})')}[/]")
        if st == RepoStatus.AHEAD:
            return (f"[{COLOR_WARN}]{tr(f'领先 {info.ahead}', f'ahead {info.ahead}')}[/]")
        if st == RepoStatus.BEHIND:
            return (f"[{COLOR_WARN}]{tr(f'落后 {info.behind}', f'behind {info.behind}')}[/]")
        if st == RepoStatus.CHANGED:
            parts = []
            if info.added:
                parts.append(f"+{info.added}")
            if info.modified:
                parts.append(f"~{info.modified}")
            if info.deleted:
                parts.append(f"-{info.deleted}")
            detail = f" ({' '.join(parts)})" if parts else ""
            return (f"[{COLOR_WARN}]{tr(f'{info.change_count} 处变化{detail}',
                                        f'{info.change_count} changes{detail}')}[/]")
        if info.release_pending:
            return f"[{COLOR_WARN}]{tr('Release 待发布', 'Release pending')}[/]"
        return f"[{COLOR_SUCCESS_SOFT}]{tr('已同步', 'synced')}[/]"

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

        会话视图先行渲染（推送中… + 阶段摘要 + 空日志流），随后事件驱动
        追加刷新。
        """
        info = self._refresh_status(True)  # fetch 刷新远程状态（分叉/落后检测可靠）
        stages = self._plan_stages(info)
        with self._lock:
            self._stages = stages
            self._session = "running"
            self._header = f"[{COLOR_PUSH_PENDING}]{tr('推送中…', 'Pushing…')}[/]"
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
        """按当前状态构建本次推送的阶段清单（与 sync.run 执行顺序一致）。"""
        tokens: list[str] = []
        if info.status == RepoStatus.NO_REPO:
            tokens += ["init", "config"]
        elif not info.remote_url:
            tokens.append("config")
        tokens += ["scan", "commit", "push"]
        if changelog_pending(self.sync.repo_path):
            tokens.append("release")
        return [_Stage(token=t) for t in tokens]

    # ── 事件驱动（主线程同步回调）──
    def _on_action_log(self, event: ActionLog) -> None:
        """按阶段标识更新阶段状态；所有消息追加进日志流（一页流回显）。

        PROGRESS（实时进度）只更新 detail 不翻转状态——阶段仍在进行中，
        详情列展示最新进度（如 push 的对象写入百分比）。
        """
        if not event.stage or self._session is None:
            return
        with self._lock:
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
        """会话失败：头行带失败原因，进行中/未开始的阶段标失败。"""
        with self._lock:
            self._session = "failed"
            self._header = (f"[{COLOR_ERROR}]{tr('推送失败:', 'Push failed:')}[/]"
                            f" {event.message}")
            self._append_log("FAIL", event.message)
            target = next((s for s in reversed(self._stages)
                           if s.state in ("running", "pending")), None)
            if target:
                target.state = "failed"
        self._refresh()

    def _on_sync_completed(self, event: SyncCompleted) -> None:
        """会话完成：头行带变更数量，未执行阶段标跳过。"""
        with self._lock:
            self._session = "done"
            n = len(event.updated_items)
            if n:
                detail = tr(f"{n} 项更改", f"{n} change(s)")
                message = tr(f"推送完成（{detail}）", f"Push completed ({detail})")
            else:
                message = tr("推送完成", "Push completed")
            self._header = f"[{COLOR_SUCCESS_SOFT}]{message}[/]"
            self._append_log("DONE", message)  # 纯文本消息，避免嵌套 markup
            for st in self._stages:
                if st.state in ("pending", "running"):
                    st.state = "skipped"
        self._refresh()
