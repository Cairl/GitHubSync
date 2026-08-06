"""表现层：RestoreMode —— 恢复模式组件。

浏览 Git 提交历史，选择后回车恢复到指定 commit。
提交历史由 AppContext 预加载（光标聚焦即加载，无占位回显）。
"""

from __future__ import annotations

from ...config import (
    COOLDOWN_PERIOD, KEY_DOWN, KEY_ENTER, KEY_RIGHT, KEY_UP,
)
from ...domain.state import AppPhase
from ..context import AppContext

PLACEHOLDERS = ("(无提交)", "(加载中...)")


class RestoreMode:
    name = "恢复模式"

    def handle_key(self, key: bytes, ctx: AppContext) -> None:
        state = ctx.state
        items = state.release_items

        if key == KEY_UP:
            if items:
                state.selected_index = (state.selected_index - 1) % len(items)
                state.reset_focus()
        elif key == KEY_DOWN:
            if items:
                state.selected_index = (state.selected_index + 1) % len(items)
                state.reset_focus()
        elif key == KEY_RIGHT:
            if state.mode_locked and self._restore_available(state.release_items):
                state.action_index = 1
        elif key == KEY_ENTER:
            if state.mode_locked and self._restore_available(state.release_items):
                if state.action_index == 1:
                    self.execute(ctx)
                else:
                    state.action_index = 1

    def on_mode_selected(self, ctx: AppContext) -> None:
        """恢复模式确认：确保提交历史已加载。"""
        ctx.ensure_releases_loaded()

    @staticmethod
    def _restore_available(items: list) -> bool:
        return bool(items) and items[0]["name"] not in PLACEHOLDERS

    def execute(self, ctx: AppContext) -> None:
        state = ctx.state
        item = state.release_items[state.selected_index]
        commit_hash = item["name"]

        state.enter(AppPhase.RESTORING)
        try:
            ok = ctx.restore.restore(commit_hash)
            if ok:
                state.first_sync_done = True
                ctx.refresh_caches()
                ctx.reload_file_list()
        finally:
            state.enter_idle()
            state.enter_cooldown(COOLDOWN_PERIOD)
            state.reset_focus()
