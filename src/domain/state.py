"""AppState：收敛散落的状态标志，提供最小状态机。

将旧实现中 mode / mode_locked / operation_in_progress / cooldown_until /
first_sync_done / 各类缓存统一为一个对象，渲染与按键处理只读此对象，
消除互相踩踏的竞态风险。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class AppPhase(Enum):
    IDLE = "idle"
    SYNCING = "syncing"
    RESTORING = "restoring"


@dataclass
class AppState:
    repo_path: str
    phase: AppPhase = AppPhase.IDLE
    mode_index: int = 0            # 当前模式在注册表中的下标（原 self.mode）
    mode_locked: bool = False      # 模式是否已锁定（回车确认）
    selected_index: int = 0        # 列表选中项
    action_index: int = 0          # 0=列表焦点, 1=操作按钮焦点
    first_sync_done: bool = False
    cooldown_until: float = 0.0
    updated_items: dict = field(default_factory=dict)  # 变更文件状态 {'name': 'A'|'D'}

    # 视图缓存（由后台线程刷新，渲染只读）
    status: dict | None = None
    release: dict | None = None
    changes: int = 0
    logs: list = field(default_factory=list)
    file_items: list = field(default_factory=list)
    release_items: list = field(default_factory=list)

    # ── 状态机 ──
    def enter(self, phase: AppPhase) -> None:
        self.phase = phase

    def enter_idle(self) -> None:
        self.phase = AppPhase.IDLE

    def is_busy(self) -> bool:
        """同步/恢复进行中：此时按键应被丢弃。"""
        return self.phase in (AppPhase.SYNCING, AppPhase.RESTORING)

    def enter_cooldown(self, period: float = 1.0) -> None:
        self.cooldown_until = time.time() + period
        if self.phase == AppPhase.IDLE:
            self.phase = AppPhase.IDLE

    def in_cooldown(self) -> bool:
        return time.time() < self.cooldown_until

    def lock_mode(self) -> None:
        self.mode_locked = True

    def reset_focus(self) -> None:
        self.action_index = 0

    # ── 缓存读写（渲染路径零 I/O：只读缓存，不触发子进程）──
    def has_status(self) -> bool:
        return self.status is not None

    def get_release(self):
        return self.release or None
