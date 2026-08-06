"""表现层：RichRenderer —— 从旧 App 抽出的纯渲染组件。

职责：只读 AppState 与模式名称列表，构建 Rich Group 屏幕。
渲染路径零子进程调用、零副作用（不持有 Live、不触发刷新）。
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone

from rich.console import Group
from rich.style import Style
from rich.text import Text

from ..config import (
    STYLE_DEFAULT, STYLE_DIM, STYLE_GRAY, STYLE_RED, STYLE_GREEN,
    STYLE_WHITE, STYLE_SELECTED, STYLE_STRIKE, LEVEL_STYLES, LEVEL_LABELS,
)
from ..domain.state import AppState
from ..utils import get_display_width

_SEL_BG = "#CDD6F4"
_SEL_FG = "#11111B"


class RichRenderer:
    BOX_WIDTH = 101

    def __init__(self, mode_names: list[str], repo_path: str):
        self.mode_names = mode_names
        self.repo_path = repo_path

    # ── 静态工具（迁移自旧 App）────────────────────────
    @staticmethod
    def to_https_url(remote_raw: str) -> str:
        """将 git@ 或裸 remote 地址统一转为 https URL（去除 .git 后缀）"""
        if not remote_raw:
            return ""
        if remote_raw.startswith("git@"):
            url = f"https://{remote_raw[len('git@'):].replace(':', '/', 1)}"
        elif remote_raw.startswith("http"):
            url = remote_raw
        else:
            url = f"https://{remote_raw}"
        if url.endswith(".git"):
            url = url[:-4]
        return url

    @staticmethod
    def truncate(text: str, max_width: int) -> str:
        """按显示宽度截断文本，超出部分以省略号结尾"""
        if get_display_width(text) <= max_width:
            return text
        result = ""
        cur = 0
        for ch in text:
            cw = get_display_width(ch)
            if cur + cw > max_width - 1:
                break
            result += ch
            cur += cw
        return result + "…"

    @staticmethod
    def relative_time(published_at: str) -> str:
        """将 ISO 发布时间转为 GitHub 风格的英文相对时间（四舍五入取整）"""
        if not published_at:
            return ""
        try:
            iso = published_at[:-1] + "+00:00" if published_at.endswith("Z") else published_at
            pub = datetime.fromisoformat(iso)
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - pub).total_seconds()
            if elapsed < 60:
                return "just now"
            if elapsed < 3600:
                n = int(round(elapsed / 60))
                return f"{n} minute{'s' if n > 1 else ''} ago"
            if elapsed < 86400:
                n = int(round(elapsed / 3600))
                return f"{n} hour{'s' if n > 1 else ''} ago"
            days = elapsed / 86400
            if days < 7:
                n = int(round(days))
                return "yesterday" if n == 1 else f"{n} days ago"
            if days < 30:
                n = int(round(days / 7))
                return f"{n} week{'s' if n > 1 else ''} ago"
            if days < 365:
                n = int(round(days / 30))
                return f"{n} month{'s' if n > 1 else ''} ago"
            n = int(round(days / 365))
            return f"{n} year{'s' if n > 1 else ''} ago"
        except Exception:
            return ""

    # ── 屏幕组装 ───────────────────────────────────────
    def render(self, state: AppState) -> Group:
        return self.build_main_box(state)

    def build_main_box(self, state: AppState) -> Group:
        try:
            term_cols = shutil.get_terminal_size().columns
        except Exception:
            term_cols = self.BOX_WIDTH
        box_width = min(self.BOX_WIDTH, max(60, term_cols - 2))
        # 左右栏均强制奇数宽：保证虚线（减号+空格交替）首尾都是减号
        left_w = ((box_width - 3) // 2) | 1
        right_w = box_width - 3 - left_w
        if right_w % 2 == 0:
            right_w -= 1
        TL, TR = "╭", "╮"
        BL, BR = "╰", "╯"
        H, V = "─", "│"
        TM, BM = "┬", "┴"
        style_sel = Style(bgcolor=_SEL_BG, color=_SEL_FG, bold=True)

        try:
            term_height = shutil.get_terminal_size().lines
        except Exception:
            term_height = 24
        panel_height = max(8, term_height - 2)

        # 书页左右调换：左栏为模式导航栏 + 列表，右栏为状态区 + 日志
        left_lines = self._build_mode_list_panel(state, left_w, style_sel, panel_height)
        right_lines = self._build_status_log_panel(state, right_w, panel_height)

        lines = [Text(f"{TL}{H * left_w}{TM}{H * right_w}{TR}", style=STYLE_DEFAULT)]
        for lline, rline in zip(left_lines, right_lines):
            if isinstance(lline, tuple):
                merged = Text()
                merged.append(lline[1], style=STYLE_DEFAULT)
                merged.append_text(rline)
                rpad = right_w - get_display_width(rline.plain)
                merged.append(" " * max(0, rpad))
                merged.append(V, style=STYLE_DEFAULT)
                lines.append(merged)
            else:
                lines.append(self._merge_row(lline, rline, left_w, right_w, V))
        lines.append(Text(f"{BL}{H * left_w}{BM}{H * right_w}{BR}", style=STYLE_DEFAULT))
        return Group(*lines)

    def _merge_row(self, lline, rline, left_w, right_w, V):
        """将左右两栏内容合并为一行：│ 左内容 │ 右内容 │"""
        merged = Text()
        merged.append(V, style=STYLE_DEFAULT)
        merged.append_text(lline)
        lpad = left_w - get_display_width(lline.plain)
        merged.append(" " * max(0, lpad))
        merged.append(V, style=STYLE_DEFAULT)
        merged.append_text(rline)
        rpad = right_w - get_display_width(rline.plain)
        merged.append(" " * max(0, rpad))
        merged.append(V, style=STYLE_DEFAULT)
        return merged

    # ── 右栏：状态区 + 日志（原 _build_left_panel）────
    def _build_status_log_panel(self, state: AppState, w, panel_height):
        lines = []
        lines.extend(self._status_rows_content(state, w))
        lines.append(Text(""))
        lines.append(Text(""))
        log_rows = max(0, panel_height - len(lines))
        lines.extend(self._log_rows_content(state, w, log_rows))
        return lines

    def _status_rows_content(self, state: AppState, w):
        """构建状态区内容（项目、分支、主页、版本）"""
        lines = []
        status = state.status
        if status is None:
            lines.append(self._kv_row("项目: ", os.path.basename(self.repo_path), w, STYLE_WHITE))
            lines.append(Text(""))
            lines.append(Text(""))
            lines.append(Text(""))
            return lines
        if status["initialized"]:
            lines.append(self._kv_row("项目: ", os.path.basename(self.repo_path), w, STYLE_WHITE))
            branch_val = status["branch"]
            changes = state.changes
            if changes:
                line = Text()
                line.append(" ")
                line.append("分支: ", style=STYLE_DEFAULT)
                max_val = w - 1 - get_display_width("分支: ")
                line.append(self.truncate(branch_val, max_val), style=STYLE_WHITE)
                line.append(f" (+{changes})", style=STYLE_DEFAULT)
                lines.append(line)
            else:
                lines.append(self._kv_row("分支: ", branch_val, w, STYLE_WHITE))

            remote_raw = status["remote"]
            osc_url = self.to_https_url(remote_raw) if remote_raw != "未配置" else ""
            if remote_raw != "未配置":
                lines.append(self._kv_link_row("主页: ", osc_url, w, "#F9E2AF"))
            else:
                lines.append(self._kv_row("主页: ", "未配置", w, STYLE_DIM))

            latest_release = state.release
            if latest_release:
                tag = latest_release.get("tag") if isinstance(latest_release, dict) else latest_release
                rel_time = self.relative_time(
                    latest_release.get("published_at", "")) if isinstance(latest_release, dict) else ""
                release_url = f"{osc_url}/releases/tag/{tag}"
                label = "版本: "
                tag_max = w - 1 - get_display_width(label)
                if rel_time:
                    tag_max -= get_display_width(f" ({rel_time})")
                line = Text()
                line.append(" ")
                line.append(label, style=STYLE_DEFAULT)
                line.append(self.truncate(tag, tag_max), style=Style(link=release_url, color="#A6E3A1"))
                if rel_time:
                    line.append(f" ({rel_time})", style=STYLE_GRAY)
                lines.append(line)
            else:
                lines.append(self._kv_row("版本: ", "无", w, STYLE_DIM))
        else:
            lines.append(self._kv_row("项目: ", os.path.basename(self.repo_path), w, STYLE_WHITE))
            lines.append(Text("未初始化 Git 仓库", style=STYLE_RED))
            lines.append(Text("启动时将自动初始化", style=STYLE_DIM))
            lines.append(Text(""))
        return lines

    def _kv_row(self, label, value, w, value_style):
        """构建键值行内容（值超宽自动截断）"""
        line = Text()
        line.append(" ")
        line.append(label, style=STYLE_DEFAULT)
        max_val = w - 1 - get_display_width(label)
        line.append(self.truncate(value, max_val), style=value_style)
        return line

    def _kv_link_row(self, label, url, w, color):
        """构建带超链接的键值行内容（显示截断文本，链接指向完整 URL）"""
        line = Text()
        line.append(" ")
        line.append(label, style=STYLE_DEFAULT)
        max_val = w - 1 - get_display_width(label)
        line.append(self.truncate(url, max_val), style=Style(link=url, color=color))
        return line

    def _log_rows_content(self, state: AppState, w, count):
        """构建日志区内容（右栏底部，最多 count 行）"""
        lines = []
        logs = state.logs[-count:] if len(state.logs) > count else state.logs
        for timestamp, level, message in logs:
            label = LEVEL_LABELS.get(level, level)
            style = LEVEL_STYLES.get(level, STYLE_WHITE)
            prefix = f"[{timestamp}] "
            line = Text()
            line.append(" ")
            line.append(prefix, style=STYLE_DIM)
            line.append(f"{label} ", style=style)
            used = 1 + get_display_width(prefix) + get_display_width(f"{label} ")
            line.append(self.truncate(message, w - used))
            lines.append(line)
        while len(lines) < count:
            lines.append(Text(""))
        return lines

    # ── 左栏：模式导航 + 列表（原 _build_right_panel）──
    def _build_mode_list_panel(self, state: AppState, w, style_sel, panel_height):
        lines = []
        lines.append(self._mode_nav_row_content(state, w, style_sel))
        lines.append(Text(""))
        lines.append(Text(""))
        list_height = panel_height - 3
        lines.extend(self._list_rows_content(state, w, list_height))
        return lines

    def _mode_nav_row_content(self, state: AppState, w, style_sel):
        """构建模式选择导航栏：各模式均分宽度，选中模式整块背景高亮（无竖线分隔）"""
        names = self.mode_names or ["推送模式", "恢复模式"]
        line = Text()
        total = w
        each = total // len(names)
        for i, name in enumerate(names):
            nw = get_display_width(name)
            pad = each - nw
            pad_l = pad // 2
            pad_r = pad - pad_l
            is_sel = (i == state.mode_index)
            s = style_sel if is_sel else STYLE_DEFAULT
            line.append(" " * pad_l, style=s)
            line.append(name, style=s)
            line.append(" " * pad_r, style=s)
        return line

    def _list_rows_content(self, state: AppState, w, list_height):
        """构建列表区内容（含滚动窗口和指示器）"""
        lines = []
        if state.mode_index == 0:
            items = state.file_items
            sel_idx = state.selected_index
            show_list = state.first_sync_done
        else:
            items = state.release_items
            sel_idx = state.selected_index
            show_list = True

        if not (show_list and items):
            while len(lines) < list_height:
                lines.append(Text(""))
            return lines

        display_start = 0
        display_items = items
        show_top = False
        show_bottom = False

        if len(items) > list_height:
            half = list_height // 2
            display_start = max(0, sel_idx - half)
            end = min(len(items), display_start + list_height)
            if end == len(items):
                display_start = max(0, end - list_height)
            display_items = items[display_start:end]
            show_top = display_start > 0
            show_bottom = (display_start + len(display_items)) < len(items)

        max_name_width = 0
        for item in display_items:
            nw = get_display_width(item["name"])
            if nw > max_name_width:
                max_name_width = nw
        name_max = max(4, min(max_name_width, w - 21))

        item_rows = []
        content_width = 0
        for i, item in enumerate(display_items):
            row = self._list_item_row(state, item, display_start + i, name_max)
            item_rows.append(row)
            rw = get_display_width(row.plain)
            if rw > content_width:
                content_width = rw

        left_pad = 0
        if state.mode_index == 1:
            left_pad = max(0, (w - content_width) // 2)

        rows = []
        if show_top:
            rows.append(self._pad_row(self._scroll_indicator_content(), left_pad))
        for row in item_rows:
            rows.append(self._pad_row(row, left_pad))
        if show_bottom:
            rows.append(self._pad_row(self._scroll_indicator_content(), left_pad))

        if len(rows) > list_height:
            rows = rows[:list_height]
        while len(rows) < list_height:
            rows.append(Text(""))
        return rows

    @staticmethod
    def _pad_row(row, left_pad):
        """为行内容添加统一的左侧缩进（列表块整体居中）"""
        if left_pad <= 0:
            return row
        padded = Text()
        padded.append(" " * left_pad)
        padded.append_text(row)
        return padded

    @staticmethod
    def _scroll_indicator_content():
        line = Text()
        line.append(" ")
        line.append("...", style=STYLE_DIM)
        return line

    def _list_item_row(self, state: AppState, item, actual_index, name_max):
        """构建单个列表项内容行（推送模式文件 / 恢复模式版本）"""
        is_selected = (actual_index == state.selected_index)
        name = item["name"]
        line = Text()
        line.append(" ")

        if state.mode_index == 0:
            status_char = state.updated_items.get(name)
            if status_char == "A":
                line.append("[+]", style=STYLE_GREEN)
            elif status_char == "D":
                line.append("[-]", style=STYLE_RED)
            else:
                line.append("   ")
            line.append(" ")

        if is_selected:
            if state.mode_index == 0 and item.get("ignored", False):
                name_style = Style(bgcolor=_SEL_BG, bold=True, color=_SEL_FG, strike=True)
            else:
                name_style = STYLE_SELECTED
        elif state.mode_index == 0 and item.get("ignored", False):
            name_style = STYLE_STRIKE
        else:
            name_style = STYLE_WHITE

        display = self.truncate(name, name_max)
        line.append(display, style=name_style)
        name_pad = name_max - get_display_width(display)
        line.append(" " * name_pad, style=name_style if is_selected else None)

        action_text = item.get("action_text", "")
        if action_text:
            if is_selected and state.action_index == 1:
                if state.mode_index == 0:
                    action_color = "#40A02B" if item.get("ignored", False) else "#D20F39"
                else:
                    action_color = "#40A02B"
                line.append("  ")
                line.append(f" {action_text} ", style=Style(bgcolor=_SEL_BG, bold=True, color=action_color))
            else:
                line.append(f"   {action_text} ", style=STYLE_DIM)

        tag_text = item.get("tag_text", "")
        if tag_text:
            line.append(f" {tag_text}", style=STYLE_DIM)

        if state.mode_index == 1 and item.get("time"):
            line.append(f"  {item['time']}", style=STYLE_DIM)
        return line

