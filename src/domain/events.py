"""领域事件：DomainEventBus 与事件定义。

替代旧 on_log 回调：领域/应用层发布事件，表现层订阅刷新，
UI 从被调用者变为观察者。发布者不感知订阅者，订阅者之间互不影响。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable


# ── 事件定义 ─────────────────────────────────────────
@dataclass(frozen=True)
class DomainEvent:
    """事件基类。"""


@dataclass(frozen=True)
class ActionLog(DomainEvent):
    """操作日志事件（替代 log()）。level: ACTION/DONE/FAIL/NOTE"""
    level: str
    message: str


@dataclass(frozen=True)
class SyncStarted(DomainEvent):
    pass


@dataclass(frozen=True)
class SyncCompleted(DomainEvent):
    committed: int = 0
    pushed: bool = False
    release_published: bool = False
    updated_items: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SyncFailed(DomainEvent):
    message: str = ""


@dataclass(frozen=True)
class RestoreCompleted(DomainEvent):
    commit_hash: str = ""


@dataclass(frozen=True)
class FileChanged(DomainEvent):
    name: str = ""
    action: str = ""  # 'A' 推送 / 'D' 删除


@dataclass(frozen=True)
class ReleasePublished(DomainEvent):
    tag: str = ""


@dataclass(frozen=True)
class RepoChanged(DomainEvent):
    """仓库状态/缓存已刷新（UI 据此重建屏幕）。"""


# ── 事件总线 ─────────────────────────────────────────
class DomainEventBus:
    def __init__(self):
        self._subscribers: dict[type, list[Callable[[Any], None]]] = {}
        self._lock = threading.Lock()

    def subscribe(self, event_type: type, handler: Callable[[Any], None]) -> None:
        """订阅某类事件。handler 在发布者线程同步调用。"""
        with self._lock:
            self._subscribers.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type: type, handler: Callable[[Any], None]) -> None:
        with self._lock:
            handlers = self._subscribers.get(event_type, [])
            if handler in handlers:
                handlers.remove(handler)

    def publish(self, event: DomainEvent) -> None:
        """同步分发事件；单个订阅者异常被隔离，不影响其他订阅者。

        订阅 DomainEvent 基类的处理器可收到全部事件。
        """
        with self._lock:
            handlers = list(self._subscribers.get(type(event), ()))
            if type(event) is not DomainEvent:
                handlers += list(self._subscribers.get(DomainEvent, ()))
        for handler in handlers:
            try:
                handler(event)
            except Exception:
                # 订阅者异常不得中断发布链路
                continue
