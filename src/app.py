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
    STYLE_BLUE, STYLE_DEFAULT, STYLE_WHITE, STYLE_STRIKE, STYLE_SELECTED,
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
        self.mode = 0                   # 0=推送模式, 1=恢复模式
        self.selected_index = 0
        self.action_index = 0
        self.file_items = []
        self.release_items = []
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
            self.git.log(f"刷新文件列表异常: {e}", "NOTE")

    def load_releases(self):
        self.release_items = []
        releases = self.git.get_all_releases()
        for tag in releases:
            self.release_items.append({
                "name": tag,
                "action_text": "恢复",
            })
        if not self.release_items:
            self.release_items.append({
                "name": "(无版本)",
                "action_text": "",
            })

    def do_first_sync(self):
        self.operation_in_progress = True
        self.git.sync()
        self.first_sync_done = True
        self._refresh_caches()
        self.operation_in_progress = False
        self.cooldown_until = time.time() + COOLDOWN_PERIOD
        self.refresh_file_list()
        self.deadline = time.time() + IDLE_TIMEOUT

    def build_main_box(self):
        box_width = 60
        TL, TR = '╭', '╮'
        BL, BR = '╰', '╯'
        H, V = '─', '│'
        style_sel = Style(bgcolor="#585B70", color="#CDD6F4", bold=True)

        lines = []
        lines.append(Text(f"{TL}{H * (box_width - 2)}{TR}", style=STYLE_DEFAULT))

        # ── 模式指示器 ──
        mode_names = ["推送模式", "恢复模式"]
        left_hint = "◀ "
        right_hint = " ▶"
        inner_width = box_width - 2
        left_arrow_w = get_display_width(left_hint)
        right_arrow_w = get_display_width(right_hint)
        content_w = inner_width - left_arrow_w - right_arrow_w
        each_mode_w = content_w // 2

        mode_line = Text()
        mode_line.append(V, style=STYLE_DEFAULT)
        mode_line.append(left_hint, style=STYLE_DIM)
        for i, name in enumerate(mode_names):
            w = get_display_width(name)
            pad = each_mode_w - w
            pad_l = pad // 2
            pad_r = pad - pad_l
            is_sel = (i == self.mode)
            s = style_sel if is_sel else STYLE_DEFAULT
            mode_line.append(" " * pad_l, style=s)
            mode_line.append(name, style=s)
            mode_line.append(" " * pad_r, style=s)
        mode_line.append(right_hint, style=STYLE_DIM)
        mode_line.append(V, style=STYLE_DEFAULT)
        lines.append(mode_line)

        lines.append(Text(f"├{H * (box_width - 2)}┤", style=STYLE_DEFAULT))

        # ── 状态区 ──
        status = self._get_status()
        if status["initialized"]:
            if self.mode == 0:
                status_entries = [
                    ("项目: ", STYLE_DEFAULT, os.path.basename(self.git.cwd), STYLE_WHITE),
                    ("分支: ", STYLE_DEFAULT, status["branch"], STYLE_WHITE),
                ]
            else:
                status_entries = [
                    ("项目: ", STYLE_DEFAULT, os.path.basename(self.git.cwd), STYLE_WHITE),
                ]

            remote_line = Text()
            remote_line.append("远程: ", style=STYLE_DEFAULT)
            remote_raw = status["remote"]
            if remote_raw.startswith("git@"):
                osc_url = f"https://{remote_raw[len('git@'):].replace(':', '/', 1)}"
            elif remote_raw.startswith("http"):
                osc_url = remote_raw
            else:
                osc_url = f"https://{remote_raw}"

            if remote_raw != "未配置":
                remote_line.append(remote_raw, style=Style(link=osc_url, color="#F9E2AF"))
            else:
                remote_line.append("未配置", style=STYLE_DIM)

            latest_release = self._get_release()
            version_line = Text()
            version_line.append("版本: ", style=STYLE_DEFAULT)
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

        if self.mode == 0:
            self._add_box_line(lines, version_line, box_width, V)

        # ── 计时器（仅推送模式且已同步）──
        if self.mode == 0 and self.first_sync_done and self.file_items:
            rem = max(0, min(box_width - 4, self.timeout_seconds))
            elap = (box_width - 4) - rem
            timer = Text()
            timer.append(V, style=STYLE_DEFAULT)
            timer.append(" ")
            timer.append("─" * rem, style=STYLE_DIM)
            timer.append("┄" * elap, style=STYLE_BLUE)
            timer.append(" ")
            timer.append(V, style=STYLE_DEFAULT)
            lines.append(timer)

        # ── 列表区 ──
        if self.mode == 0:
            items = self.file_items
            sel_idx = self.selected_index
            show_list = self.first_sync_done
        else:
            items = self.release_items
            sel_idx = self.selected_index
            show_list = True

        if show_list and items:
            try:
                term_height = shutil.get_terminal_size().lines
            except Exception:
                term_height = 24
            reserved = 6 + 8
            max_height = max(3, term_height - reserved)

            display_start = 0
            display_items = items
            show_top = False
            show_bottom = False

            if len(items) > max_height:
                half = max_height // 2
                display_start = max(0, sel_idx - half)
                end = min(len(items), display_start + max_height)
                if end == len(items):
                    display_start = max(0, end - max_height)
                display_items = items[display_start:end]
                show_top = display_start > 0
                show_bottom = (display_start + len(display_items)) < len(items)

            if show_top:
                ind = Text()
                ind.append(V, style=STYLE_DEFAULT)
                ind.append("    ")
                ind.append("...", style=STYLE_DIM)
                ind.append(" " * (box_width - 8 - 1))
                ind.append(V, style=STYLE_DEFAULT)
                lines.append(ind)

            max_name_width = 0
            for item in display_items:
                w = get_display_width(item["name"])
                if w > max_name_width:
                    max_name_width = w

            for i, item in enumerate(display_items):
                actual_index = display_start + i
                is_selected = (actual_index == sel_idx)
                name = item["name"]

                line = Text()
                line.append(V, style=STYLE_DEFAULT)
                line.append(" ")

                if self.mode == 0:
                    status_char = self.git.updated_items.get(name)
                    if status_char == 'A':
                        line.append("[+]", style=STYLE_GREEN)
                    elif status_char == 'D':
                        line.append("[-]", style=STYLE_RED)
                    else:
                        line.append("   ")

                if is_selected:
                    if self.mode == 0 and item.get("ignored", False):
                        name_style = Style(bgcolor="#31748F", bold=True, color="#CDD6F4", strike=True)
                    else:
                        name_style = STYLE_SELECTED
                elif self.mode == 0 and item.get("ignored", False):
                    name_style = STYLE_STRIKE
                else:
                    name_style = STYLE_WHITE
                line.append(f" {name}", style=name_style)
                name_pad = max_name_width - get_display_width(name)
                line.append(" " * name_pad, style=name_style if is_selected else None)
                line.append(" ", style=name_style if is_selected else None)

                action_text = item.get("action_text", "")
                if action_text:
                    if is_selected and self.action_index == 1:
                        if self.mode == 0:
                            action_color = STYLE_GREEN if item.get("ignored", False) else STYLE_RED
                        else:
                            action_color = STYLE_GREEN
                        line.append(f"  ")
                        line.append(f" {action_text} ", style=Style(
                            bgcolor="#31748F", bold=True,
                            color=action_color.color if action_color.color else "#CDD6F4"
                        ))
                    else:
                        line.append(f"   {action_text} ", style=STYLE_DIM)

                tag_text = item.get("tag_text", "")
                if tag_text:
                    line.append(f" {tag_text}", style=STYLE_DIM)

                visible = get_display_width(line.plain)
                padding = max(0, box_width - visible - 1)
                line.append(" " * padding)
                line.append(V, style=STYLE_DEFAULT)
                lines.append(line)

            if show_bottom:
                ind = Text()
                ind.append(V, style=STYLE_DEFAULT)
                ind.append("    ")
                ind.append("...", style=STYLE_DIM)
                ind.append(" " * (box_width - 8 - 1))
                ind.append(V, style=STYLE_DEFAULT)
                lines.append(ind)

        lines.append(Text(f"{BL}{H * (box_width - 2)}{BR}", style=STYLE_DEFAULT))
        return Group(*lines)

    def _add_box_line(self, lines, content, box_width, V):
        line = Text()
        line.append(V, style=STYLE_DEFAULT)
        line.append(" ")
        line.append_text(content)
        visible = get_display_width(line.plain)
        padding = max(0, box_width - visible - 1)
        line.append(" " * padding)
        line.append(V, style=STYLE_DEFAULT)
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

        box_lines = 2 + 4 + 1
        if self.mode == 0:
            if self.first_sync_done and self.file_items:
                box_lines += min(len(self.file_items), max(3, term_height - 14))
        else:
            if self.release_items:
                box_lines += min(len(self.release_items), max(3, term_height - 14))
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
            if self.mode != 0:
                self.mode = 0
                self.selected_index = 0
                self.action_index = 0
            else:
                self.action_index = 0
        elif key == KEY_RIGHT:
            if self.mode != 1:
                self.mode = 1
                self.selected_index = 0
                self.action_index = 0
                if not self.release_items:
                    self.load_releases()
            else:
                if self.release_items and self.release_items[0]["name"] != "(无版本)":
                    self.action_index = 1
        elif key == KEY_ENTER:
            if self.mode == 0:
                if self.file_items and self.file_items[self.selected_index]["name"] != "(空目录)":
                    if self.action_index == 1:
                        self.execute_action()
                    else:
                        self.action_index = 1
                    self.deadline = time.time() + IDLE_TIMEOUT
            else:
                if self.release_items and self.release_items[0]["name"] != "(无版本)":
                    if self.action_index == 1:
                        self.execute_restore()
                    else:
                        self.action_index = 1
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

    def execute_restore(self):
        item = self.release_items[self.selected_index]
        tag = item["name"]
        if tag == "(无版本)" or self.first_sync_done:
            return

        self.operation_in_progress = True
        try:
            success = self.git.restore_to_tag(tag)
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
            s, m = run_command(f'git ls-files "{item_name}"', cwd=self.git.cwd)
            if s and m.strip():
                s, m = run_command(f'git rm -r --cached "{item_name}"', cwd=self.git.cwd)
                if not s:
                    result.failed = True
                    result.detail = m
                    return

            self.add_to_gitignore(item_name)
            run_command('git add .gitignore', cwd=self.git.cwd)

            msg = f"Delete: {item_name}"
            s, m = run_command(f'git commit -m "{msg}"', cwd=self.git.cwd)
            if not s and "nothing to commit" not in m.lower() and "no changes added to commit" not in m.lower():
                result.failed = True
                result.detail = m
                return

            if s:
                status = self.git.get_status()
                branch = status.get("branch", "main")
                if branch == "未知" or not branch:
                    branch = "main"

                s, m = run_command(f"git push origin {branch}", cwd=self.git.cwd)
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
            run_command('git add .gitignore', cwd=self.git.cwd)
            run_command(f'git add "{item_name}"', cwd=self.git.cwd)

            msg = f"Add: {item_name}"
            s, m = run_command(f'git commit -m "{msg}"', cwd=self.git.cwd)
            if not s and "nothing to commit" not in m.lower() and "no changes added to commit" not in m.lower():
                result.failed = True
                result.detail = m
                self.refresh_file_list()
                return

            if not s:
                result.failed = True
                result.detail = "没有新文件需要推送"
                self.refresh_file_list()
                return

            status = self.git.get_status()
            branch = status.get("branch", "main")
            if branch == "未知" or not branch:
                branch = "main"

            s, m = run_command(f"git push origin {branch}", cwd=self.git.cwd)
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
            new_lines = [line for line in lines if line.strip().rstrip("/") != item_name]
            with open(gitignore_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
        except Exception as e:
            self.git.log(f"移除忽略异常: {e}", "NOTE")

    def open_remote(self):
        import webbrowser
        status = self.git.get_status()
        if status["initialized"] and status["remote"] != "未配置":
            remote_url = status["remote"]
            if not remote_url.startswith("http"):
                remote_url = f"https://{remote_url.replace('git@', '').replace(':', '/')}"
            with self.git.action("打开远程仓库") as result:
                result.detail = remote_url
                webbrowser.open(remote_url)
        else:
            self.git.log("未配置远程仓库", "NOTE")

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

            if not self.first_sync_done:
                live.update(self.build_screen())
                self.do_first_sync()
                live.update(self.build_screen())

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
