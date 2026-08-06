"""表现层：PushMode —— 推送模式组件。

文件列表浏览、推送/删除操作。业务逻辑委托 FileOpsService / SyncService，
本组件只负责交互编排与状态流转。
"""

from __future__ import annotations

from ...config import (
    COOLDOWN_PERIOD, KEY_DOWN, KEY_ENTER, KEY_LEFT, KEY_RIGHT, KEY_UP,
)
from ...domain.state import AppPhase
from ..context import AppContext

EMPTY_ITEM = "(空目录)"


class PushMode:
    name = "推送模式"

    def handle_key(self, key: bytes, ctx: AppContext) -> None:
        state = ctx.state
        items = state.file_items

        if key == KEY_UP:
            if items:
                state.selected_index = (state.selected_index - 1) % len(items)
                state.reset_focus()
        elif key == KEY_DOWN:
            if items:
                state.selected_index = (state.selected_index + 1) % len(items)
                state.reset_focus()
        elif key == KEY_LEFT:
            if state.mode_locked:
                state.reset_focus()  # 左键重置焦点到列表
        elif key == KEY_RIGHT:
            if state.mode_locked and self._has_action(items, state.selected_index):
                state.action_index = 1
        elif key == KEY_ENTER:
            if state.mode_locked and self._has_action(items, state.selected_index):
                if state.action_index == 1:
                    self.execute(items[state.selected_index], ctx)
                else:
                    state.action_index = 1

    def on_mode_selected(self, ctx: AppContext) -> None:
        """推送模式确认：执行完整同步。"""
        state = ctx.state
        state.enter(AppPhase.SYNCING)
        try:
            ctx.sync.run()
        except Exception:
            pass  # 失败事件已由 SyncService 发布
        finally:
            state.first_sync_done = True
            ctx.refresh_caches()
            ctx.reload_file_list()
            state.enter_idle()
            state.enter_cooldown(COOLDOWN_PERIOD)

    @staticmethod
    def _has_action(items: list, index: int) -> bool:
        return bool(items) and items[index]["name"] != EMPTY_ITEM

    def execute(self, item: dict, ctx: AppContext) -> None:
        """执行推送/删除操作（操作期间锁定按键，防止并发）。"""
        state = ctx.state
        state.enter(AppPhase.SYNCING)
        try:
            if item.get("ignored", False):
                ctx.file_ops.push_file(item["name"])
            else:
                ctx.file_ops.remove_file(item["name"])
        finally:
            ctx.refresh_caches()
            ctx.reload_file_list()
            state.enter_idle()
            state.enter_cooldown(COOLDOWN_PERIOD)
