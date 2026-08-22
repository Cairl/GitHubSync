"""标签页视图协议级测试：懒加载、失效重扫、键处理、渲染。"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import i18n
i18n.LANG = "en"  # 测试固定英文输出，必须先于 import tui 模块

from tests.fakes import make_services


def test_activate_loads_once_then_cache_hits():
    from tui.view_base import ViewBase

    class Probe(ViewBase):
        id = "probe"

        def __init__(self):
            super().__init__()
            self.loads = 0

        def _load(self):
            self.loads += 1

        def render(self):
            return "x"

        def handle_key(self, key):
            return []

    v = Probe()
    v.activate()
    v.activate()
    assert v.loads == 1          # 二次切入零扫描（缓存命中）
    v.invalidate()
    v.activate()
    assert v.loads == 2          # 失效后重扫


def test_activate_retries_after_load_failure():
    """_load 异常（executor 契约降级 callback(None)）：不置 _loaded，下次 activate 自动重试。"""
    from tui.view_base import ViewBase

    class Flaky(ViewBase):
        id = "flaky"

        def __init__(self):
            super().__init__()
            self.loads = 0
            self.fail = True
            self.notified = 0
            self._on_loaded = lambda: setattr(self, "notified", self.notified + 1)

        def _load(self):
            self.loads += 1
            if self.fail:
                raise RuntimeError("boom")

        def _render(self):
            return "x"

        def handle_key(self, key):
            return []

    v = Flaky()
    v.activate()
    assert v.loads == 1
    assert v._loaded is False and v._loading is False  # 失败不缓存空数据
    assert v.notified == 1                             # on_loaded 仍触发
    v.activate()                                       # 立即重试（未缓存）
    assert v.loads == 2
    v.fail = False
    v.activate()
    assert v.loads == 3 and v._loaded is True          # 恢复后正常缓存
    v.activate()
    assert v.loads == 3                                # 缓存命中零扫描


# ── PushView ──
from core.config import KEY_DOWN, KEY_ENTER, KEY_UP
from tui.push_view import PushView


def _make_push_view(**git_kw):
    """PushView + 测试线束：get_info 用构造时 status，paint/refresh 记录调用。"""
    svc = make_services(**git_kw)
    painted: list[str] = []
    info = svc.status.get_status(fetch=False)

    def refresh(fetch: bool):
        return svc.status.get_status(fetch=fetch)

    view = PushView(svc.sync, svc.git, svc.bus, get_info=lambda: info,
                    refresh_status=refresh, paint=painted.append)
    return svc, view, painted


def test_push_view_no_porcelain_scan():
    """动作行视图：激活不触发 porcelain 扫描（无文件清单，零 I/O）。"""
    svc, view, _ = _make_push_view(initialized=True, remote="x",
                                   files={"a.py": "1"})
    base = svc.git.porcelain_calls  # 线束构造时 get_status 已计一次
    view.activate()
    view.activate()
    assert svc.git.porcelain_calls == base  # 懒加载不扫描清单
    assert "1 change(s)" in view.render()  # 空态显示变更数
    view.invalidate()
    view.activate()
    assert svc.git.porcelain_calls == base  # 失效重扫同样零扫描


def test_push_view_enter_renders_result():
    """Enter 推送：动作行显示最后结果（推送完成 N 项更改）。"""
    svc, view, _ = _make_push_view(initialized=True, remote="x",
                                   files={"a.py": "1", "b.py": "2"})
    view.activate()
    stale = view.handle_key(KEY_ENTER)
    assert stale == ["pull"]                       # 提交历史已变
    assert svc.git.commits                         # 确实提交
    assert svc.git.fetch_calls == 1                # fetch 恰好一次
    out = view.render()
    assert "✓ Push completed (2 change(s))" in out.splitlines()[0]
    assert "[OK]" not in out and "$ git" not in out  # 无命令回显


def test_push_view_session_persists_across_switch():
    """会话常驻：切出再切入，结果仍在（无结果锁定，无需重扫）。"""
    svc, view, _ = _make_push_view(initialized=True, remote="x",
                                   files={"a.py": "1"})
    view.activate()
    view.handle_key(KEY_ENTER)
    view.deactivate()
    view.activate()
    assert "Push completed (1 change(s))" in view.render()


def test_push_view_no_changes_still_syncs():
    """无结果锁定 + 无可推内容（未初始化仓库）：Enter 仍执行 sync（建仓库等）。"""
    svc, view, _ = _make_push_view(initialized=False, remote=None)
    view.activate()
    view.handle_key(KEY_ENTER)
    assert svc.git.initialized
    assert "Push completed" in view.render().splitlines()[0]


def test_push_view_failure_renders_error():
    """推送失败：动作行显示失败原因。"""
    svc, view, _ = _make_push_view(initialized=True, remote="x",
                                   files={"a.py": "1"})
    svc.git.fail_mode = "network"
    view.activate()
    view.handle_key(KEY_ENTER)
    out = view.render()
    assert "✕" in out.splitlines()[0]
    assert "Network error" in out.splitlines()[0]


def test_push_view_progress_not_rendered():
    """PROGRESS 实时进度不渲染；里程碑消息覆盖动作行。"""
    from core.events import ActionLog
    svc, view, _ = _make_push_view(initialized=True, remote="x",
                                   files={"a.py": "1"})
    view.activate()
    with view._lock:
        view._session = "running"
    svc.bus.publish(ActionLog("ACTION", "Pushing to GitHub", stage="push"))
    assert "> Pushing to GitHub" in view.render().splitlines()[0]
    svc.bus.publish(ActionLog("PROGRESS", "100% (12/12) · 1.20 MiB",
                              stage="push"))
    out = view.render()
    assert "> Pushing to GitHub" in out.splitlines()[0]  # 进度不覆盖动作行
    assert "100% (12/12) · 1.20 MiB" not in out
    svc.bus.publish(ActionLog("DONE", "Push completed (1 change(s))",
                              stage="push"))
    assert "✓ Push completed (1 change(s))" in view.render().splitlines()[0]


def test_push_view_progress_via_full_sync(tmp_path):
    """真实推送流程：进度不渲染，动作行显示最后结果。"""
    svc, view, _ = _make_push_view(initialized=True, remote="x",
                                   files={"a.py": "1", "b.py": "2"})
    svc.sync.repo_path = str(tmp_path)
    svc.release.repo_path = str(tmp_path)
    svc.git.push_progress = ["16% (1/6)", "100% (2/2) · 512 B"]   # fake 模拟 push 进度
    view.activate()
    view.handle_key(KEY_ENTER)
    out = view.render()
    assert "16% (1/6)" not in out            # 进度不占行
    assert "512 B" not in out                # 进度 detail 不渲染
    assert "✓ Push completed (2 change(s))" in out.splitlines()[0]


def test_push_view_release_stage_published(tmp_path):
    """工作区干净 + 本地 changelog 待发布：会话含 Release 阶段且 ✓。"""
    svc, view, _ = _make_push_view(initialized=True, remote="x")
    svc.sync.repo_path = str(tmp_path)
    svc.release.repo_path = str(tmp_path)  # ReleaseService 独立持有 repo_path
    svc.status.repo_path = str(tmp_path)   # StatusService 探测 release_pending 用
    (tmp_path / "changelog.md").write_text("notes", encoding="utf-8")
    view.activate()
    view.handle_key(KEY_ENTER)
    assert svc.gh.published                     # Release 确实发布
    out = view.render()
    assert "Published" in out.splitlines()[0]   # 动作行=最后结果（release 发布）


def test_push_view_single_line_layout(tmp_path):
    """单行动作行布局：行数恒定 1 + 空行占位，无阶段行。"""
    svc, view, _ = _make_push_view(initialized=True, remote="x")
    svc.sync.repo_path = str(tmp_path)
    svc.release.repo_path = str(tmp_path)
    svc.status.repo_path = str(tmp_path)
    (tmp_path / "changelog.md").write_text("   ", encoding="utf-8")  # 空白：有 release 预判但不发布
    view._max_rows = lambda: 5
    view.activate()
    view.handle_key(KEY_ENTER)
    lines = view._render_lines()
    assert len(lines) == 5                                     # 1 动作行 + 4 空行
    assert any("Push completed" in ln for ln in lines)         # 动作行=结果
    assert not any("Scan" in ln or "Commit" in ln or "Push" in ln
                   for ln in lines if "Push completed" not in ln)  # 无阶段行


def test_push_view_empty_shows_hint():
    """空会话（无变更）：无提示文字，内容为空。"""
    svc, view, _ = _make_push_view(initialized=True, remote="x")
    view.activate()
    out = view.render()
    assert out.strip() == ""                # 无变更无内容
    assert "Press Enter to push" not in out  # 无提示文字


def test_push_view_idle_shows_change_count():
    """开屏按 Enter 前显示本次变更数，无变更时不显示。"""
    # 有变更：显示 N change(s)
    svc, view, _ = _make_push_view(initialized=True, remote="x",
                                   files={"a.py": "1", "b.py": "2"})
    view.activate()
    out = view.render()
    assert "2 change(s)" in out.splitlines()[0]
    # 无变更：内容为空
    svc, view, _ = _make_push_view(initialized=True, remote="x")
    view.activate()
    out = view.render()
    assert "change(s)" not in out


def test_push_view_no_repo_idle_empty():
    """NO_REPO：空会话无内容（无变更数），不显示差异摘要。"""
    svc, view, _ = _make_push_view(initialized=False, remote=None)
    view.activate()
    out = view.render()
    assert out.strip() == ""
    assert "not a git repository" not in out


def test_push_view_idle_to_session_same_rowcount():
    """开屏一页流与会话行数一致：Enter 后走定点更新，无整屏跳变。"""
    svc, view, _ = _make_push_view(initialized=True, remote="x",
                                   files={"a.py": "1", "b.py": "2"})
    view._max_rows = lambda: 6
    view.activate()
    idle_lines = view._render_lines()          # 空态（含空行占位）
    view.handle_key(KEY_ENTER)
    session_lines = view._render_lines()
    assert len(idle_lines) == len(session_lines) == 6  # 行数恒定
    assert "2 change(s)" in idle_lines[0]   # 开屏显示变更数
    assert "Push completed" in session_lines[0]


# ── PullView ──
from tui.pull_view import PullView


def _make_pull_view(**git_kw):
    svc = make_services(**git_kw)
    view = PullView(svc.restore, svc.git, max_rows=lambda: 20)
    return svc, view


def test_pull_view_activate_loads_once():
    svc, view = _make_pull_view(initialized=True, remote="x",
                                commits=["abcdef1234567890"])
    view.activate()
    view.activate()
    assert svc.git.recent_commits_calls == 1  # 懒加载缓存
    assert "abcdef12" in view.render()


def test_pull_view_cursor_moves_and_wraps():
    svc, view = _make_pull_view(initialized=True, remote="x",
                                commits=["abcdef1234567890", "fedcba9876543210"])
    view.activate()
    assert view.handle_key(KEY_UP) == []      # 光标移动不产生失效
    assert view._index == 1                   # 上移回卷到末项
    view.handle_key(KEY_DOWN)
    assert view._index == 0


def test_pull_view_enter_first_aligns_remote():
    svc, view = _make_pull_view(initialized=True, remote="x",
                                commits=["abcdef1234567890"])
    view.activate()
    stale = view.handle_key(KEY_ENTER)
    assert stale == ["pull", "push"]          # 工作区与历史都变了
    assert svc.git.reset_to == "origin/main"
    assert svc.git.fetch_calls == 1
    assert svc.git.clean_calls == 1


def test_pull_view_enter_restores_commit():
    svc, view = _make_pull_view(initialized=True, remote="x",
                                commits=["abcdef1234567890", "fedcba9876543210"])
    view.activate()
    view.handle_key(KEY_DOWN)
    view.handle_key(KEY_ENTER)
    assert svc.git.reset_to == "abcdef1234567890"


def test_pull_view_no_commits():
    svc, view = _make_pull_view(initialized=True, remote="x", commits=[])
    view.activate()
    assert view.render() == "none"
    assert view.handle_key(KEY_ENTER) == []   # 空列表键全 no-op


def test_pull_view_remote_head_marked():
    """远程一致版本 hash 包 #ABDFA7（同 [✓]），其余不变色。"""
    svc, view = _make_pull_view(initialized=True, remote="x",
                                commits=["abcdef1234567890", "fedcba9876543210"])
    svc.git.remote_head_hash = "fedcba9876543210"
    view.activate()
    assert view._remote_head == "fedcba9876543210"
    assert "[#ABDFA7]fedcba98[/]" in view._render_label(
        "fedcba9876543210", "2026-01-01 00:00:00")
    assert "[#ABDFA7]" not in view._render_label(
        "abcdef1234567890", "2026-01-01 00:00:00")


def test_pull_view_cursor_style_aligned():
    """选中行 › + 底色框选（不加粗），未选中行 3 空格占位，文本起始列均为 3。"""
    svc, view = _make_pull_view(initialized=True, remote="x",
                                commits=["abcdef1234567890", "fedcba9876543210"])
    view.activate()
    lines = view.render().splitlines()
    assert len(lines) == 2
    assert lines[0].index("fedcba98") == 3    # 最新在前，选中
    assert lines[1].index("abcdef12") == 3
    assert "[on #636363]" not in lines[0]     # render 已转 ANSI（非 tty 纯文本）


# ── FilesView ──
from tui.files_view import FilesView


def _make_files_view(tmp_path, files=(), ignored=()):
    """files: 工作区文件名；ignored: gitignore 条目。返回 (svc, view)。"""
    for name in files:
        (tmp_path / name).write_text("x")
    svc = make_services(initialized=True, remote="x")
    svc.git.gitignore_lines = list(ignored)
    svc.file_ops.repo_path = str(tmp_path)
    return svc, FilesView(svc.file_ops)


def test_files_view_enter_toggles_and_invalidates(tmp_path):
    """Enter 对未忽略文件执行排除（加入 gitignore），返回 ["files"] 触发重扫。"""
    svc, view = _make_files_view(tmp_path, files=["a.py"])
    view.activate()
    stale = view.handle_key(KEY_ENTER)
    assert stale == ["files"]
    assert "a.py" in svc.git.gitignore_lines


def test_files_view_include_ignored(tmp_path):
    svc, view = _make_files_view(tmp_path, files=["notes.txt"],
                                 ignored=["notes.txt"])
    view.activate()
    view.handle_key(KEY_ENTER)      # 已忽略 → 推送（重新纳入同步）
    assert "notes.txt" not in svc.git.gitignore_lines


def test_files_view_failed_marker(tmp_path):
    """push 失败后 _failed 记录文件名，重扫后行首 [!]（invalidate 不清 _failed）。"""
    svc, view = _make_files_view(tmp_path, files=["notes.txt"],
                                 ignored=["notes.txt"])
    svc.git.fail_mode = "network"
    view.activate()
    view.handle_key(KEY_ENTER)
    assert "notes.txt" in view._failed
    view.invalidate()
    view.activate()                  # 动作后失效重扫（主循环语义）
    assert "[!]" in view.render()


def test_files_view_empty_shows_hint(tmp_path):
    svc, view = _make_files_view(tmp_path)
    view.activate()
    assert view.render() == "none"
    assert view.handle_key(KEY_ENTER) == []


def test_files_view_cursor_aligned(tmp_path):
    """选中行 › 前缀 + 底色框选，未选中行 3 空格占位，文本起始列均为 3。"""
    svc, view = _make_files_view(tmp_path, files=["a.py", "b.py"])
    view.activate()
    lines = view.render().splitlines()
    assert len(lines) == 2
    assert lines[0].index("a.py") == 3
    assert lines[1].index("b.py") == 3


# ── BranchView ──
from tui.branch_view import BranchView


def _make_branch_view(**git_kw):
    svc = make_services(initialized=True, remote="x", **git_kw)
    view = BranchView(svc.branch, svc.git, max_rows=lambda: 20)
    return svc, view


def test_branch_view_empty_shows_none():
    """无本地分支：分支页渲染 none 占位，键全 no-op。"""
    svc, view = _make_branch_view(branches=[])
    view.activate()
    assert view.render() == "none"
    assert view.handle_key(KEY_ENTER) == []


def test_branch_view_lazy_load():
    svc, view = _make_branch_view(branches=["main", "feature"])
    view.activate()
    view.activate()
    assert svc.git.list_branches_calls == 1   # 懒加载缓存
    view.invalidate()
    view.activate()
    assert svc.git.list_branches_calls == 2   # 失效重扫


def test_branch_view_current_highlighted():
    """当前分支名包 #ABDFA7（与 [✓] 同色），其余分支原样。"""
    svc, view = _make_branch_view(branches=["main", "feature"])
    view.activate()
    assert view._render_label("main", "main") == "[#ABDFA7]main[/]"
    assert view._render_label("feature", "feature") == "feature"


def test_branch_view_merge_row_only_off_main():
    """「合并到 main」首行仅在当前分支 ≠ main 时出现。"""
    svc, view = _make_branch_view(branches=["main", "feature"])
    view.activate()                            # 当前 main
    assert "Merge into main" not in view.render()
    svc, view = _make_branch_view(branches=["main", "feature"])
    svc.git.branch = "feature"
    view.activate()
    assert "Merge into main" in view.render()


def test_branch_view_enter_switches():
    svc, view = _make_branch_view(branches=["main", "feature"])
    view.activate()                            # 光标 0 = main
    view.handle_key(KEY_DOWN)                  # → feature
    stale = view.handle_key(KEY_ENTER)
    assert stale == ["push", "pull", "files", "branch"]
    assert svc.git.branch == "feature"


def test_branch_view_enter_current_noop():
    svc, view = _make_branch_view(branches=["main", "feature"])
    view.activate()                            # 光标在 main（当前分支）
    assert view.handle_key(KEY_ENTER) == []
    assert svc.git.switch_calls == []


def test_branch_view_dirty_blocked():
    """脏区 Enter：行标 [!] 拒绝执行，分支不变，无失效返回。"""
    svc, view = _make_branch_view(branches=["main", "feature"],
                                  files={"a.py": "1"})
    view.activate()
    view.handle_key(KEY_DOWN)
    assert view.handle_key(KEY_ENTER) == []
    assert "feature" in view._blocked
    assert svc.git.branch == "main"
    assert "[!]" in view.render()


def test_branch_view_merge_flow():
    """首行 Enter：合并到 main 并推送，返回全部视图失效。"""
    svc, view = _make_branch_view(branches=["main", "feature"])
    svc.git.branch = "feature"
    view.activate()                            # 光标 0 = 合并项
    stale = view.handle_key(KEY_ENTER)
    assert stale == ["push", "pull", "files", "branch"]
    assert svc.git.branch == "main"
    assert svc.git.merge_calls == ["feature"]


def test_branch_view_merge_conflict_marks_failed():
    """合并冲突：自动 abort + 切回原分支，首行标 [✕]。"""
    svc, view = _make_branch_view(branches=["main", "feature"])
    svc.git.branch = "feature"
    svc.git.merge_ok = False
    view.activate()
    assert view.handle_key(KEY_ENTER) == []
    assert "@merge" in view._failed
    assert svc.git.merge_abort_calls == 1
    assert svc.git.branch == "feature"
    assert "[✕]" in view.render()


def test_branch_view_cursor_aligned():
    """选中行 › + 底色框选，未选中行 3 空格占位，正常行文本起始列均为 3。"""
    svc, view = _make_branch_view(branches=["main", "feature"])
    view.activate()
    lines = view.render().splitlines()
    assert lines[0].index("main") == 3
    assert lines[1].index("feature") == 3


def test_empty_state_none_colored_gray(monkeypatch, tmp_path):
    """四个标签页空态 none 均以 #636363 灰色渲染（ANSI 38;2;99;99;99）。"""
    import tui.renderer
    monkeypatch.setattr(tui.renderer, "supports_color", lambda stream: True)
    gray = "\x1b[38;2;99;99;99m"  # #636363 占位色
    gray2 = "\x1b[38;2;139;148;158m"  # #8B949E 次要色（变更数 COLOR_GRAY）
    # 推送（空会话：变更数灰色显示）
    _, push, _ = _make_push_view(initialized=True, remote="x", files={"a.py": "1"})
    push.activate()
    assert gray2 in push.render() and "1 change(s)" in push.render()
    # 拉取（无提交历史）
    _, pull = _make_pull_view(initialized=True, remote="x", commits=[])
    pull.activate()
    assert gray in pull.render() and "none" in pull.render()
    # 文件（无文件）
    _, files = _make_files_view(tmp_path)
    files.activate()
    assert gray in files.render() and "none" in files.render()
    # 分支（无本地分支）
    _, branch = _make_branch_view(branches=[])
    branch.activate()
    assert gray in branch.render() and "none" in branch.render()



# ── loading 态（异步加载）──
class _ManualExecutor:
    """测试用可控执行器：submit 存任务不执行，run_pending 手动触发。"""

    def __init__(self):
        self._pending = []

    def submit(self, fn, callback):
        self._pending.append((fn, callback))

    def run_pending(self):
        pending, self._pending = self._pending, []
        for fn, callback in pending:
            try:
                callback(fn())
            except Exception:
                callback(None)

    def shutdown(self):
        pass


def test_view_loading_state_blank_render():
    """loading 期间 render 返回空串（留白），完成后正常渲染。"""
    from tui.pull_view import PullView
    svc = make_services(initialized=True, remote="x",
                        commits=["abcdef1234567890"])
    gate = _ManualExecutor()
    view = PullView(svc.restore, svc.git, max_rows=lambda: 20, executor=gate)
    view.activate()
    assert view.render() == ""          # loading 留白
    gate.run_pending()                  # 手动完成加载
    assert "abcdef12" in view.render()


def test_view_enter_noop_while_loading():
    """loading 期间 Enter 无效（推送页尤其不得触发空推送流程）。"""
    from tui.push_view import PushView
    svc = make_services(initialized=True, remote="x", files={"a.py": "1"})
    gate = _ManualExecutor()
    info = svc.status.get_status(fetch=False)
    view = PushView(svc.sync, svc.git, svc.bus, get_info=lambda: info,
                    refresh_status=lambda f: info, paint=lambda t: None,
                    executor=gate)
    view.activate()
    assert view.handle_key(b"\r") == []     # KEY_ENTER
    gate.run_pending()
    assert view.handle_key(b"\r") != [] or svc.git.commits  # 完成后恢复正常


def test_view_on_loaded_callback_fires():
    """加载完成触发 on_loaded 回调（主循环借此重绘内容区）。"""
    from tui.files_view import FilesView
    svc = make_services(initialized=True, remote="x")
    gate = _ManualExecutor()
    seen = []
    view = FilesView(svc.file_ops, executor=gate,
                     on_loaded=lambda: seen.append(1))
    view.activate()
    assert seen == []                   # 未完成不触发
    gate.run_pending()
    assert seen == [1]
