"""领域事件总线与事件定义。

替代旧 GitManager 的 logs/on_log 回调体系：服务发布事件，
cli/output 或 tui 订阅后把日志作为追加行输出（自然滚动，无全屏重绘）。
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ActionLog:
    """操作过程日志。level ∈ ACTION / DONE / FAIL / NOTE / PROGRESS。

    - ACTION：阶段开始（进行中）；
    - DONE：阶段完成；NOTE：阶段完成附注（不改变完成语义）；
    - FAIL：阶段失败；
    - PROGRESS：阶段进行中的实时进度（如 push 的对象写入百分比），
      同一阶段可多次发布，最后一次为最新进度（表现层只更新详情不翻转状态）。

    stage：流程阶段标识（如 push 流程的 init/config/scan/commit/push/release），
    供表现层做结构化进度回显；CLI 等纯文本消费者忽略该字段。默认空串向后兼容。
    """

    level: str
    message: str
    stage: str = ""


@dataclass
class SyncCompleted:
    """同步成功完成。"""

    pushed: bool
    committed: int
    updated_items: dict[str, str] = field(default_factory=dict)


@dataclass
class SyncFailed:
    """同步失败（异常向上抛出前发布）。"""

    message: str


@dataclass
class RestoreCompleted:
    """恢复完成（commit hash 或 origin/<branch>）。"""

    target: str


@dataclass
class ReleasePublished:
    """Release 发布完成。"""

    tag: str
    notes: str = ""


class DomainEventBus:
    """同步事件总线：按事件类型分发，订阅者即时回调。"""

    def __init__(self):
        self._handlers: dict[type, list[Callable]] = defaultdict(list)

    def subscribe(self, event_type: type, handler: Callable) -> None:
        """订阅指定类型的事件。"""
        self._handlers[event_type].append(handler)

    def publish(self, event) -> None:
        """发布事件，按注册顺序同步调用所有订阅者。"""
        for handler in self._handlers.get(type(event), []):
            handler(event)
