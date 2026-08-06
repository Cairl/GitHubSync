"""表现层：AppContext —— 组合上下文。

向模式组件暴露统一访问入口（state / services / 刷新方法），
承载后台初始化线程与缓存刷新（渲染路径零子进程的原则不变）。
"""

from __future__ import annotations

import os
import threading

from ..application.file_ops_service import FileOpsService
from ..application.release_service import ReleaseService
from ..application.restore_service import RestoreService
from ..application.sync_service import SyncService
from ..domain.events import ActionLog, DomainEventBus
from ..domain.protocols import GitProvider, GitHubProvider
from ..domain.state import AppState
from .renderer import RichRenderer


class AppContext:
    def __init__(
        self,
        state: AppState,
        bus: DomainEventBus,
        git: GitProvider,
        gh: GitHubProvider,
        sync: SyncService,
        restore: RestoreService,
        release: ReleaseService,
        file_ops: FileOpsService,
        renderer: RichRenderer,
        repo_path: str,
    ):
        self.state = state
        self.bus = bus
        self.git = git
        self.gh = gh
        self.sync = sync
        self.restore = restore
        self.release = release
        self.file_ops = file_ops
        self.renderer = renderer
        self.repo_path = repo_path
        self._live = None
        self._init_thread: threading.Thread | None = None
        self._releases_loading = False

    # ── 渲染刷新（Live 注入后调用）──
    def request_refresh(self) -> None:
        if self._live is not None:
            self._live.update(self.renderer.render(self.state))

    # ── 缓存刷新（纯读，不触发子进程渲染）──
    def refresh_caches(self) -> None:
        self.state.status = self.git.get_status()
        self.state.release = self.gh.get_latest_release()
        self.state.changes = self.git.get_change_count()

    def reload_file_list(self) -> None:
        self.state.file_items = self.file_ops.refresh_file_list()
        if self.state.selected_index >= len(self.state.file_items):
            self.state.selected_index = 0

    # ── 初始化（后台线程执行，不阻塞界面渲染）──
    def do_first_sync(self) -> None:
        """基本初始化：创建 .gitignore、init、配置远程，但不执行推送"""
        self.git.create_ignore()
        status = self.git.get_status()
        if not status["initialized"]:
            self.git.init_repo()
            status = self.git.get_status()
        if status["remote"] == "未配置":
            username = self.gh.get_username()
            if username:
                url = f"https://github.com/{username}/{os.path.basename(self.repo_path)}"
                self.git.set_remote(url)
        self.refresh_caches()

    def _init_background(self) -> None:
        try:
            self.do_first_sync()
        except Exception as e:
            self.bus.publish(ActionLog("NOTE", f"初始化异常: {e}"))
        finally:
            self.state.first_sync_done = True
            self.reload_file_list()
            self.request_refresh()

    def start_background_init(self) -> None:
        self._init_thread = threading.Thread(target=self._init_background, daemon=True)
        self._init_thread.start()

    def wait_init_done(self, timeout: float = 30) -> None:
        """等待后台初始化结束（模式锁定前调用，避免与同步并发访问仓库）"""
        if self._init_thread and self._init_thread.is_alive():
            self._init_thread.join(timeout=timeout)

    # ── 恢复模式预加载 ──
    def load_releases(self) -> None:
        commits = self.git.get_recent_commits()
        self.state.release_items = [
            {"name": c["hash"][:8], "time": c["time"], "action_text": "恢复"}
            for c in commits
        ] or [{"name": "(无提交)", "time": "", "action_text": ""}]

    def ensure_releases_loaded(self) -> None:
        """静默后台加载提交历史（光标聚焦恢复模式时预加载，无占位回显）"""
        if self.state.release_items or self._releases_loading:
            return
        self._releases_loading = True
        threading.Thread(target=self._load_releases_background, daemon=True).start()

    def _load_releases_background(self) -> None:
        try:
            self.load_releases()
        finally:
            self._releases_loading = False
            self.request_refresh()

    # ── 远程仓库 ──
    def open_remote(self) -> None:
        import webbrowser

        status = self.state.status
        if status and status["initialized"] and status["remote"] != "未配置":
            webbrowser.open(RichRenderer.to_https_url(status["remote"]))
            self.bus.publish(ActionLog("ACTION", "打开远程仓库"))
        else:
            self.bus.publish(ActionLog("NOTE", "未配置远程仓库"))
