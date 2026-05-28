import os
import sys
import time
import shutil
import msvcrt

from rich.console import Console, Group
from rich.live import Live
from rich.text import Text
from rich.style import Style

from .config import (
    STYLE_BOLD, STYLE_DIM, STYLE_RED, STYLE_GREEN, STYLE_YELLOW,
    STYLE_BLUE, STYLE_GRAY, STYLE_WHITE, STYLE_STRIKE, STYLE_SELECTED,
    STYLE_LINK, LEVEL_STYLES, LEVEL_LABELS,
    KEY_UP, KEY_DOWN, KEY_LEFT, KEY_RIGHT, KEY_ENTER, KEY_ESC, KEY_Q, KEY_O,
    IDLE_TIMEOUT, COOLDOWN_PERIOD, STATUS_PANEL_HEIGHT, LOG_PANEL_HEIGHT,
)
from .utils import enable_vt100, run_command, get_key, get_display_width
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

    def build_main_box(self):
        box_width = 60
        TL, TR = '╭', '╮'
        BL, BR = '╰', '╯'
        H, V = '─', '│'

        lines = []
        lines.append(Text(f"{TL}{H * (box_width - 2)}{TR}", style=STYLE_GRAY))

        status = self._get_status()
        if status["initialized"]:
            remote_raw = status["remote"]
            if remote_raw.startswith("git@"):
                osc_url = f"https://{remote_raw[len('git@'):].replace(':', '/', 1)}"
            elif remote_raw.startswith("http"):
                osc_url = remote_raw
            else:
                osc_url = f"https://{remote_raw}"

            status_entries = [
                ("项目: ", STYLE_GRAY, os.path.basename(self.git.cwd), STYLE_WHITE),
                ("分支: ", STYLE_GRAY, status["branch"], STYLE_WHITE),
            ]

            remote_line = Text()
            remote_line.append("远程: ", style=STYLE_GRAY)
            if remote_raw != "未配置":
                remote_line.append(remote_raw, style=Style(link=osc_url, color="#F9E2AF"))
            else:
                remote_line.append("未配置", style=STYLE_DIM)

            latest_release = self._get_release()
            version_line = Text()
            version_line.append("版本: ", style=STYLE_GRAY)
            if latest_release:
                release_url = f"{osc_url}/releases/tag/{latest_release}"
                version_line.append(latest_release, style=Style(link=release_url, color="#A6E3A1"))
            else:
                version_line.append("无", style=STYLE_DIM)
        else:
            status_entries = []
            remote_line = Text("未初始化 Git 仓库", style=STYLE_RED)
            version_line = Text("启动时将自动初始化", style=STYLE_DIM)

        for label, label_style, value, value_style in status_entries:
            line = Text()
            line.append(label, style=label_style)
            line.append(value, style=value_style)
            self._add_box_line(lines, line, box_width, V)

        self._add_box_line(lines, remote_line, box_width, V)
        self._add_box_line(lines, version_line, box_width, V)

        if self.first_sync_done and self.file_items:
            rem = max(0, min(box_width - 4, self.timeout_seconds))
            elap = (box_width - 4) - rem
            timer = Text()
            timer.append(V, style=STYLE_GRAY)
            timer.append(" ")
            timer.append("─" * rem, style=STYLE_DIM)
            timer.append("┄" * elap, style=STYLE_BLUE)
            timer.append(" ")
            timer.append(V, style=STYLE_GRAY)
            lines.append(timer)

            try:
                term_height = shutil.get_terminal_size().lines
            except Exception:
                term_height = 24
            reserved = 6 + 8
            max_file_height = max(3, term_height - reserved)

            display_start = 0
            display_items = self.file_items
            show_top = False
            show_bottom = False

            if len(self.file_items) > max_file_height:
                half = max_file_height // 2
                display_start = max(0, self.selected_index - half)
                end = min(len(self.file_items), display_start + max_file_height)
                if end == len(self.file_items):
                    display_start = max(0, end - max_file_height)
                display_items = self.file_items[display_start:end]
                show_top = display_start > 0
                show_bottom = (display_start + len(display_items)) < len(self.file_items)

            if show_top:
                ind = Text()
                ind.append(V, style=STYLE_GRAY)
                ind.append("    ")
                ind.append("...", style=STYLE_DIM)
                ind.append(" " * (box_width - 8 - 1))
                ind.append(V, style=STYLE_GRAY)
                lines.append(ind)

            max_name_width = 0
            for item in display_items:
                w = get_display_width(item["name"])
                if w > max_name_width:
                    max_name_width = w

            for i, item in enumerate(display_items):
                actual_index = display_start + i
                is_selected = (actual_index == self.selected_index)
                name = item["name"]

                line = Text()
                line.append(V, style=STYLE_GRAY)
                line.append(" ")

                status_char = self.git.updated_items.get(name)
                if status_char == 'A':
                    line.append("[+]", style=STYLE_GREEN)
                elif status_char == 'D':
                    line.append("[-]", style=STYLE_RED)
                else:
                    line.append("   ")

                name_style = STYLE_SELECTED if is_selected else (STYLE_STRIKE if item["ignored"] else STYLE_WHITE)
                line.append(f" {name}", style=name_style)
                name_pad = max_name_width - get_display_width(name)
                line.append(" " * name_pad)

                if is_selected and self.action_index == 1:
                    action_color = STYLE_GREEN if item["ignored"] else STYLE_RED
                    line.append(f"  ")
                    line.append(f" {item['action_text']} ", style=Style(
                        bgcolor="#31748F", bold=True,
                        color=action_color.color if action_color.color else "#CDD6F4"
                    ))
                else:
                    line.append(f"   {item['action_text']} ", style=STYLE_DIM)

                if item["tag_text"]:
                    line.append(f" {item['tag_text']}", style=STYLE_DIM)

                visible = 1 + 1 + 3 + 1 + 1 + max_name_width
                if is_selected and self.action_index == 1:
                    visible += 2 + 1 + get_display_width(item["action_text"]) + 1
                else:
                    visible += 3 + get_display_width(item["action_text"]) + 1
                if item["tag_text"]:
                    visible += 1 + get_display_width(item["tag_text"])
                padding = max(0, box_width - visible - 1)
                line.append(" " * padding)
                line.append(V, style=STYLE_GRAY)
                lines.append(line)

            if show_bottom:
                ind = Text()
                ind.append(V, style=STYLE_GRAY)
                ind.append("    ")
                ind.append("...", style=STYLE_DIM)
                ind.append(" " * (box_width - 8 - 1))
                ind.append(V, style=STYLE_GRAY)
                lines.append(ind)

        lines.append(Text(f"{BL}{H * (box_width - 2)}{BR}", style=STYLE_GRAY))
        return Group(*lines)

    def _add_box_line(self, lines, content, box_width, V):
        line = Text()
        line.append(V, style=STYLE_GRAY)
        line.append(" ")
        line.append_text(content)
        visible = 1 + 1 + get_display_width(content.plain)
        padding = max(0, box_width - visible - 1)
        line.append(" " * padding)
        line.append(V, style=STYLE_GRAY)
        lines.append(line)

    def build_log_text(self):
        try:
            term_width = shutil.get_terminal_size().columns
        except Exception:
            term_width = 80

        try:
            term_height = shutil.get_terminal_size().lines
        except Exception:
            term_height = 24

        status = self._get_status()
        box_lines = 2 + 4 + 1
        if self.first_sync_done and self.file_items:
            box_lines += min(len(self.file_items), max(3, term_height - 14))
        available = max(1, term_height - box_lines - 2)

        recent = self.git.logs[-available:] if len(self.git.logs) > available else self.git.logs

        content = Text()
        for i, (timestamp, level, message) in enumerate(recent):
            if i > 0:
                content.append("\n")
            label = LEVEL_LABELS.get(level, level)
            style = LEVEL_STYLES.get(level, STYLE_WHITE)
            content.append(f" [{timestamp}] ", style=STYLE_DIM)
            content.append(f"{label} ", style=style)
            content.append(message)
        return content

    def build_screen(self):
        parts = [self.build_main_box()]
        log_text = self.build_log_text()
        if log_text.plain:
            parts.append(Text(""))
            parts.append(log_text)
        return Group(*parts)

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
