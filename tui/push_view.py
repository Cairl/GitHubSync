"""推送标签页：控制台日志视图（实时显示推送过程日志，无差异文件清单）。

推送页整页作为"控制台"：Enter 执行推送时，操作事件（ActionLog 动作/完成/失败）
与 git 命令执行详情实时追加显示，结果通过日志行表达（[OK] 成功 / [X] 失败），
替代原文件清单与 [·]/[✓]/[✕] 状态符号，观感对齐 CLI 模式控制台输出。

日志来源与线程纪律：
- 事件总线（ActionLog / SyncFailed / ReleasePublished）：sync.run() 在主线程
  同步发布，回调直接追加 + 重绘（渲染纪律满足）；
- 命令钩子（register_command_hook）：fetch 等可能经 StatusService 后台线程
  触发，回调只追加不重绘（worker 线程禁止输出），主线程后续事件
  （ActionLog/SyncFailed）触发重绘时自然带出最新命令行。

无文件清单 → 无需 porcelain 扫描（_load 空实现，激活即就绪）；
无结果锁定 → 切出保留日志，切回仍可见；日志块超 _MAX_LOG_LINES 丢弃最旧行。
"""
from __future__ import annotations

import threading
from typing import Callable

from core.command import register_command_hook
from core.config import (COLOR_ERROR, COLOR_GRAY, COLOR_PLACEHOLDER,
                         COLOR_SUCCESS_SOFT, KEY_ENTER)
from core.events import ActionLog, DomainEventBus, ReleasePublished, SyncFailed
from core.exceptions import SyncError
from core.i18n import tr
from core.protocols import GitProvider
from core.status import RepoInfo
from core.sync_service import SyncService

from .renderer import markup_to_ansi
from .view_base import ViewBase

# 日志块上限：超出丢弃最旧行（一次完整推送约 10~20 行，100 行充裕）
_MAX_LOG_LINES = 100
# 单条命令/错误输出截断长度（防超长输出撑爆日志区）
_MAX_DETAIL = 160

# ActionLog level → 行前缀与语义色（对齐 CLI print_action_log 观感）
_LEVEL_STYLE = {
    "ACTION": (">", COLOR_GRAY),
    "NOTE": (">", COLOR_GRAY),
    "DONE": ("[OK]", COLOR_SUCCESS_SOFT),
    "FAIL": ("[X]", COLOR_ERROR),
}


class PushView(ViewBase):
    """推送标签页：控制台日志视图（事件驱动，无文件清单）。"""

    id = "push"

    def __init__(self, sync: SyncService, git: GitProvider, bus: DomainEventBus,
                 get_info: Callable[[], RepoInfo],
                 refresh_status: Callable[[bool], RepoInfo],
                 paint: Callable[[str], None],
                 executor=None, on_loaded=None):
        super().__init__(executor=executor, on_loaded=on_loaded)
        self.sync = sync
        self.git = git
        self._get_info = get_info
        self._refresh_status = refresh_status
        self._paint = paint
        self._logs: list[str] = []   # 日志行（markup 文本，渲染时统一转 ANSI）
        self._capturing = False      # 推送流程中：命令钩子才收集
        self._lock = threading.Lock()  # worker 线程命令回调与主线程渲染互斥
        # 事件订阅：sync.run() 主线程同步发布，回调可直绘
        bus.subscribe(ActionLog, self._on_action_log)
        bus.subscribe(SyncFailed, self._on_sync_failed)
        bus.subscribe(ReleasePublished, self._on_release)
        # 命令钩子：推送流程内收集 git 命令详情（fetch 经后台线程，只追加）
        self._cmd_hook = self._on_command
        register_command_hook(self._cmd_hook)

    # ── 生命周期 ──
    def _load(self) -> None:
        """日志事件驱动，无需扫描；空实现（激活即就绪，零 I/O）。"""

    # ── 渲染（纯函数，只读缓存）──
    def _render(self) -> str:
        with self._lock:
            logs = list(self._logs)
        if not logs:
            return markup_to_ansi(
                f"[{COLOR_PLACEHOLDER}]{tr('按 Enter 推送', 'Press Enter to push')}[/]")
        return markup_to_ansi("\n".join(logs))

    # ── 键处理 ──
    def handle_key(self, key: bytes) -> list[str]:
        if self._loading:
            return []  # loading 期间无数据，Enter 不得触发推送流程
        if key != KEY_ENTER:
            return []
        self._start_push()
        return ["pull"]  # 提交历史已变

    # ── 日志记录 ──
    def _append(self, line: str) -> None:
        """追加日志行并重绘（仅主线程事件回调调用）。"""
        with self._lock:
            self._logs.append(line)
            del self._logs[:-_MAX_LOG_LINES]
        self._paint(self._render())

    def _append_quiet(self, line: str) -> None:
        """追加日志行但不重绘（worker 线程命令回调；主线程后续事件带出）。"""
        with self._lock:
            self._logs.append(line)
            del self._logs[:-_MAX_LOG_LINES]

    def _on_action_log(self, event: ActionLog) -> None:
        prefix, color = _LEVEL_STYLE.get(event.level, (">", COLOR_GRAY))
        self._append(f"[{color}]{prefix}[/] {event.message}")

    def _on_sync_failed(self, event: SyncFailed) -> None:
        self._append(f"[{COLOR_ERROR}][X][/] {event.message}")

    def _on_release(self, event: ReleasePublished) -> None:
        self._append(f"[{COLOR_SUCCESS_SOFT}][OK][/] "
                     f"{tr(f'Release {event.tag} 已发布', f'Released {event.tag}')}")

    def _on_command(self, command: list[str], cwd: str | None,
                    ok: bool, output: str) -> None:
        """命令执行详情：仅推送流程（_capturing）期间收集，失败附输出首行。"""
        if not self._capturing:
            return
        line = f"[{COLOR_GRAY}]$ {' '.join(command)}[/]"
        if not ok:
            detail = (output or "").splitlines()
            if detail:
                line += f" [{COLOR_ERROR}]{detail[0][:_MAX_DETAIL]}[/]"
        self._append_quiet(line)

    # ── 推送流程 ──
    def _start_push(self) -> None:
        """执行推送：fetch 刷新远程状态 → 全量同步，日志流实时滚动。"""
        self._capturing = True
        try:
            self._refresh_status(True)  # fetch 刷新远程状态（分叉/落后检测可靠）
            try:
                self.sync.run()  # ActionLog / SyncFailed / 命令详情经订阅上屏
            except SyncError as e:
                if e.detail:  # 失败原始输出（SyncFailed 事件已记 [X] 消息）
                    detail = e.detail.splitlines()
                    self._append(f"[{COLOR_ERROR}]{detail[0][:_MAX_DETAIL]}[/]")
        finally:
            self._capturing = False
