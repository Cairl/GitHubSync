"""执行器抽象：同步（测试/降级）与线程池（生产）双实现。

契约：submit(fn, callback) —— fn 在指定上下文执行，完成后 callback(result)；
fn 抛异常时 callback(None)（后台任务永不炸调用方）。

ThreadExecutor 的 callback 在 worker 线程触发：callback 只允许线程安全操作
（queue.put / 置标志位），禁止任何 ANSI 渲染与 DomainEventBus 发布
（同步派发等于在后台线程渲染）。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable


class InlineExecutor:
    """同步执行器：submit 立即执行并回调（测试与降级路径用，确定性）。"""

    def submit(self, fn: Callable, callback: Callable) -> None:
        try:
            result = fn()
        except Exception:
            result = None
        callback(result)

    def shutdown(self) -> None:
        """无资源，空操作（与 ThreadExecutor 接口对齐）。"""


class ThreadExecutor:
    """线程池执行器：fn 在 worker 线程执行，callback 同线程触发。"""

    def __init__(self, max_workers: int = 4):
        self._pool = ThreadPoolExecutor(max_workers=max_workers)

    def submit(self, fn: Callable, callback: Callable) -> None:
        def run() -> None:
            try:
                result = fn()
            except Exception:
                result = None
            callback(result)
        self._pool.submit(run)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False)
