"""推送标签页：推送会话阶段行累积回显（每阶段一行，完成留痕）。

开屏即一屏框架，Enter 推送前后不跳界面：
- 激活即后台预执行扫描（SyncService.scan()）：完成前 loading 留白，
  完成后免 Enter 即见真实扫描结论行（`✓ 扫描完成`(+ N 项更改) /
  `> 没有需要提交的更改`）；未初始化/错误状态不预扫描（留空）；
- Enter 推送：ready 会话复用预扫描结果续跑（`sync.run(reuse_scan=True)`，
  扫描不执行第二遍），其余状态清空阶段行全流程执行；提交/推送/发布
  每个阶段一行按出现顺序累积——进行中行 `> 当前动作`，完成行 `✓ 结果`
  保留不覆盖，失败行 `✕ 原因`；push 阶段实时进度（百分比 + 对象数）
  拼在当前动作行尾并覆盖旧进度，如 `> 推送到 GitHub 42% (12/29) · 1.20 MiB`；
- 结束后：所有阶段行保留可回溯；整体失败在末尾追加 `✕ 失败原因`。

事件驱动：core 服务发布 ActionLog（带 stage 标识），表现层按 stage
定位行——新阶段追加一行，已有阶段更新该行；PROGRESS 拼到该行文本
（进行中动作行后拼最新进度、完成行后拼附注，重复消息自动去重）。
CLI 等纯文本消费者忽略 stage 字段，零影响。

线程纪律：预扫描在 executor worker 线程执行，期间发布的 ActionLog
先入缓冲区（worker 禁止 ANSI 渲染），完成后统一应用为 ready 会话，
经 on_loaded 通知主循环重绘。会话进行中/已结束不重扫（留痕优先）；
ready 会话随状态签名变化失效重扫（预扫描结论始终最新）。
"""
from __future__ import annotations

import threading
from typing import Callable

from core.config import (COLOR_ERROR, COLOR_GRAY, COLOR_PUSH_PENDING,
                         COLOR_SUCCESS_SOFT, KEY_ENTER)
from core.events import (ActionLog, DomainEventBus, SyncCompleted, SyncFailed)
from core.exceptions import SyncError
from core.protocols import GitProvider
from core.status import RepoInfo, RepoStatus
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
    """推送标签页：预扫描 + 推送会话阶段行累积回显。"""

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
        self._session: str | None = None  # None（无会话）/ ready（已预扫描）/ running / done / failed
        self._stage: dict[str, tuple[str, str]] = {}  # stage → (level, message)
        self._stage_order: list[str] = []             # stage 出现顺序（渲染行序）
        self._stage_title: dict[str, str] = {}        # stage → ACTION 标题（进度拼接基准）
        self._last_lines: list[str] | None = None  # 上次渲染行（markup，增量对比基准）
        self._lock = threading.Lock()
        self._buffering = False       # 预扫描进行中：ActionLog 入缓冲区不直绘
        self._buffer: list[ActionLog] = []
        # 事件订阅：会话内主线程同步发布可直绘；预扫描 worker 发布走缓冲
        bus.subscribe(ActionLog, self._on_action_log)
        bus.subscribe(SyncFailed, self._on_sync_failed)
        bus.subscribe(SyncCompleted, self._on_sync_completed)

    # ── 生命周期 ──
    def _load(self) -> None:
        """预执行扫描阶段：Enter 前真实跑完「暂存 → 收集变更项」。

        worker 线程执行：scan() 同步发布的 ActionLog 先入缓冲区（线程
        纪律：worker 禁止 ANSI 渲染），完成后统一应用为 ready 会话的
        阶段行，经 on_loaded 通知主循环重绘。未初始化/错误状态跳过；
        running/done/failed 会话保留留痕不重扫；ready 会话随失效重扫
        （预扫描结论始终最新）。扫描失败转为 failed 会话留痕。
        """
        info = self._get_info()
        if info is None or info.status in (RepoStatus.NO_REPO,
                                           RepoStatus.ERROR):
            return
        with self._lock:
            if self._session not in (None, "ready"):
                return
            self._buffering = True
            self._buffer = []
        try:
            self.sync.scan()
        except SyncError as e:
            with self._lock:
                buf = self._take_buffer_locked()
                self._reset_stage_locked()
                for ev in buf:
                    self._set_stage(ev.stage, ev.level, ev.message)
                self._session = "failed"
                self._set_stage("__fail", "FAIL", e.message)
            return
        with self._lock:
            buf = self._take_buffer_locked()
            self._reset_stage_locked()
            for ev in buf:
                self._set_stage(ev.stage, ev.level, ev.message)
            self._session = "ready"

    def _take_buffer_locked(self) -> list[ActionLog]:
        """取出事件缓冲并结束缓冲态（已持锁调用）。"""
        self._buffering = False
        buf, self._buffer = self._buffer, []
        return buf

    def _reset_stage_locked(self) -> None:
        """清空阶段行（已持锁调用；重扫时丢弃上一轮结论防残留）。"""
        self._stage.clear()
        self._stage_order.clear()
        self._stage_title.clear()

    # ── 渲染（纯函数，只读缓存）──
    def _render(self) -> str:
        return markup_to_ansi("\n".join(self._render_lines()))

    def _render_lines(self) -> list[str]:
        """当前视图的 markup 行列表：会话阶段行按出现顺序累积。

        无会话（未初始化/错误状态/loading 留白由 ViewBase 处理）：空；
        ready（预扫描完成）：真实扫描结论行，免 Enter 即见；推送中/结束：
        每个阶段一行累积，完成留痕、失败红色，超出内容区可用行数时
        截断保留末尾（最新阶段）。
        """
        with self._lock:
            session = self._session
            order = list(self._stage_order)
            stage = dict(self._stage)
        if session is None:
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
        """开启推送会话：fetch 刷新远程状态 → ready 续跑，否则清空全流程。

        ready 会话（Enter 前已预扫描）保留阶段行并复用扫描结果
        （sync.run(reuse_scan=True)），扫描不执行第二遍；其余状态清空
        阶段行从初始化开始全流程执行。会话视图先行渲染，随后事件驱动
        逐阶段追加刷新。
        """
        self._refresh_status(True)  # fetch 刷新远程状态（分叉/落后检测可靠）
        with self._lock:
            resume = self._session == "ready"
            self._session = "running"
            if not resume:
                self._reset_stage_locked()
        self._refresh()  # 行数变化：整区重绘
        try:
            self.sync.run(reuse_scan=resume)  # 动作事件经订阅覆盖刷新视图
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

    # ── 事件驱动 ──
    def _on_action_log(self, event: ActionLog) -> None:
        """按 stage 更新阶段行：新阶段追加、已有阶段更新、PROGRESS 拼进度。

        预扫描期间（worker 线程发布）事件入缓冲区不直绘，完成后由
        _load 统一应用；会话内（主线程同步发布）直接更新并刷新。
        """
        with self._lock:
            if self._buffering:
                self._buffer.append(event)
                return
            if self._session is None:
                return
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
