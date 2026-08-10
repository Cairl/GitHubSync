"""极简交互模式主循环：顶栏常驻 + 内容区刷新。

屏幕模型（整屏重绘）：
- 顶部常驻栏：项目·分支 / 状态详情 / 菜单 / 分隔线（render_header）；
- 内容区 = 视图块（变更列表 / diff / 文件）+ 日志块（ActionLog 追加）；
- 任何部分变化 → 清屏重绘整屏；整屏文本未变 → 零输出（无效键不刷屏）。

导航栏用 ← → 移动光标、Enter 执行选中项（推送 / 拉取 / 文件）；
Backspace 从子视图返回主屏；退出无专用按键，直接关闭终端窗口。
顶栏在每次重绘时随状态更新。
"""
from __future__ import annotations

import os
import time
import webbrowser
from typing import Callable

from core.config import (COLOR_ERROR, COLOR_GRAY, COLOR_SUCCESS, COLOR_WARN,
                         KEY_BACKSPACE, KEY_ENTER, KEY_LEFT, KEY_O,
                         KEY_RIGHT)
from core.exceptions import SyncError
from core.i18n import tr
from core.services import Services
from core.status import RepoInfo, RepoStatus
from core.utils import enable_vt100, get_key, hide_cursor, show_cursor

from .renderer import markup_to_ansi
from .screen import (MENU_ITEMS, menu_for_action, recommended_action,
                     render_header, render_menu_line, render_status_line)

# 清屏 + 光标回左上角；仅首次绘制顶栏时使用
_CLEAR_SCREEN = "\x1b[2J\x1b[H"
# 日志块上限：超出后丢弃最旧日志，防止内容撑满一屏把顶栏顶出屏幕
_MAX_LOG_LINES = 20
# 单字母状态 → 符号标记（TUI 显示用；CLI format_diff 保持字母契约不变）
_CHANGE_CN = {"A": "[+]", "M": "[~]", "D": "[-]"}
# 符号语义色：新增=成功绿 / 修改=警告黄 / 删除=错误红
_CHANGE_COLOR = {"A": COLOR_SUCCESS, "M": COLOR_WARN, "D": COLOR_ERROR}
# 推送状态符号 → 语义色：上传中=次要灰 / 完成=成功绿 / 失败=错误红
_PUSH_COLOR = {"·": COLOR_GRAY, "✓": COLOR_SUCCESS, "✕": COLOR_ERROR}


class InteractiveApp:
    """无子命令时的默认入口：See → Decide → Act → Done。

    顶栏（render_header）只绘制一次，常驻屏幕顶部不再重绘：
    - 状态详情行变化 → ANSI 定点重写顶栏第二行；
    - 菜单光标移动 → ANSI 定点重绘菜单行（_redraw_menu）；
    - 内容区（视图块 + 日志块）变化 → 光标定位内容区首行，清屏到末尾后重绘。
    """

    def __init__(self, svc: Services, repo_path: str,
                 key_source: Callable[[], bytes] = get_key,
                 out: Callable[[str], None] = print):
        self.svc = svc
        self.repo_path = repo_path
        self._key = key_source
        self._out = out
        self._project = os.path.basename(self.repo_path.rstrip("\\/")) or self.repo_path
        self._info: RepoInfo | None = None
        self._view: str | None = None   # 视图块文本；None = 待主循环按当前状态生成
        self._logs: list[str] = []      # 日志块
        self._header_shown = False      # 顶栏是否已绘制（只绘制一次）
        self._active: str | None = None  # 光标选中的菜单项 id（push/pull/files）
        self._last_active: str | None = None  # 上次渲染的选中项（菜单高亮去重）
        self._status_ansi = ""          # 当前状态行的 ANSI 文本（定点更新比对）
        self._last_content = ""         # 上次内容区文本（去重）
        self._header_rows: int | None = None  # 顶栏行数（首次绘制后固定）
        self._push_state: dict[str, str] | None = None  # {文件路径: 状态符号}
        self._push_paths: list[str] = []                 # 推送中的文件路径

    # ── 渲染 ──
    def _set_view(self, text: str | None) -> None:
        """替换视图块；传 None 表示交还主循环按当前状态重新生成。"""
        self._view = text
        self._paint()

    def _content_text(self) -> str:
        parts = []
        if self._view:
            parts.append(self._view)
        if self._logs:
            parts.append("\n".join(self._logs))
        return "\n".join(parts)

    def _header_lines(self) -> int:
        """顶栏固定行数：项目 / 分支·状态 / [主页] / 空行 / 菜单块(3行) / 空行。

        首次绘制后固定：顶栏只在启动时绘制一次，之后 remote 状态变化
        （NO_REMOTE → 已配置 / ERROR）不得改变行号，否则定点重绘错位。
        """
        if self._header_rows is not None:
            return self._header_rows
        return 8 if (self._info and self._info.remote_url) else 7

    @staticmethod
    def _terminal_width() -> int:
        try:
            return os.get_terminal_size().columns
        except OSError:
            return 80

    @staticmethod
    def _terminal_height() -> int:
        try:
            return os.get_terminal_size().lines
        except OSError:
            return 24

    def _content_rows(self) -> int:
        """内容区可用行数：终端高度 - 顶栏行数 - 余量（防输出触发终端滚动）。"""
        return max(3, self._terminal_height() - self._header_lines() - 1)

    def _render_content(self, text: str) -> None:
        """局部刷新内容区：定位到内容区首行，清除其下所有行后重绘（每行缩进 2 空格）。

        输出行数受可用高度限制：超出会触发终端滚动，把顶栏顶出屏幕，
        且每次刷新滚动累积导致列表越刷越往下走。
        """
        if text == self._last_content:
            return
        lines = text.splitlines()
        avail = self._content_rows()
        if len(lines) > avail:
            lines = lines[-avail:]  # 保留末尾（视图 + 最新日志）
        indented = "\n".join(f"  {ln}" if ln else ln for ln in lines)
        self._out(f"\x1b[{self._header_lines() + 1};1H\x1b[J{indented}")
        self._last_content = text

    def _paint(self) -> None:
        """增量刷新：顶栏只绘制一次，其后仅更新状态行/菜单高亮与内容区。"""
        if self._info is None:
            return
        content = self._content_text()
        if not self._header_shown:
            self._header_rows = self._header_lines()  # 顶栏布局以首次绘制为准
            header = markup_to_ansi(
                render_header(self._info, self._project, self._terminal_width(),
                              self._active))
            self._out(_CLEAR_SCREEN + header)
            self._header_shown = True
            self._last_active = self._active
            self._status_ansi = markup_to_ansi(f"  {render_status_line(self._info)}")
            self._render_content(content)
            return
        status = markup_to_ansi(f"  {render_status_line(self._info)}")
        if status != self._status_ansi:
            # 定点重写顶栏第二行（print 自带换行，光标落点不影响后续绝对定位）
            self._out(f"\x1b[2;1H\x1b[2K{status}")
            self._status_ansi = status
        if self._active != self._last_active:
            self._last_active = self._active
            self._redraw_menu()
        self._render_content(content)

    def _redraw_menu(self) -> None:
        """选中项变化时定点重绘菜单行（行号 = 顶栏行数 - 2）。"""
        y = self._header_lines() - 2
        line = render_menu_line(self._info, self._active, self._terminal_width())
        self._out(f"\x1b[{y};1H\x1b[2K{markup_to_ansi(line)}")

    def _diff_lines(self) -> list[str]:
        """文件级变化列表，状态用符号标记（[+]/[~]/[-]）显示，符号按语义着色。

        符号单独经 markup 着色，文件名保持纯文本（防止仓库文件名中的方括号
        被 Rich markup 误解析）。
        """
        from cli.output import format_diff
        lines = []
        for line in format_diff(self.svc.git.get_porcelain()):
            if len(line) >= 3 and line[1] == " ":
                label = _CHANGE_CN.get(line[0], line[0])
                color = _CHANGE_COLOR.get(line[0])
                if color:
                    label = markup_to_ansi(f"[{color}]{label}[/]")
                lines.append(f"{label} {line[3:]}")
            else:
                lines.append(line)
        return lines

    def _main_view(self, info: RepoInfo) -> str:
        """主屏视图块：有变更时显示文件级变化列表，干净/无仓库时留空。"""
        if info.status in (RepoStatus.CLEAN, RepoStatus.NO_REPO):
            return ""
        lines = self._diff_lines()
        return "\n".join(lines) if lines else ""

    def _render_push_lines(self) -> list[str]:
        """推送状态行：按 _push_paths + _push_state 渲染（不依赖 porcelain 实时状态）。

        符号带方括号（[·]/[✓]/[✕]），与 diff 列表 [~]/[+]/[-] 风格一致；
        方括号经反斜杠转义，防 Rich markup 误解析。
        """
        lines = []
        for path in self._push_paths:
            sym = (self._push_state or {}).get(path, "·")
            label = markup_to_ansi(f"[{_PUSH_COLOR[sym]}]\\[{sym}][/]")
            lines.append(f"{label} {path}")
        return lines

    # ── 主循环 ──
    def run(self) -> int:
        enable_vt100()
        hide_cursor()
        try:
            return self._run()
        finally:
            show_cursor()  # 无论正常退出还是异常，恢复光标避免终端光标消失

    def _run(self) -> int:
        while True:
            # 本地快速刷新（fetch=False，无网络开销；fetch 仅 Enter 动作前执行）
            info = self.svc.status.get_status(fetch=False)
            status_changed = self._info is None or info.status != self._info.status
            self._info = info
            if self._view is None or status_changed:
                self._view = self._main_view(info)
            if self._active is None:
                # 初始光标 = 推荐动作对应项，Enter 默认执行推荐动作
                self._active = menu_for_action(recommended_action(info)[0])
            self._paint()
            key = self._key()
            if key == KEY_BACKSPACE:
                if self._view is not None:
                    self._set_view(None)  # Backspace 返回主屏，视图交还主循环
            elif key == KEY_LEFT:
                self._move_cursor(-1)
            elif key == KEY_RIGHT:
                self._move_cursor(1)
            elif key == KEY_ENTER:
                # 动作前 fetch 刷新远程状态（分叉/落后检测可靠），频率低可接受
                info = self.svc.status.get_status(fetch=True)
                status_changed = info.status != self._info.status
                self._info = info
                if status_changed:
                    self._view = self._main_view(info)
                self._paint()
                self._act_menu(self._active, info)
            elif key == KEY_O:
                # 隐藏快捷键：打开远程仓库，不影响菜单光标
                self._open_remote(info)
            # 无效键：不清屏、不输出，下轮重绘内容不变则零刷新

    # ── 动作 ──
    def _move_cursor(self, delta: int) -> None:
        """← → 循环移动菜单光标（越界回卷），移动由 _paint 触发菜单重绘。"""
        if self._active is None:
            return
        idx = next(i for i, (item_id, _) in enumerate(MENU_ITEMS)
                   if item_id == self._active)
        self._active = MENU_ITEMS[(idx + delta) % len(MENU_ITEMS)][0]

    def _act_menu(self, item_id: str, info: RepoInfo) -> None:
        """执行光标选中的菜单项。"""
        if item_id == "push":
            self._push()
        elif item_id == "pull":
            # 拉取 = 选择历史 git：首项对齐远程，其余历史提交可恢复
            from .restore_view import RestoreView
            RestoreView(self.svc.restore, self.svc.git, self._key, self._out,
                        render_body=self._set_view,
                        max_rows=self._content_rows()).run()
        elif item_id == "files":
            from .files_view import FilesView
            FilesView(self.svc.file_ops, self._key, self._out,
                      render_body=self._set_view).run()

    def _push(self) -> None:
        from cli.output import format_diff
        paths = [line[3:] for line in format_diff(self.svc.git.get_porcelain())
                 if len(line) >= 3 and line[1] == " "]
        if paths:
            self._push_paths = paths
            self._push_state = {p: "·" for p in paths}
            self._view = "\n".join(self._render_push_lines())
            self._paint()  # 界面显示全部 [·]（上传中）
        try:
            self.svc.sync.run()
            if paths:
                self._push_state = {p: "✓" for p in paths}
        except SyncError:
            if paths:
                self._push_state = {p: "✕" for p in paths}
        if paths:
            self._view = "\n".join(self._render_push_lines())
            self._paint()  # 显示 [✓] / [✕]
            time.sleep(1)  # 停留 1 秒让用户看清结果
            self._push_state = None
            self._push_paths = []

    def _open_remote(self, info: RepoInfo) -> None:
        if info.remote_url:
            webbrowser.open(info.remote_url)
            self._logs.append(tr(f"> 已打开 {info.remote_url}",
                                 f"> Opened {info.remote_url}"))
        else:
            self._logs.append(tr("> 未配置远程仓库", "> No remote configured"))
        self._paint()
