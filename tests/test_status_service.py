"""StatusService 与状态模型测试：8 种状态判定矩阵 + porcelain 解析。"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.status import RepoStatus, decide_status, parse_porcelain


# ── porcelain 解析 ──
def test_parse_porcelain_counts():
    out = " M src/main.py\nM  README.md\nA  new.py\n?? foo.txt\n D old.py\nR  a.py -> b.py\n"
    assert parse_porcelain(out) == (2, 3, 1)  # A+?? / M+M+R / D


def test_parse_porcelain_empty():
    assert parse_porcelain("") == (0, 0, 0)


def test_decide_status_matrix():
    assert decide_status(ahead=1, behind=1, changes=0) == RepoStatus.DIVERGED
    assert decide_status(ahead=0, behind=2, changes=3) == RepoStatus.BEHIND
    assert decide_status(ahead=2, behind=0, changes=3) == RepoStatus.AHEAD
    assert decide_status(ahead=0, behind=0, changes=1) == RepoStatus.CHANGED
    assert decide_status(ahead=0, behind=0, changes=0) == RepoStatus.CLEAN


# ── StatusService 状态判定 ──
from core.status_service import StatusService
from tests.fakes import FakeGitProvider


def _svc(g):
    return StatusService(g, "fake_repo")


def test_status_no_repo():
    g = FakeGitProvider()
    assert _svc(g).get_status().status == RepoStatus.NO_REPO


def test_status_release_pending_with_changelog(tmp_path):
    """本地存在非空 changelog.md：release_pending 为真（状态仍 CLEAN）。"""
    g = FakeGitProvider()
    g.init_repo()
    g.remote = "https://github.com/octocat/repo"
    (tmp_path / "changelog.md").write_text("notes", encoding="utf-8")
    info = StatusService(g, str(tmp_path)).get_status(fetch=False)
    assert info.release_pending is True
    assert info.status == RepoStatus.CLEAN


def test_status_release_not_pending_without_changelog(tmp_path):
    g = FakeGitProvider()
    g.init_repo()
    g.remote = "https://github.com/octocat/repo"
    info = StatusService(g, str(tmp_path)).get_status(fetch=False)
    assert info.release_pending is False


def test_status_release_not_pending_empty_changelog(tmp_path):
    """空 changelog.md（0 字节）不算待发布：与 maybe_publish 触发条件一致。"""
    g = FakeGitProvider()
    g.init_repo()
    g.remote = "https://github.com/octocat/repo"
    (tmp_path / "changelog.md").write_text("", encoding="utf-8")
    info = StatusService(g, str(tmp_path)).get_status(fetch=False)
    assert info.release_pending is False


def test_status_no_remote():
    g = FakeGitProvider()
    g.initialized = True
    info = _svc(g).get_status()
    assert info.status == RepoStatus.NO_REMOTE and info.branch == "main"


def test_status_clean():
    g = FakeGitProvider()
    g.initialized = True
    g.set_remote("https://github.com/o/r")
    info = _svc(g).get_status()
    assert info.status == RepoStatus.CLEAN
    assert info.remote_url == "https://github.com/o/r"
    assert g.fetch_calls == 1


def test_status_changed():
    g = FakeGitProvider()
    g.initialized = True
    g.set_remote("https://github.com/o/r")
    g.files = {"a.py": "x", "b.py": "y"}
    info = _svc(g).get_status()
    assert info.status == RepoStatus.CHANGED
    assert info.change_count == 2 and info.modified == 2


def test_status_diverged_and_ahead_behind():
    g = FakeGitProvider()
    g.initialized = True
    g.set_remote("https://github.com/o/r")
    g.ahead, g.behind = 3, 1
    info = _svc(g).get_status()
    assert info.status == RepoStatus.DIVERGED and info.ahead == 3 and info.behind == 1
    g.behind = 0
    assert _svc(g).get_status().status == RepoStatus.AHEAD
    g.ahead, g.behind = 0, 2
    assert _svc(g).get_status().status == RepoStatus.BEHIND


def test_status_fetch_failure_degrades_gracefully():
    g = FakeGitProvider()
    g.initialized = True
    g.set_remote("https://github.com/o/r")
    g.fetch_ok = False
    assert _svc(g).get_status().status == RepoStatus.CLEAN  # 降级为本地状态


def test_status_error_capture():
    class Boom(FakeGitProvider):
        def get_porcelain(self):
            raise RuntimeError("boom")

    g = Boom()
    g.initialized = True
    g.set_remote("x")
    info = _svc(g).get_status()
    assert info.status == RepoStatus.ERROR and "boom" in info.error


def test_status_parallel_matches_sequential(tmp_path):
    """并行路径结果与串行一致：ahead/behind/porcelain/remote/fetch 全部正确组合。"""
    g = FakeGitProvider()
    g.initialized = True
    g.set_remote("https://github.com/o/r")
    g.ahead, g.behind = 2, 1
    g.files = {"a.txt": "1"}
    info = StatusService(g, str(tmp_path)).get_status(fetch=True)
    assert info.status == RepoStatus.DIVERGED
    assert (info.ahead, info.behind) == (2, 1)
    assert info.remote_url == "https://github.com/o/r"
    assert info.modified == 1
    assert g.fetch_calls == 1


def test_status_parallel_no_remote_skips_fetch():
    """无远程：NO_REMOTE 早退，fetch 虽并行提交但失败静默（不影响判定）。"""
    g = FakeGitProvider()
    g.initialized = True
    info = _svc(g).get_status(fetch=True)
    assert info.status == RepoStatus.NO_REMOTE
    assert info.remote_url is None


def test_status_ahead_behind_reflects_post_fetch_refs():
    """fetch 更新 refs 后 ahead/behind 必须取新值：ab 调用发生在 fetch 之后。

    Fake 的 fetch() 模拟"拉进远程新提交"（ahead/behind 在 fetch 末尾才变化）；
    若实现把 ahead_behind_upstream 与 fetch 同波并行，rev-list 会读到旧 refs，
    该报 BEHIND 的报成 CLEAN（CLI 退出码 2 → 0）。
    """
    class OrderGit(FakeGitProvider):
        def __init__(self):
            super().__init__()
            self.calls = []

        def fetch(self):
            self.calls.append("fetch")
            self.ahead, self.behind = 0, 2  # fetch 末尾 refs 更新：落后 2
            return True

        def ahead_behind_upstream(self):
            self.calls.append("ab")
            return super().ahead_behind_upstream()

    g = OrderGit()
    g.initialized = True
    g.set_remote("https://github.com/o/r")
    info = _svc(g).get_status(fetch=True)
    assert (info.ahead, info.behind) == (0, 2)
    assert info.status == RepoStatus.BEHIND
    assert g.calls.index("ab") > g.calls.index("fetch")


def test_status_no_fetch_keeps_parallel_reads():
    """fetch=False（TUI 启动路径）：不触发 fetch，ahead/behind 直接读当前 refs。"""
    g = FakeGitProvider()
    g.initialized = True
    g.set_remote("https://github.com/o/r")
    g.ahead, g.behind = 1, 0
    info = _svc(g).get_status(fetch=False)
    assert (info.ahead, info.behind) == (1, 0)
    assert info.status == RepoStatus.AHEAD
    assert g.fetch_calls == 0
