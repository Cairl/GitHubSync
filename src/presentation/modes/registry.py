"""表现层：ModeRegistry —— 模式注册表。

主循环遍历注册表渲染导航栏与分发按键，对模式种类零感知。
新增模式：实现 Mode 协议 + registry.register("名称", 类)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from ..context import AppContext

if TYPE_CHECKING:
    from .base import Mode


class ModeRegistry:
    def __init__(self):
        self._factories: list[tuple[str, Callable[[], object]]] = []

    def register(self, name: str, mode_cls: type) -> None:
        """注册模式类（延迟实例化，实例化时注入 ctx）。"""
        def factory():
            return mode_cls()
        self._factories.append((name, factory))

    def names(self) -> list[str]:
        return [name for name, _ in self._factories]

    def create_all(self) -> list:
        """实例化全部模式组件（按注册顺序）。"""
        return [factory() for _, factory in self._factories]
