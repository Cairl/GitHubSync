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

    view = PushView(svc.sync, svc.git, get_info=lambda: info,
                    refresh_status=refresh, paint=painted.append)
    return svc, view, painted


def test_push_view_activate_scans_once():
    svc, view, _ = _make_push_view(initialized=True, remote="x",
                                   files={"a.py": "1"})
    base = svc.git.porcelain_calls  # 线束构造时 get_status 已计一次
    view.activate()
    view.activate()
    assert svc.git.porcelain_calls == base + 1  # 懒加载：二次切入零扫描
    assert "[~] a.py" in view.render()
    view.invalidate()
    view.activate()
    assert svc.git.porcelain_calls == base + 2  # 失效后重扫


def test_push_view_enter_marks_progress_then_done():
    svc, view, painted = _make_push_view(initialized=True, remote="x",
                                         files={"a.py": "1", "b.py": "2"})
    view.activate()
    stale = view.handle_key(KEY_ENTER)
    assert stale == ["pull"]                # 提交历史已变
    assert svc.git.commits                  # 确实提交
    assert svc.git.fetch_calls == 1         # fetch 在 [·] 渲染之后恰好一次
    assert "[·]" in painted[0]              # 先渲染上传中
    assert "[✓]" in painted[-1]             # 最终完成标记
    assert view._push_result is True        # 结果锁定


def test_push_view_result_lock_blocks_rescan_until_deactivate():
    svc, view, _ = _make_push_view(initialized=True, remote="x",
                                   files={"a.py": "1"})
    view.activate()
    view.handle_key(KEY_ENTER)
    calls = svc.git.porcelain_calls
    view.activate()                         # 锁定期间不重扫
    assert svc.git.porcelain_calls == calls
    assert "[✓]" in view.render()           # 结果常驻
    view.deactivate()                       # 切出清除锁定
    view.activate()
    assert svc.git.porcelain_calls > calls  # 切入重扫
    assert "[✓]" not in view.render()


def test_push_view_empty_enter_with_result_clears():
    """结果锁定期间再按 Enter（无可推内容）：清结果，返回 ["push"]，不再 sync。"""
    svc, view, _ = _make_push_view(initialized=True, remote="x",
                                   files={"a.py": "1"})
    view.activate()
    view.handle_key(KEY_ENTER)              # 推送，锁定
    stale = view.handle_key(KEY_ENTER)      # 工作区已干净 → 空推送
    assert stale == ["push"]
    assert view._push_result is False


def test_push_view_no_changes_still_syncs():
    """无结果锁定 + 无可推内容（如未初始化仓库）：Enter 仍执行 sync（建仓库等）。"""
    svc, view, _ = _make_push_view(initialized=False, remote=None)
    view.activate()
    view.handle_key(KEY_ENTER)
    assert svc.git.initialized


def test_push_view_ahead_placeholder():
    svc, view, painted = _make_push_view(initialized=True, remote="x", ahead=1)
    view.activate()
    view.handle_key(KEY_ENTER)
    assert "1 local commit" in painted[0]


def test_push_view_ahead_clean_tree_initial_shows_files():
    """AHEAD 且工作区干净：初始渲染显示本地领先提交涉及的文件（而非一句话/空白）。"""
    svc, view, _ = _make_push_view(
        initialized=True, remote="x", ahead=1,
        ahead_diff="M\tcore/sync_service.py\nA\ttests/fakes.py")
    view.activate()
    lines = view.render().split("\n")
    assert "[~] core/sync_service.py" in lines
    assert "[+] tests/fakes.py" in lines


def test_push_view_failure_marks_error():
    svc, view, painted = _make_push_view(initialized=True, remote="x",
                                         files={"a.py": "1"})
    svc.git.fail_mode = "network"
    view.activate()
    view.handle_key(KEY_ENTER)
    assert "[✕]" in painted[-1]


def test_push_view_changelog_bottomed_with_gap():
    """changelog.md 置底且前置一空行（列表还有其他文件时）。"""
    svc, view, _ = _make_push_view(initialized=True, remote="x",
                                   files={"a.py": "1", "changelog.md": "2"})
    view.activate()
    lines = view.render().split("\n")
    assert lines[-1] == "[~] changelog.md"
    assert lines[-2] == ""                       # 与其他文件空一行
    assert "[~] a.py" in lines                   # 其余文件保持在上方


def test_push_view_changelog_alone_no_gap():
    """仅 changelog.md 一个待推文件时不插空行。"""
    svc, view, _ = _make_push_view(initialized=True, remote="x",
                                   files={"changelog.md": "1"})
    view.activate()
    assert view.render().split("\n") == ["[~] changelog.md"]


def test_push_view_changelog_bottomed_in_progress():
    """推送状态行（[·]/[✓]）同样保持 changelog.md 置底 + 空行。"""
    svc, view, painted = _make_push_view(initialized=True, remote="x",
                                         files={"a.py": "1", "changelog.md": "2"})
    view.activate()
    view.handle_key(KEY_ENTER)
    assert "[·]" in painted[0]
    final = painted[-1].split("\n")
    assert final[-1] == "[✓] changelog.md"
    assert final[-2] == ""
    assert "[✓] a.py" in final


def test_push_view_injects_local_changelog(tmp_path):
    """gitignore 隔离后 porcelain 无 changelog 行：本地存在时注入显示（置底）。"""
    svc, view, _ = _make_push_view(initialized=True, remote="x",
                                   files={"a.py": "1"})
    svc.git.gitignore_lines = ["__pycache__/", "changelog.md"]
    svc.sync.repo_path = str(tmp_path)
    (tmp_path / "changelog.md").write_text("release notes", encoding="utf-8")
    view.activate()
    lines = view.render().split("\n")
    assert lines[-1] == "[+] changelog.md"   # 注入行（A → [+]）置底
    assert lines[-2] == ""                    # 与其他文件空一行
    assert "[~] a.py" in lines


def test_push_view_clean_tree_with_changelog_can_push(tmp_path):
    """工作区干净 + 本地 changelog 待发布：列表显示 changelog，Enter 推送发布。"""
    svc, view, painted = _make_push_view(initialized=True, remote="x")
    svc.sync.repo_path = str(tmp_path)
    (tmp_path / "changelog.md").write_text("notes", encoding="utf-8")
    view.activate()
    assert view.render().split("\n")[-1] == "[+] changelog.md"
    view.handle_key(KEY_ENTER)
    assert "[✓] changelog.md" in painted[-1]
    assert view._push_result is True


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


def test_push_view_empty_clean_shows_none():
    """工作区干净、无 ahead、无 changelog：推送页渲染 none 占位。"""
    svc, view, _ = _make_push_view(initialized=True, remote="x")
    view.activate()
    assert view.render() == "none"


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
