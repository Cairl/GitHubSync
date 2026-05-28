import os
import sys
import time
import shutil
import msvcrt

from rich.console import Console
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.style import Style
from rich import box

from .config import (
    STYLE_BOLD, STYLE_DIM, STYLE_RED, STYLE_GREEN, STYLE_YELLOW,
    STYLE_BLUE, STYLE_GRAY, STYLE_WHITE, STYLE_STRIKE, STYLE_SELECTED,
    STYLE_LINK, LEVEL_STYLES, LEVEL_LABELS,
    KEY_UP, KEY_DOWN, KEY_LEFT, KEY_RIGHT, KEY_ENTER, KEY_ESC, KEY_Q, KEY_O,
    IDLE_TIMEOUT, COOLDOWN_PERIOD, STATUS_PANEL_HEIGHT, LOG_PANEL_HEIGHT,
)
from .utils import enable_vt100, run_command, get_key
from .git_manager import GitManager


class App:
    def __init__(self, repo_path):
        self.git = GitManager(repo_path, on_log=self._on_git_log)
        self.console = Console()
        self.running = True
        self.selected_index = 0
        self.action_index = 0
        self.file_items = []
        self.first_sync_done = False
        self.timeout_seconds = IDLE_TIMEOUT
        self.deadline = time.time() + IDLE_TIMEOUT
        self.operation_in_progress = False
        self.cooldown_until = 0
        self._cached_status = None
        self._cached_release = None
        self._cache_miss_sentinel = object()
        self._live = None

    def _on_git_log(self):
        if self._live:
            self._live.update(self.build_screen())

    def _get_status(self):
        if self._cached_status is None:
            self._refresh_caches()
        return self._cached_status

    def _get_release(self):
        if self._cached_release is None:
            self._refresh_caches()
        if self._cached_release is self._cache_miss_sentinel:
            return None
        return self._cached_release

    def _refresh_caches(self):
        self._cached_status = self.git.get_status()
        release = self.git.get_latest_release()
        self._cached_release = release if release is not None else self._cache_miss_sentinel

    def refresh_file_list(self):
        self.file_items = []
        try:
            items = os.listdir(self.git.cwd)
            dirs = []
            files = []
            for item in items:
                if item == ".git":
                    continue
                if os.path.isdir(os.path.join(self.git.cwd, item)):
                    dirs.append(item)
                else:
                    files.append(item)

            dirs.sort()
            files.sort()

            gitignore_path = os.path.join(self.git.cwd, ".gitignore")
            ignored_items = set()
            if os.path.exists(gitignore_path):
                with open(gitignore_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            ignored_items.add(line.rstrip("/"))

            for name in dirs + files:
                ignored = name in ignored_items
                action_text = "推送" if ignored else "删除"
                tag_text = "(已忽略)" if ignored else ""
                self.file_items.append({
                    "name": name,
                    "ignored": ignored,
                    "action_text": action_text,
                    "tag_text": tag_text,
                })

            if not self.file_items:
                self.file_items.append({
                    "name": "(空目录)",
                    "ignored": False,
                    "action_text": "",
                    "tag_text": "",
                })

            if self.selected_index >= len(self.file_items):
                self.selected_index = 0

        except Exception as e:
            self.git.log(f"刷新文件列表失败: {e}", "ERROR")

    def build_status_panel(self):
        status = self._get_status()
        content = Text()

        if status["initialized"]:
            remote_raw = status["remote"]
            if remote_raw.startswith("git@"):
                osc_url = f"https://{remote_raw[len('git@'):].replace(':', '/', 1)}"
            elif remote_raw.startswith("http"):
                osc_url = remote_raw
            else:
                osc_url = f"https://{remote_raw}"

            content.append("项目: ", style=STYLE_GRAY)
            content.append(os.path.basename(self.git.cwd), style=STYLE_WHITE)
            content.append("\n")

            content.append("分支: ", style=STYLE_GRAY)
            content.append(status["branch"], style=STYLE_WHITE)
            content.append("\n")

            content.append("远程: ", style=STYLE_GRAY)
            if remote_raw != "未配置":
                content.append(remote_raw, style=Style(link=osc_url, color="#F9E2AF"))
            else:
                content.append("未配置", style=STYLE_DIM)
            content.append("\n")

            latest_release = self._get_release()
            content.append("版本: ", style=STYLE_GRAY)
            if latest_release:
                release_url = f"{osc_url}/releases/tag/{latest_release}"
                content.append(latest_release, style=Style(link=release_url, color="#A6E3A1"))
            else:
                content.append("无", style=STYLE_DIM)
        else:
            content.append("未初始化 Git 仓库", style=STYLE_RED)
            content.append("\n")
            content.append("启动时将自动初始化", style=STYLE_DIM)

        return Panel(
            content,
            title=os.path.basename(self.git.cwd),
            box=box.ROUNDED,
            border_style=STYLE_GRAY,
        )

    def build_timer_bar(self):
        try:
            width = shutil.get_terminal_size().columns
        except Exception:
            width = 80

        bar_width = width - 6
        elapsed_ratio = 1.0 - (self.timeout_seconds / IDLE_TIMEOUT)
        filled = int(bar_width * elapsed_ratio)
        empty = bar_width - filled

        bar = Text()
        bar.append("─" * filled, style=STYLE_DIM)
        bar.append("┄" * empty, style=STYLE_BLUE)
        bar.append(f" {self.timeout_seconds}s", style=STYLE_GRAY)
        return bar

    def build_file_table(self):
        if not self.file_items or self.file_items[0]["name"] == "(空目录)":
            return Text("  (空目录)", style=STYLE_GRAY)

        try:
            term_height = shutil.get_terminal_size().lines
        except Exception:
            term_height = 24

        visible_rows = max(3, term_height - STATUS_PANEL_HEIGHT - 1 - LOG_PANEL_HEIGHT - 4)

        display_start = 0
        display_items = self.file_items
        show_top_indicator = False
        show_bottom_indicator = False

        if len(self.file_items) > visible_rows:
            half = visible_rows // 2
            display_start = max(0, self.selected_index - half)
            end = min(len(self.file_items), display_start + visible_rows)
            if end == len(self.file_items):
                display_start = max(0, end - visible_rows)
            display_items = self.file_items[display_start:end]
            show_top_indicator = display_start > 0
            show_bottom_indicator = (display_start + len(display_items)) < len(self.file_items)

        table = Table(
            show_header=False,
            show_lines=False,
            box=None,
            padding=(0, 1),
            expand=True,
        )
        table.add_column("status", width=3, no_wrap=True)
        table.add_column("name", ratio=1, no_wrap=True)
        table.add_column("action", no_wrap=True)
        table.add_column("tag", no_wrap=True)

        if show_top_indicator:
            table.add_row(Text(""), Text("...", style=STYLE_DIM), Text(""), Text(""))

        for i, item in enumerate(display_items):
            actual_index = display_start + i
            is_selected = (actual_index == self.selected_index)
            name = item["name"]

            status_char = self.git.updated_items.get(name)
            if status_char == 'A':
                status_text = Text("[+]", style=STYLE_GREEN)
            elif status_char == 'D':
                status_text = Text("[-]", style=STYLE_RED)
            else:
                status_text = Text("   ")

            if is_selected:
                name_style = STYLE_SELECTED
            elif item["ignored"]:
                name_style = STYLE_STRIKE
            else:
                name_style = STYLE_WHITE

            name_text = Text(f" {name}", style=name_style)

            action_label = item["action_text"]
            if is_selected and self.action_index == 1:
                action_color = STYLE_GREEN if item["ignored"] else STYLE_RED
                action_text = Text(f" {action_label} ", style=Style(
                    bgcolor="#31748F", bold=True,
                    color=action_color.color if action_color.color else "#CDD6F4"
                ))
            else:
                action_text = Text(f" {action_label} ", style=STYLE_DIM)

            tag_text = Text(item["tag_text"], style=STYLE_DIM) if item["tag_text"] else Text("")

            table.add_row(status_text, name_text, action_text, tag_text)

        if show_bottom_indicator:
            table.add_row(Text(""), Text("...", style=STYLE_DIM), Text(""), Text(""))

        return table

    def build_log_panel(self):
        max_lines = LOG_PANEL_HEIGHT - 2
        recent_logs = self.git.logs[-max_lines:] if len(self.git.logs) > max_lines else self.git.logs

        content = Text()
        for i, (timestamp, level, message) in enumerate(recent_logs):
            if i > 0:
                content.append("\n")
            label = LEVEL_LABELS.get(level, level)
            style = LEVEL_STYLES.get(level, STYLE_WHITE)
            content.append(f"[{timestamp}] ", style=STYLE_DIM)
            content.append(f"{label} ", style=style)
            content.append(message)

        return Panel(
            content,
            title="日志",
            box=box.ROUNDED,
            border_style=STYLE_GRAY,
        )

    def build_screen(self):
        layout = Layout()
        layout.split_column(
            Layout(self.build_status_panel(), size=STATUS_PANEL_HEIGHT),
            Layout(self.build_timer_bar(), size=1),
            Layout(self.build_file_table(), ratio=1),
            Layout(self.build_log_panel(), size=LOG_PANEL_HEIGHT),
        )
        return layout

    def handle_key(self, key):
        if key == KEY_UP:
            if self.file_items:
                self.selected_index = (self.selected_index - 1) % len(self.file_items)
                self.action_index = 0
        elif key == KEY_DOWN:
            if self.file_items:
                self.selected_index = (self.selected_index + 1) % len(self.file_items)
                self.action_index = 0
        elif key == KEY_LEFT:
            self.action_index = 0
        elif key == KEY_RIGHT:
            self.action_index = 1
        elif key == KEY_ENTER:
            if self.file_items and self.file_items[self.selected_index]["name"] != "(空目录)":
                if self.action_index == 1:
                    self.execute_action()
                else:
                    self.action_index = 1
                self.deadline = time.time() + IDLE_TIMEOUT
        elif key == KEY_O or key == b"O":
            self.open_remote()

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

    def remove_from_github(self, item_name):
        self.git.log(f"正在删除: {item_name}", "INFO")

        s, m = run_command(f'git ls-files "{item_name}"', cwd=self.git.cwd)
        if s and m.strip():
            s, m = run_command(f'git rm -r --cached "{item_name}"', cwd=self.git.cwd)
            if not s:
                self.git.log(f"删除失败: {m}", "ERROR")
                return

        self.add_to_gitignore(item_name)
        run_command('git add .gitignore', cwd=self.git.cwd)

        msg = f"Delete: {item_name}"
        s, m = run_command(f'git commit -m "{msg}"', cwd=self.git.cwd)
        if not s and "nothing to commit" not in m.lower() and "no changes added to commit" not in m.lower():
            self.git.log(f"提交失败: {m}", "ERROR")
            return

        if s:
            status = self.git.get_status()
            branch = status.get("branch", "main")
            if branch == "未知" or not branch:
                branch = "main"

            s, m = run_command(f"git push origin {branch}", cwd=self.git.cwd)
            if not s:
                self.git.log(f"推送失败: {m}", "ERROR")

        self.refresh_file_list()
        self.git.updated_items[item_name] = 'D'
        self.git.log(f"删除成功: {item_name}", "SUCCESS")

    def add_to_gitignore(self, item_name):
        gitignore_path = os.path.join(self.git.cwd, ".gitignore")
        try:
            with open(gitignore_path, "a", encoding="utf-8") as f:
                f.write(f"\n{item_name}\n")
        except Exception as e:
            self.git.log(f"添加忽略失败: {e}", "ERROR")

    def confirm_delete(self, item_name):
        path = os.path.join(self.git.cwd, item_name)
        self.git.log(f"确定删除 '{item_name}' 吗？(按回车确认，Esc/Q 取消)", "WARN")
        if self._live:
            self._live.update(self.build_screen())

        key = get_key()
        if key == KEY_ENTER:
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                self.git.log(f"从本地磁盘物理删除成功: {item_name}", "SUCCESS")
                self.refresh_file_list()
            except Exception as e:
                self.git.log(f"物理删除失败: {e}", "ERROR")
        else:
            self.git.log("取消删除操作", "INFO")

    def push_to_github(self, item_name):
        self.git.log(f"正在推送: {item_name}", "INFO")

        self.remove_from_gitignore(item_name)
        run_command('git add .gitignore', cwd=self.git.cwd)
        run_command(f'git add "{item_name}"', cwd=self.git.cwd)

        msg = f"Add: {item_name}"
        s, m = run_command(f'git commit -m "{msg}"', cwd=self.git.cwd)
        if not s and "nothing to commit" not in m.lower() and "no changes added to commit" not in m.lower():
            self.git.log(f"提交失败: {m}", "ERROR")
            self.refresh_file_list()
            return

        if not s:
            self.git.log("没有新文件需要推送", "WARN")
            self.refresh_file_list()
            return

        status = self.git.get_status()
        branch = status.get("branch", "main")
        if branch == "未知" or not branch:
            branch = "main"

        s, m = run_command(f"git push origin {branch}", cwd=self.git.cwd)
        if s:
            self.git.log(f"推送成功: {item_name}", "SUCCESS")
            self.git.updated_items[item_name] = 'A'
        else:
            self.git.log(f"推送失败: {m}", "ERROR")

        self.refresh_file_list()

    def remove_from_gitignore(self, item_name):
        gitignore_path = os.path.join(self.git.cwd, ".gitignore")
        try:
            with open(gitignore_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            new_lines = [line for line in lines if line.strip().rstrip("/") != item_name]
            with open(gitignore_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
        except Exception as e:
            self.git.log(f"移除忽略失败: {e}", "ERROR")

    def open_remote(self):
        import webbrowser
        status = self.git.get_status()
        if status["initialized"] and status["remote"] != "未配置":
            remote_url = status["remote"]
            if not remote_url.startswith("http"):
                remote_url = f"https://{remote_url.replace('git@', '').replace(':', '/')}"
            webbrowser.open(remote_url)
            self.git.log(f"打开成功: {remote_url}", "SUCCESS")
        else:
            self.git.log("未配置远程仓库", "WARN")

    def run(self):
        enable_vt100()

        if not self.first_sync_done:
            self.operation_in_progress = True
            self.git.sync()
            self.first_sync_done = True
            self._refresh_caches()
            self.operation_in_progress = False
            self.cooldown_until = time.time() + COOLDOWN_PERIOD
            self.refresh_file_list()
            self.deadline = time.time() + IDLE_TIMEOUT

        with Live(
            self.build_screen(),
            console=self.console,
            refresh_per_second=4,
            screen=True,
        ) as live:
            self._live = live

            while self.running:
                if msvcrt.kbhit():
                    if self.operation_in_progress or time.time() < self.cooldown_until:
                        while msvcrt.kbhit():
                            msvcrt.getch()
                        time.sleep(0.01)
                        continue

                    key = get_key()
                    self.deadline = time.time() + IDLE_TIMEOUT
                    self.handle_key(key)
                    live.update(self.build_screen())
                else:
                    remaining = self.deadline - time.time()
                    self.timeout_seconds = max(0, round(remaining))
                    if remaining < 0:
                        self.running = False
                    live.update(self.build_screen())
                    time.sleep(0.05)

            self._live = None

        self.console.print("\n退出成功。")
