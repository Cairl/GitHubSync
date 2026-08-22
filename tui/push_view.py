"""推送标签页：推送会话进度视图（结构化阶段回显，非纯日志流）。

Enter 执行推送时，内容区显示一个"推送会话"：
- 会话头：整体状态（推送中… / 推送完成（N 项更改）/ 推送失败：原因）；
- 阶段行：本次推送实际执行的阶段清单（预查询动态构建），每行统一格式
  `  [k/n] 阶段名 状态符号 详情`，状态符号 = · 未开始 / … 进行中 /
  ✓ 完成 / ✕ 失败 / - 未执行，随事件实时刷新。

阶段标识由 ActionLog.stage 携带（结构化事件驱动）：core 服务在发布时
标注阶段，表现层按阶段状态机更新，而非解析日志文本。CLI 等纯文本
消费者忽略该字段，零影响。

实时进度（PROGRESS）：scan/commit/push 阶段进行中发布实时详情——
扫描到 N 项更改、已提交 N 项更改、push 对象写入百分比（git push
--progress 流式解析），只更新阶段行 detail 不翻转状态，推送过程不再
只有「…」符号。

空态（无会话）：差异摘要 + 「按 Enter 推送」提示（见 _summary）。
每次 Enter 开启新会话（覆盖上一次结果视图）；切出保留当前会话可切回查看。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable

from core.config import (COLOR_ERROR, COLOR_PLACEHOLDER, COLOR_PUSH_PENDING,
                         COLOR_SUCCESS_SOFT, COLOR_WARN, KEY_ENTER)
from core.events import (ActionLog, DomainEventBus, SyncCompleted, SyncFailed)
from core.exceptions import SyncError
from core.i18n import tr
from core.protocols import GitProvider
from core.status import (RepoInfo, RepoStatus, changelog_pending)
from core.sync_service import SyncService
from core.utils import get_display_width

from .renderer import markup_to_ansi
from .view_base import ViewBase

# 阶段元数据：标识 → (显示名中, 显示名英)，顺序即 sync.run 执行顺序
_STAGES = {
    "init": ("初始化仓库", "Init repository"),
    "config": ("配置远程", "Config remote"),
    "scan": ("扫描更改", "Scanning changes"),
    "commit": ("提交", "Commit"),
    "push": ("推送", "Push"),
    "release": ("发布 Release", "Publish release"),
}

# 阶段状态 → (符号, 语义色)；会话结束仍未执行的状态渲染为跳过 `-`
_STATE_STYLE = {
    "pending": ("·", COLOR_PUSH_PENDING),
    "running": ("…", COLOR_PUSH_PENDING),
    "done": ("✓", COLOR_SUCCESS_SOFT),
    "failed": ("✕", COLOR_ERROR),
    "skipped": ("-", COLOR_PLACEHOLDER),
}


@dataclass
class _Stage:
    """推送会话中的单个阶段。"""

    token: str              # 阶段标识（_STAGES 键）
    state: str = "pending"  # pending / running / done / failed / skipped
    detail: str = ""        # 附加信息（无更改 / 失败原因等）

    @property
    def name(self) -> str:
        return tr(*_STAGES[self.token])


class PushView(ViewBase):
    """推送标签页：推送会话进度视图（结构化阶段回显）。"""

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
        self._max_rows = max_rows    # 内容区可用行数；超限时压缩保证一屏显示
        self._stages: list[_Stage] = []   # 当前会话阶段
        self._session: str | None = None  # None（无会话）/ running / done / failed
        self._header = ""                 # 会话头（markup）
        self._last_lines: list[str] | None = None  # 上次渲染行（markup，增量对比基准）
        self._lock = threading.Lock()
        # 事件订阅：sync.run() 主线程同步发布，回调可直绘
        bus.subscribe(ActionLog, self._on_action_log)
        bus.subscribe(SyncFailed, self._on_sync_failed)
        bus.subscribe(SyncCompleted, self._on_sync_completed)

    # ── 生命周期 ──
    def _load(self) -> None:
        """进度视图事件驱动，无需扫描；空实现（激活即就绪，零 I/O）。"""

    # ── 渲染（纯函数，只读缓存）──
    def _render(self) -> str:
        return markup_to_ansi("\n".join(self._render_lines()))

    def _render_lines(self) -> list[str]:
        """当前视图的 markup 行列表；超出 max_rows 时隐藏未执行阶段保证一屏。

        压缩只影响行数（隐藏 skipped 阶段行），阶段 detail 在同一行内保留；
        会话头永远保留，绝不截断头部。
        """
        with self._lock:
            stages = list(self._stages)
            session = self._session
            header = self._header
        if session is None:
            return self._idle_lines()
        lines = self._stage_lines(stages, header, skipped=True)
        limit = self._max_rows() if self._max_rows is not None else None
        if limit is not None and len(lines) > limit:
            compact = self._stage_lines(stages, header, skipped=False)
            if len(compact) <= limit:
                return compact
        return lines

    def _idle_lines(self) -> list[str]:
        """无会话：差异摘要（状态色）+ Enter 提示行（灰色）。"""
        lines = []
        summary = self._summary()
        if summary:
            lines.append(summary)
        lines.append(
            f"[{COLOR_PLACEHOLDER}]{tr('按 Enter 推送', 'Press Enter to push')}[/]")
        return lines

    def _stage_lines(self, stages: list[_Stage], header: str,
                     skipped: bool) -> list[str]:
        """阶段行渲染：`  [k/n] 阶段名 符号[ 详情]`，符号列按显示宽度对齐。

        skipped=True 时包含「未执行」阶段（-）；False 时隐藏之（序号随之重排）。
        """
        lines = [header]
        active = [s for s in stages if skipped or s.state != "skipped"]
        n = len(active)
        width = max((get_display_width(s.name) for s in active), default=0)
        for i, st in enumerate(active, 1):
            sym, color = _STATE_STYLE[st.state]
            pad = " " * max(0, width - get_display_width(st.name))
            line = f"  [{i}/{n}] {st.name}{pad} [{color}]{sym}[/]"
            if st.detail:
                line += f" {st.detail}"
            lines.append(line)
        return lines

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

        会话视图先行渲染（推送中… + 全阶段未开始），随后事件驱动增量刷新。
        """
        info = self._refresh_status(True)  # fetch 刷新远程状态（分叉/落后检测可靠）
        stages = self._plan_stages(info)
        with self._lock:
            self._stages = stages
            self._session = "running"
            self._header = f"[{COLOR_PUSH_PENDING}]{tr('推送中…', 'Pushing…')}[/]"
        self._refresh()  # 行数变化（摘要 → 会话）：整区重绘
        try:
            self.sync.run()  # 阶段事件经订阅增量刷新会话视图
        except SyncError:
            pass  # SyncFailed 事件已标记失败（_on_sync_failed）

    def _refresh(self) -> None:
        """增量刷新：行数不变则定点更新差异行（不清屏），否则整区重绘。

        阶段状态变化通常只改 1~2 行的符号/文本，定点更新避免推送过程中
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
        """按阶段标识更新阶段状态：ACTION→进行中，DONE/NOTE→完成，FAIL→失败。

        PROGRESS（实时进度）只更新 detail 不翻转状态——阶段仍在进行中，
        详情列展示最新进度（如 push 的对象写入百分比），下次 ACTION/DONE
        事件到来前的中间态保持 running 不变。
        """
        if not event.stage or self._session is None:
            return
        with self._lock:
            st = next((s for s in self._stages if s.token == event.stage), None)
            if st is None:
                return
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
                self._header = (f"[{COLOR_SUCCESS_SOFT}]"
                                f"{tr(f'推送完成（{detail}）', f'Push completed ({detail})')}[/]")
            else:
                self._header = (f"[{COLOR_SUCCESS_SOFT}]"
                                f"{tr('推送完成', 'Push completed')}[/]")
            for st in self._stages:
                if st.state in ("pending", "running"):
                    st.state = "skipped"
        self._refresh()
