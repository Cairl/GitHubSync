"""表现层：Mode 协议定义。

每个模式组件封装：按键处理（模式内）、数据加载、操作执行。
TUI 主循环只认本协议，对模式种类零感知。
"""

from __future__ import annotations

from typing import Protocol

from ..context import AppContext


class Mode(Protocol):
    name: str

    def handle_key(self, key: bytes, ctx: AppContext) -> None:
        """处理模式内按键（模式已锁定后）。"""
        ...

    def on_mode_selected(self, ctx: AppContext) -> None:
        """模式被回车确认后调用。"""
        ...
