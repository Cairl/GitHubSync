import os
import sys
import time
import shutil
import fnmatch
import msvcrt
import threading

from rich.console import Console, Group
from rich.live import Live
from rich.text import Text
from rich.style import Style

from .config import (
    STYLE_BOLD, STYLE_DIM, STYLE_RED, STYLE_GREEN, STYLE_YELLOW,
    STYLE_BLUE, STYLE_DEFAULT, STYLE_WHITE, STYLE_STRIKE, STYLE_SELECTED,
    STYLE_LINK, STYLE_GRAY, LEVEL_STYLES, LEVEL_LABELS,
    KEY_UP, KEY_DOWN, KEY_LEFT, KEY_RIGHT, KEY_ENTER, KEY_ESC, KEY_Q, KEY_O,
    COOLDOWN_PERIOD,
)
from .utils import enable_vt100, run_command, get_key, get_display_width
from .git_manager import GitManager


class App:
    BOX_WIDTH = 101

    def __init__(self, repo_path):
        self.git = GitManager(repo_path, on_log=self._on_git_log)
        self.console = Console()
        self.running = True
        self.mode = 0                   # 0=推送模式, 1=恢复模式（默认光标在推送）
        self.mode_locked = False
        self.selected_index = 0
        self.action_index = 0
        self.file_items = []
        self.release_items = []
        self.first_sync_done = False
        self.operation_in_progress = False
        self.cooldown_until = 0
        self._cached_status = None
        self._cached_release = None
        self._cached_changes = None
        self._releases_loading = False
        self._cache_miss_sentinel = object()
        self._live = None

    @staticmethod
    def _to_https_url(remote_raw):
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

    def _on_git_log(self):
        if self._live:
            self._live.update(self.build_screen())

    def _get_status(self):
        # 纯读缓存，不触发子进程（数据由后台线程刷新），保证渲染路径零阻塞
        return self._cached_status

    def _get_release(self):
        if self._cached_release is None:
            return None
        if self._cached_release is self._cache_miss_sentinel:
            return None
        return self._cached_release

    def _get_changes(self):
        if self._cached_changes is None:
            return 0
        return self._cached_changes

    def _refresh_caches(self):
        self._cached_status = self.git.get_status()
        release = self.git.get_latest_release()
        self._cached_release = release if release is not None else self._cache_miss_sentinel
        self._cached_changes = self.git.get_change_count()

    def _try_commit(self, msg):
        """尝试 git commit。返回 (ok, msg)：
        - (True, msg): 提交成功
        - (False, None): 无需提交（nothing to commit）
        - (False, msg): 提交失败（真实错误）
        """
        s, m = run_command(["git", "commit", "-m", msg], cwd=self.git.cwd)
        if s:
            return True, m
        lower = m.lower()
        if "nothing to commit" in lower or "no changes added to commit" in lower:
            return False, None
        return False, m

    def refresh_file_list(self):
        self.file_items = []
        try:
            cwd = self.git.cwd
            items = os.listdir(cwd)
            dirs = sorted(item for item in items if item != ".git" and os.path.isdir(os.path.join(cwd, item)))
            files = sorted(item for item in items if item != ".git" and not os.path.isdir(os.path.join(cwd, item)))

            patterns, negations = self._read_gitignore()

            for name in dirs + files:
                ignored = self._is_gitignored(name, patterns, negations)
                self.file_items.append({
                    "name": name,
                    "ignored": ignored,
                    "action_text": "推送" if ignored else "删除",
                    "tag_text": "(已忽略)" if ignored else "",
                })

            if not self.file_items:
                self.file_items.append({"name": "(空目录)", "ignored": False, "action_text": "", "tag_text": ""})

            if self.selected_index >= len(self.file_items):
                self.selected_index = 0

        except Exception as e:
            self.git.log(f"刷新文件列表异常: {e}", "NOTE")

    def _read_gitignore(self):
        """简化的 .gitignore 解析（支持基本 glob 和 ! 取反，尾部空白已忽略）
        注意：不支持 ** 递归匹配、目录通配、路径模式等完整 gitignore 规范。
        仅用于 UI 显示"已忽略"标签，不影响实际 git 操作。"""
        gitignore_path = os.path.join(self.git.cwd, ".gitignore")
        if not os.path.exists(gitignore_path):
            return [], []
        patterns = []
        negations = []
        with open(gitignore_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip()  # 忽略尾部空白（gitignore 规范）
                if not line or line.startswith("#"):
                    continue
                if line.startswith("!"):
                    neg = line[1:].rstrip("/")
                    if neg:
                        negations.append(neg)
                else:
                    pat = line.rstrip("/")
                    if pat:
                        patterns.append(pat)
        return patterns, negations

    def _is_gitignored(self, name, patterns, negations):
        """检查文件名是否匹配 gitignore 规则（支持 glob 和取反）"""
        for pat in patterns:
            if fnmatch.fnmatch(name, pat):
                for neg in negations:
                    if fnmatch.fnmatch(name, neg):
                        return False
                return True
        return False

    def load_releases(self):
        commits = self.git.get_recent_commits()
        self.release_items = [
            {"name": c["hash"][:8], "time": c["time"], "action_text": "恢复"}
            for c in commits
        ] or [{"name": "(无提交)", "time": "", "action_text": ""}]

    def do_first_sync(self):
        """基本初始化：创建 .gitignore、初始化仓库、配置远程，但不执行推送"""
        self.operation_in_progress = True
        try:
            self.git.create_ignore()
            status = self.git.get_status()
            if not status["initialized"]:
                self.git.init_repo()
            status = self.git.get_status()
            if status["remote"] == "未配置":
                self.git.configure_remote()
        finally:
            self._refresh_caches()
            self.operation_in_progress = False
        self.refresh_file_list()

    def build_main_box(self):
        try:
            term_cols = shutil.get_terminal_size().columns
        except Exception:
            term_cols = self.BOX_WIDTH
        box_width = min(self.BOX_WIDTH, max(60, term_cols - 2))
        # 左右栏均强制奇数宽：保证虚线（减号+空格交替）首尾都是减号、左右各缺一格
        left_w = ((box_width - 3) // 2) | 1
        right_w = box_width - 3 - left_w
        if right_w % 2 == 0:
            right_w -= 1
        TL, TR = '╭', '╮'
        BL, BR = '╰', '╯'
        H, V = '─', '│'
        TM, BM = '┬', '┴'
        style_sel = Style(bgcolor="#CDD6F4", color="#11111B", bold=True)

        try:
            term_height = shutil.get_terminal_size().lines
        except Exception:
            term_height = 24
        panel_height = max(8, term_height - 2)

        # 书页左右调换：左栏为模式导航栏 + 列表，右栏为状态区 + 日志
        left_lines = self._build_right_panel(left_w, style_sel, panel_height)
        right_lines = self._build_left_panel(right_w, panel_height)

        lines = [Text(f"{TL}{H * left_w}{TM}{H * right_w}{TR}", style=STYLE_DEFAULT)]
        for lline, rline in zip(left_lines, right_lines):
            if isinstance(lline, tuple):
                # 完整横线行：├ ┤ 占据框左边框与中竖线位置，转角与边框衔接
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

    def _build_left_panel(self, w, panel_height):
        """构建右栏：状态区 + 两行空行 + 日志区"""
        lines = []
        lines.extend(self._status_rows_content(w))
        # 状态区与日志区之间隔两个空行
        lines.append(Text(""))
        lines.append(Text(""))
        log_rows = max(0, panel_height - len(lines))
        lines.extend(self._log_rows_content(w, log_rows))
        return lines

    def _mode_nav_row_content(self, w, style_sel):
        """构建模式选择导航栏：两个模式各占一半，选中模式整块背景高亮（无竖线分隔）"""
        line = Text()
        each = w // 2
        for i, name in enumerate(["推送模式", "恢复模式"]):
            nw = get_display_width(name)
            pad = each - nw
            pad_l = pad // 2
            pad_r = pad - pad_l
            is_sel = (i == self.mode)
            s = style_sel if is_sel else STYLE_DEFAULT
            line.append(" " * pad_l, style=s)
            line.append(name, style=s)
            line.append(" " * pad_r, style=s)
        return line

    def _status_rows_content(self, w):
        """构建状态区内容（项目、分支、主页、版本）"""
        lines = []
        status = self._get_status()
        if status is None:
            # 数据尚未加载完成：仅渲染本地可知的项目名，其余行留空（静默加载，无回显）
            lines.append(self._kv_row("项目: ", os.path.basename(self.git.cwd), w, STYLE_WHITE))
            lines.append(Text(""))
            lines.append(Text(""))
            lines.append(Text(""))
            return lines
        if status["initialized"]:
            lines.append(self._kv_row("项目: ", os.path.basename(self.git.cwd), w, STYLE_WHITE))

            # 选择模式前的变更检测（缓存于 _cached_changes），有变更时在分支后括号显示
            branch_val = status["branch"]
            changes = self._get_changes()
            if changes:
                line = Text()
                line.append(" ")
                line.append("分支: ", style=STYLE_DEFAULT)
                max_val = w - 1 - get_display_width("分支: ")
                line.append(self._truncate(branch_val, max_val), style=STYLE_WHITE)
                line.append(f" (+{changes})", style=STYLE_DEFAULT)
                lines.append(line)
            else:
                lines.append(self._kv_row("分支: ", branch_val, w, STYLE_WHITE))

            remote_raw = status["remote"]
            osc_url = App._to_https_url(remote_raw) if remote_raw != "未配置" else ""
            if remote_raw != "未配置":
                lines.append(self._kv_link_row("主页: ", osc_url, w, "#F9E2AF"))
            else:
                lines.append(self._kv_row("主页: ", "未配置", w, STYLE_DIM))

            latest_release = self._get_release()
            if latest_release:
                tag = latest_release.get("tag") if isinstance(latest_release, dict) else latest_release
                rel_time = self._relative_time(
                    latest_release.get("published_at", "")) if isinstance(latest_release, dict) else ""
                release_url = f"{osc_url}/releases/tag/{tag}"
                label = "版本: "
                tag_max = w - 1 - get_display_width(label)
                if rel_time:
                    tag_max -= get_display_width(f" ({rel_time})")
                line = Text()
                line.append(" ")
                line.append(label, style=STYLE_DEFAULT)
                line.append(self._truncate(tag, tag_max), style=Style(link=release_url, color="#A6E3A1"))
                if rel_time:
                    # 括号及相对时间用灰色显示
                    line.append(f" ({rel_time})", style=STYLE_GRAY)
                lines.append(line)
            else:
                lines.append(self._kv_row("版本: ", "无", w, STYLE_DIM))
        else:
            lines.append(self._kv_row("项目: ", os.path.basename(self.git.cwd), w, STYLE_WHITE))
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
        line.append(self._truncate(value, max_val), style=value_style)
        return line

    def _kv_link_row(self, label, url, w, color):
        """构建带超链接的键值行内容（显示截断文本，链接指向完整 URL）"""
        line = Text()
        line.append(" ")
        line.append(label, style=STYLE_DEFAULT)
        max_val = w - 1 - get_display_width(label)
        line.append(self._truncate(url, max_val), style=Style(link=url, color=color))
        return line

    @staticmethod
    def _truncate(text, max_width):
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
    def _relative_time(published_at):
        """将 ISO 发布时间转为 GitHub 风格的英文相对时间（如 3 weeks ago），按四舍五入取整"""
        if not published_at:
            return ""
        try:
            from datetime import datetime, timezone
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
                if n == 1:
                    return "yesterday"
                return f"{n} days ago"
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

    def _log_rows_content(self, w, count):
        """构建日志区内容（左栏底部，最多 count 行）"""
        lines = []
        logs = self.git.logs[-count:] if len(self.git.logs) > count else self.git.logs
        for timestamp, level, message in logs:
            label = LEVEL_LABELS.get(level, level)
            style = LEVEL_STYLES.get(level, STYLE_WHITE)
            prefix = f"[{timestamp}] "
            line = Text()
            line.append(" ")
            line.append(prefix, style=STYLE_DIM)
            line.append(f"{label} ", style=style)
            used = 1 + get_display_width(prefix) + get_display_width(f"{label} ")
            line.append(self._truncate(message, w - used))
            lines.append(line)
        while len(lines) < count:
            lines.append(Text(""))
        return lines

    def _build_right_panel(self, w, style_sel, panel_height):
        """构建右栏：模式导航栏 + 封闭横线 + 空行 + 文件/版本列表"""
        lines = []
        lines.append(self._mode_nav_row_content(w, style_sel))
        # 空行（与列表区隔开两行，无横线）
        lines.append(Text(""))
        lines.append(Text(""))
        list_height = panel_height - 3
        lines.extend(self._list_rows_content(w, list_height))
        return lines

    def _list_rows_content(self, w, list_height):
        """构建列表区内容（含滚动窗口和指示器）"""
        lines = []
        if self.mode == 0:
            items = self.file_items
            sel_idx = self.selected_index
            show_list = self.first_sync_done
        else:
            items = self.release_items
            sel_idx = self.selected_index
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

        # 先构建各列表行，计算内容最大宽度用于整体居中（保持列对齐）
        item_rows = []
        content_width = 0
        for i, item in enumerate(display_items):
            row = self._list_item_row(item, display_start + i, name_max)
            item_rows.append(row)
            rw = get_display_width(row.plain)
            if rw > content_width:
                content_width = rw

        # 推送模式保持左对齐；恢复模式列表整体居中
        left_pad = 0
        if self.mode == 1:
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

    def _scroll_indicator_content(self):
        line = Text()
        line.append(" ")
        line.append("...", style=STYLE_DIM)
        return line

    def _list_item_row(self, item, actual_index, name_max):
        """构建单个列表项内容行（推送模式文件 / 恢复模式版本）"""
        is_selected = (actual_index == self.selected_index)
        name = item["name"]
        line = Text()
        line.append(" ")

        if self.mode == 0:
            status_char = self.git.updated_items.get(name)
            if status_char == 'A':
                line.append("[+]", style=STYLE_GREEN)
            elif status_char == 'D':
                line.append("[-]", style=STYLE_RED)
            else:
                line.append("   ")
            line.append(" ")

        if is_selected:
            if self.mode == 0 and item.get("ignored", False):
                name_style = Style(bgcolor="#CDD6F4", bold=True, color="#11111B", strike=True)
            else:
                name_style = STYLE_SELECTED
        elif self.mode == 0 and item.get("ignored", False):
            name_style = STYLE_STRIKE
        else:
            name_style = STYLE_WHITE

        display = self._truncate(name, name_max)
        line.append(display, style=name_style)
        name_pad = name_max - get_display_width(display)
        line.append(" " * name_pad, style=name_style if is_selected else None)

        action_text = item.get("action_text", "")
        if action_text:
            if is_selected and self.action_index == 1:
                if self.mode == 0:
                    action_color = "#40A02B" if item.get("ignored", False) else "#D20F39"
                else:
                    action_color = "#40A02B"
                line.append("  ")
                line.append(f" {action_text} ", style=Style(
                    bgcolor="#CDD6F4", bold=True,
                    color=action_color
                ))
            else:
                line.append(f"   {action_text} ", style=STYLE_DIM)

        tag_text = item.get("tag_text", "")
        if tag_text:
            line.append(f" {tag_text}", style=STYLE_DIM)

        # 恢复模式显示 commit 时间
        if self.mode == 1 and item.get("time"):
            line.append(f"  {item['time']}", style=STYLE_DIM)
        return line

    def build_screen(self):
        return self.build_main_box()

    def handle_key(self, key):
        if self.mode == 0:
            items = self.file_items
        else:
            items = self.release_items

        if key == KEY_UP:
            if items:
                self.selected_index = (self.selected_index - 1) % len(items)
                self.action_index = 0
        elif key == KEY_DOWN:
            if items:
                self.selected_index = (self.selected_index + 1) % len(items)
                self.action_index = 0
        elif key == KEY_LEFT:
            if not self.mode_locked and self.mode != 0:
                self.mode = 0
            elif self.mode_locked and self.mode == 0:
                self.action_index = 0
        elif key == KEY_RIGHT:
            if not self.mode_locked and self.mode != 1:
                self.mode = 1
                # 光标聚焦恢复模式时即预加载提交历史（预览）
                self._ensure_releases_loaded()
            elif self.mode_locked and self.mode == 0:
                if self.file_items and self.file_items[self.selected_index]["name"] != "(空目录)":
                    self.action_index = 1
            elif self.mode == 1 and self.mode_locked:
                if self._restore_available():
                    self.action_index = 1
        elif key == KEY_ENTER:
            if not self.mode_locked:
                self.mode_locked = True
                self._on_mode_selected()
            elif self.mode == 0:
                if self.file_items and self.file_items[self.selected_index]["name"] != "(空目录)":
                    if self.action_index == 1:
                        self.execute_action()
                    else:
                        self.action_index = 1
            else:
                if self._restore_available():
                    if self.action_index == 1:
                        self.execute_restore()
                    else:
                        self.action_index = 1
        elif key == KEY_O or key == b"O":
            self.open_remote()
        elif key == KEY_Q or key == b"Q":
            self.running = False

    def _restore_available(self):
        """恢复模式列表是否可操作（排除 无提交 / 加载中 占位项）"""
        return bool(self.release_items) and self.release_items[0]["name"] not in ("(无提交)", "(加载中...)")

    def execute_action(self):
        item = self.file_items[self.selected_index]
        item_name = item["name"]
        if item_name == "(空目录)":
            return

        self.operation_in_progress = True
        try:
            if item.get("ignored", False):
                self.push_to_github(item_name)
            else:
                self.remove_from_github(item_name)
        finally:
            self._refresh_caches()
            self.operation_in_progress = False
            self.cooldown_until = time.time() + COOLDOWN_PERIOD

    def execute_restore(self):
        item = self.release_items[self.selected_index]
        commit_hash = item["name"]
        if commit_hash in ("(无提交)", "(加载中...)"):
            return

        self.operation_in_progress = True
        try:
            success = self.git.restore_to_commit(commit_hash)
            if success:
                self.first_sync_done = True
                self._refresh_caches()
                self.refresh_file_list()
        finally:
            self.operation_in_progress = False
            self.cooldown_until = time.time() + COOLDOWN_PERIOD
            self.action_index = 0

    def remove_from_github(self, item_name):
        with self.git.action(f"删除: {item_name}") as result:
            s, m = run_command(["git", "ls-files", item_name], cwd=self.git.cwd)
            if s and m.strip():
                s, m = run_command(["git", "rm", "-r", "--cached", item_name], cwd=self.git.cwd)
                if not s:
                    result.failed = True
                    result.detail = m
                    return

            self.add_to_gitignore(item_name)
            run_command(["git", "add", ".gitignore"], cwd=self.git.cwd)

            ok, m = self._try_commit(f"Delete: {item_name}")
            if not ok:
                if m:  # 真实错误
                    result.failed = True
                    result.detail = m
                return  # nothing to commit 或失败都应返回

            branch = self.git._current_branch()
            s, m = run_command(["git", "push", "origin", branch], cwd=self.git.cwd)
            if not s:
                result.failed = True
                result.detail = self.git._parse_push_error(m)

        self.refresh_file_list()
        self.git.updated_items[item_name] = 'D'

    def add_to_gitignore(self, item_name):
        gitignore_path = os.path.join(self.git.cwd, ".gitignore")
        try:
            with open(gitignore_path, "a", encoding="utf-8") as f:
                f.write(f"\n{item_name}\n")
        except Exception as e:
            self.git.log(f"添加忽略异常: {e}", "NOTE")

    def confirm_delete(self, item_name):
        path = os.path.join(self.git.cwd, item_name)
        self.git.log(f"确定删除 '{item_name}' 吗？(按回车确认，Esc/Q 取消)", "NOTE")
        if self._live:
            self._live.update(self.build_screen())

        key = get_key()
        if key == KEY_ENTER:
            with self.git.action(f"物理删除: {item_name}") as result:
                try:
                    if os.path.isdir(path):
                        shutil.rmtree(path)
                    else:
                        os.remove(path)
                    self.refresh_file_list()
                except Exception as e:
                    result.failed = True
                    result.detail = str(e)
        else:
            self.git.log("取消删除操作", "NOTE")

    def push_to_github(self, item_name):
        with self.git.action(f"推送: {item_name}") as result:
            self.remove_from_gitignore(item_name)
            run_command(["git", "add", ".gitignore"], cwd=self.git.cwd)
            run_command(["git", "add", item_name], cwd=self.git.cwd)

            ok, m = self._try_commit(f"Add: {item_name}")
            if not ok and m:  # 真实错误（nothing to commit 不算失败）
                result.failed = True
                result.detail = m
                self.refresh_file_list()
                return

            branch = self.git._current_branch()
            s, m = run_command(["git", "push", "origin", branch], cwd=self.git.cwd)
            if s:
                self.git.updated_items[item_name] = 'A'
            else:
                result.failed = True
                result.detail = self.git._parse_push_error(m)

        self.refresh_file_list()

    def remove_from_gitignore(self, item_name):
        gitignore_path = os.path.join(self.git.cwd, ".gitignore")
        try:
            with open(gitignore_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            new_lines = []
            for line in lines:
                stripped = line.rstrip()
                if not stripped or stripped.startswith("#") or stripped.startswith("!"):
                    new_lines.append(line)
                    continue
                pat = stripped.rstrip("/")
                if pat == item_name:
                    continue  # 删除匹配的行
                new_lines.append(line)
            with open(gitignore_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
        except Exception as e:
            self.git.log(f"移除忽略异常: {e}", "NOTE")

    def open_remote(self):
        import webbrowser
        status = self.git.get_status()
        if status["initialized"] and status["remote"] != "未配置":
            remote_url = self._to_https_url(status["remote"])
            with self.git.action("打开远程仓库") as result:
                result.detail = remote_url
                webbrowser.open(remote_url)
        else:
            self.git.log("未配置远程仓库", "NOTE")

    def _on_mode_selected(self):
        """模式选择后的初始化：推送模式执行 sync，恢复模式加载版本列表"""
        # 等待后台初始化线程完成，避免与同步操作并发访问仓库
        init_thread = getattr(self, "_init_thread", None)
        if init_thread and init_thread.is_alive():
            init_thread.join(timeout=30)
        if self.mode == 0:
            # 推送模式：执行完整同步
            self.operation_in_progress = True
            try:
                self.git.sync()
            finally:
                self.first_sync_done = True
                self._refresh_caches()
                self.operation_in_progress = False
                self.cooldown_until = time.time() + COOLDOWN_PERIOD
                self.refresh_file_list()
        elif self.mode == 1:
            # 恢复模式：确认时确保版本列表已加载（光标切换时已预加载则跳过）
            self._ensure_releases_loaded()

    def _ensure_releases_loaded(self):
        """确保恢复模式版本列表已加载：未加载时静默后台加载（无占位回显）"""
        if self.release_items or self._releases_loading:
            return
        self._releases_loading = True
        threading.Thread(target=self._load_releases_background, daemon=True).start()

    def _load_releases_background(self):
        """后台线程：加载 Git 提交历史，完成后自动刷新界面"""
        try:
            self.load_releases()
        finally:
            self._releases_loading = False
            if self._live:
                self._live.update(self.build_screen())

    def _init_background(self):
        """后台线程：基本初始化 + 刷新缓存 + 文件列表，不阻塞界面渲染"""
        try:
            self.do_first_sync()
        except Exception as e:
            self.git.log(f"初始化异常: {e}", "NOTE")
        finally:
            self.first_sync_done = True
            self.refresh_file_list()
            if self._live:
                self._live.update(self.build_screen())

    def run(self):
        enable_vt100()
        self.refresh_file_list()

        with Live(
            self.build_screen(),
            console=self.console,
            refresh_per_second=4,
            screen=True,
        ) as live:
            self._live = live
            live.update(self.build_screen())

            # 后台线程执行初始化与数据加载：界面先渲染框架，具体数据懒加载
            if not self.first_sync_done:
                self._init_thread = threading.Thread(target=self._init_background, daemon=True)
                self._init_thread.start()
                live.update(self.build_screen())

            while self.running:
                if msvcrt.kbhit():
                    if self.operation_in_progress or time.time() < self.cooldown_until:
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