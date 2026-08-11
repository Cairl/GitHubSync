"""极简交互模式主循环：顶栏常驻 + 内容区刷新 + 标签页单循环派发。

导航栏即标签栏：←/→ 直接切换标签页并即时显示内容（免 Enter）；
↑/↓/Enter 转发当前标签视图（ViewBase.handle_key）；o 打开远程仓库；
Backspace/Esc 与其余键均为无效键（零输出）。退出无专用按键，直接关窗口。

屏幕模型：
- 顶部常驻栏：项目·分支 / 状态详情 / 菜单 / 分隔线（render_header）只绘一次；
- 状态行变化 → ANSI 定点重写顶栏第二行；菜单变化 → _redraw_menu 定点重绘；
- 内容区 = 当前标签视图块 + 日志块，变化才刷新，未变零输出（无效键不刷屏）。
"""
from __future__ import annotations

import os
import sys
import time
import webbrowser
from typing import Callable

from core.config import (KEY_DOWN, KEY_ENTER, KEY_LEFT, KEY_O, KEY_RIGHT,
                         KEY_UP)
from core.i18n import tr
from core.services import Services
from core.status import RepoInfo
from core.ansi import supports_color
from core.utils import get_key, hide_cursor, show_cursor

from .branch_view import BranchView
from .files_view import FilesView
from .pull_view import PullView
from .push_view import PushView
from .renderer import markup_to_ansi
from .screen import (MENU_ITEMS, menu_for_action, recommended_action,
                     render_header, render_menu_line, render_status_line)
from .view_base import ViewBase

# 清屏 + 光标回左上角；仅首次绘制顶栏时使用
_CLEAR_SCREEN = "\x1b[2J\x1b[H"
# 日志块上限：超出后丢弃最旧日志，防止内容撑满一屏把顶栏顶出屏幕
_MAX_LOG_LINES = 20


class InteractiveApp:
    """无子命令时的默认入口：标签页单循环（推送 / 拉取 / 文件 / 分支）。

    顶栏（render_header）只绘制一次，常驻屏幕顶部不再重绘：
    - 状态详情行变化 → ANSI 定点重写顶栏第二行；
    - 标签切换/同步标记增减 → ANSI 定点重绘菜单行（_redraw_menu）；
    - 内容区（当前标签视图 + 日志块）变化 → 光标定位内容区首行，清屏到末尾后重绘。

    视图数据懒加载：视图实例启动即构造但不扫描，首次 activate（切入）才加载；
    状态签名（status/change_count/ahead/behind）变化时推送与拉取视图失效，
    当前视图立即重扫，其余视图下次切入重扫。
    """

    def __init__(self, svc: Services, repo_path: str,
                 key_source: Callable[[], bytes] = get_key,
                 out: Callable[[str], None] = print,
                 cooldown: float = 1.0):
        self.svc = svc
        self.repo_path = repo_path
        self._key = key_source
        self._out = out
        self._cooldown = cooldown      # 动作执行后的 Enter 冷却期（秒），防连按
        self._last_action = 0.0        # 上次动作时间戳（time.monotonic）
        self._project = os.path.basename(self.repo_path.rstrip("\\/")) or self.repo_path
        self._info: RepoInfo | None = None
        self._view: str = ""              # 内容区视图块文本（当前标签 render 结果）
        self._logs: list[str] = []        # 日志块
        self._header_shown = False        # 顶栏是否已绘制（只绘制一次）
        self._active: str | None = None   # 当前标签 id（push/pull/files）
        self._last_menu_markup = ""  # 上次菜单行源 markup（去重：切换或同步标记增减）
        self._status_ansi = ""          # 当前状态行的 ANSI 文本（定点更新比对）
        self._last_content = ""         # 上次内容区文本（去重）
        self._header_rows: int | None = None  # 顶栏行数（首次绘制后固定）
        self._last_sig: tuple | None = None   # 状态签名（status/count/ahead/behind）
        # 视图注册表：构造即建（零扫描），数据懒加载在 activate
        self._views: dict[str, ViewBase] = {
            "push": PushView(svc.sync, svc.git,
                             get_info=lambda: self._info,
                             refresh_status=self._refresh_status,
                             paint=self._set_view),
            "pull": PullView(svc.restore, svc.git, max_rows=self._content_rows),
            "files": FilesView(svc.file_ops),
            "branch": BranchView(svc.branch, svc.git,
                                 max_rows=self._content_rows),
        }

    # ── 渲染 ──
    def _set_view(self, text: str) -> None:
        """替换内容区视图块文本并触发增量重绘。"""
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
            self._last_menu_markup = render_menu_line(
                self._info, self._active, self._terminal_width())
            self._status_ansi = markup_to_ansi(f"  {render_status_line(self._info)}")
            self._render_content(content)
            return
        status = markup_to_ansi(f"  {render_status_line(self._info)}")
        if status != self._status_ansi:
            # 定点重写顶栏第二行（print 自带换行，光标落点不影响后续绝对定位）
            self._out(f"\x1b[2;1H\x1b[2K{status}")
            self._status_ansi = status
        self._redraw_menu()  # 菜单变化（标签切换 / 同步标记 * 增减）才实际输出
        self._render_content(content)

    def _redraw_menu(self) -> None:
        """菜单行定点重绘（行号 = 顶栏行数 - 2）；源 markup 未变（如无效键）则零输出。

        用源 markup（含样式标签）而非 ANSI 比对：非 tty 下 ANSI 无颜色码，
        选中/未选中差异会丢失，导致标签切换被误判为无变化。
        """
        y = self._header_lines() - 2
        line = render_menu_line(self._info, self._active, self._terminal_width())
        if line == self._last_menu_markup:
            return
        self._last_menu_markup = line
        self._out(f"\x1b[{y};1H\x1b[2K{markup_to_ansi(line)}")

    # ── 主循环 ──
    def run(self) -> int:
        # 启动即启用 VT100（ctypes 实现，零子进程；渲染路径另有惰性兜底）
        supports_color(sys.stdout)
        hide_cursor()
        try:
            return self._run()
        finally:
            show_cursor()  # 无论正常退出还是异常，恢复光标避免终端光标消失

    def _run(self) -> int:
        while True:
            # 本地快速刷新（fetch=False，无网络开销；fetch 仅推送流程内执行）
            info = self.svc.status.get_status(fetch=False)
            self._info = info
            sig = (info.status, info.change_count, info.ahead, info.behind)
            sig_changed = sig != self._last_sig
            self._last_sig = sig
            if sig_changed:
                # 工作区/远程状态变化：推送与拉取数据可能过期
                # （推送结果锁定期间 PushView.activate 内部豁免重扫）
                self._views["push"].invalidate()
                self._views["pull"].invalidate()
            if self._active is None:
                # 初始标签 = 推荐动作落点，切入即显示内容
                self._active = menu_for_action(recommended_action(info)[0])
                self._current().activate()
            elif sig_changed:
                self._current().activate()  # 缓存命中零开销
            self._set_view(self._current().render())
            key = self._key()
            if key == KEY_LEFT:
                self._switch(-1)
            elif key == KEY_RIGHT:
                self._switch(1)
            elif key == KEY_O:
                # 隐藏快捷键：打开远程仓库，不影响标签选择
                self._open_remote(info)
            elif key in (KEY_UP, KEY_DOWN, KEY_ENTER):
                if key == KEY_ENTER and \
                        time.monotonic() - self._last_action < self._cooldown:
                    continue  # 冷却期内吞掉 Enter，防连按重复执行危险动作
                view = self._current()
                stale = view.handle_key(key)
                for vid in stale:
                    self._views[vid].invalidate()
                if self._active in stale:
                    view.activate()  # 当前视图数据过期：立即重扫
                self._set_view(view.render())
                if key == KEY_ENTER and stale:
                    self._last_action = time.monotonic()
            # 其余键（含 Backspace/Esc）：无效键，零输出

    # ── 标签与动作 ──
    def _current(self) -> ViewBase:
        return self._views[self._active]

    def _switch(self, delta: int) -> None:
        """←/→ 循环切换标签：切出 deactivate（PushView 清结果锁定），切入 activate 即显。"""
        old = self._current()
        idx = next(i for i, (item_id, _) in enumerate(MENU_ITEMS)
                   if item_id == self._active)
        self._active = MENU_ITEMS[(idx + delta) % len(MENU_ITEMS)][0]
        old.deactivate()
        view = self._current()
        view.activate()
        self._set_view(view.render())

    def _refresh_status(self, fetch: bool) -> RepoInfo:
        """推送流程内刷新状态（fetch=True）并立即重绘顶栏。"""
        info = self.svc.status.get_status(fetch=fetch)
        self._info = info
        self._paint()
        return info

    def _open_remote(self, info: RepoInfo) -> None:
        if info.remote_url:
            webbrowser.open(info.remote_url)
            self._logs.append(tr(f"> 已打开 {info.remote_url}",
                                 f"> Opened {info.remote_url}"))
        else:
            self._logs.append(tr("> 未配置远程仓库", "> No remote configured"))
        self._paint()
