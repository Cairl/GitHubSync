"""表现层：App —— 瘦身后的 TUI 主循环（纯控制器）。

职责：
- Rich Live 渲染循环（4fps），渲染路径零子进程调用；
- 全局键处理（O 打开远程 / Q 退出）与模式锁定前导航；
- 事件订阅驱动界面刷新（替代旧 on_log 回调）；
- 后台初始化线程启动（界面先渲染框架，数据懒加载）。

业务逻辑已全部下沉至 application 层与模式组件，本类不含任何 git/gh 命令。
"""

from __future__ import annotations

import msvcrt
import threading
import time
from datetime import datetime

from rich.console import Console
from rich.live import Live

from ..config import (
    COOLDOWN_PERIOD, KEY_DOWN, KEY_ENTER, KEY_LEFT, KEY_O, KEY_Q,
    KEY_RIGHT, KEY_UP,
)
from ..domain.events import ActionLog, DomainEvent, FileChanged, SyncCompleted
from ..domain.exceptions import SyncError
from ..domain.state import AppState
from ..utils import enable_vt100, get_key
from .context import AppContext


class App:
    def __init__(self, ctx: AppContext, modes: list):
        self.ctx = ctx
        self.modes = modes
        self.state: AppState = ctx.state
        self.console = Console()
        self.running = True
        self._live = None
        # 事件订阅在构造时注册：任意使用方式（含测试）都能收到领域事件
        ctx.bus.subscribe(DomainEvent, self._on_event)

    # ── 渲染 ──
    def build_screen(self):
        return self.ctx.renderer.render(self.state)

    def _on_event(self, event) -> None:
        """事件订阅：写入日志/状态缓存，然后刷新界面（合并抖动）。"""
        state = self.state
        if isinstance(event, ActionLog):
            state.logs.append((datetime.now().strftime("%H:%M:%S"), event.level, event.message))
        elif isinstance(event, SyncCompleted):
            state.updated_items = dict(event.updated_items)
            state.first_sync_done = True
        elif isinstance(event, FileChanged):
            state.updated_items[event.name] = event.action
        if self._live is not None:
            self._live.update(self.build_screen())

    # ── 主循环 ──
    def run(self) -> None:
        enable_vt100()
        ctx = self.ctx

        ctx.reload_file_list()
        with Live(
            self.build_screen(),
            console=self.console,
            refresh_per_second=4,
            screen=True,
        ) as live:
            self._live = live
            live.update(self.build_screen())

            if not self.state.first_sync_done:
                ctx.start_background_init()

            while self.running:
                if msvcrt.kbhit():
                    if self.state.is_busy() or self.state.in_cooldown():
                        while msvcrt.kbhit():
                            msvcrt.getch()
                        time.sleep(0.01)
                        continue
                    key = get_key()
                    self.handle_key(key)
                    live.update(self.build_screen())
                else:
                    live.update(self.build_screen())
                    time.sleep(0.05)

            self._live = None

        self.console.print("\n退出成功。")

    # ── 按键分发 ──
    def handle_key(self, key: bytes) -> None:
        ctx, state = self.ctx, self.state

        # 全局键：任意阶段生效
        if key in (KEY_O, b"O"):
            ctx.open_remote()
            return
        if key in (KEY_Q, b"Q"):
            self.running = False
            return

        mode = self.modes[state.mode_index]

        if not state.mode_locked:
            # 模式选择阶段：↑↓ 浏览列表，←→ 切换模式，Enter 锁定
            if key in (KEY_UP, KEY_DOWN):
                mode.handle_key(key, ctx)
            elif key == KEY_LEFT and state.mode_index != 0:
                state.mode_index -= 1
            elif key == KEY_RIGHT and state.mode_index != len(self.modes) - 1:
                state.mode_index += 1
                # 光标聚焦恢复模式即预加载提交历史（预览）
                if state.mode_index == len(self.modes) - 1:
                    ctx.ensure_releases_loaded()
            elif key == KEY_ENTER:
                state.lock_mode()
                self._on_mode_selected()
            return

        # 模式已锁定：交给模式组件
        mode.handle_key(key, ctx)

    def _on_mode_selected(self) -> None:
        """模式确认后的初始化：推送模式执行同步，恢复模式加载提交历史。"""
        ctx, state = self.ctx, self.state
        # 等待后台初始化线程结束，避免与同步操作并发访问仓库
        ctx.wait_init_done(timeout=30)
        mode = self.modes[state.mode_index]
        mode.on_mode_selected(ctx)
