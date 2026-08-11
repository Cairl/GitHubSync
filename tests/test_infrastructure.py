"""gitignore 解析器与命令执行/重试测试。"""

from __future__ import annotations

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.exceptions import CommandTimeoutError
from core.command import retry, run_command
from core.gitignore_parser import GitignoreMatcher


# ── gitignore 解析 ──
def test_basic_glob():
    m = GitignoreMatcher("*.pyc\n")
    assert m.is_ignored("a.pyc") is True
    assert m.is_ignored("a.py") is False


def test_negation():
    m = GitignoreMatcher("*.pyc\n!keep.pyc\n")
    assert m.is_ignored("keep.pyc") is False
    assert m.is_ignored("other.pyc") is True


def test_dir_ignore_inherits():
    m = GitignoreMatcher("build/\n")
    assert m.is_ignored("build/x.txt") is True
    assert m.is_ignored("build", is_dir=True) is True


def test_anchor_root():
    m = GitignoreMatcher("/root.txt\n")
    assert m.is_ignored("root.txt") is True
    assert m.is_ignored("sub/root.txt") is False


def test_double_star_recursive():
    m = GitignoreMatcher("**/temp\n")
    assert m.is_ignored("a/b/temp") is True


def test_path_anchor():
    m = GitignoreMatcher("foo/bar\n")
    assert m.is_ignored("foo/bar/baz.txt") is True
    assert m.is_ignored("foo/baz.txt") is False


def test_negation_overrides_dir():
    m = GitignoreMatcher("*.log\n!important.log\n")
    assert m.is_ignored("important.log") is False


# ── 命令超时 ──
def test_run_command_timeout():
    with pytest.raises(CommandTimeoutError):
        run_command(["python", "-c", "import time; time.sleep(5)"], timeout=0.3)


def test_timeout_error_is_sync_error():
    """超时归入同步异常体系：TUI/CLI 的 SyncError 兜底能接住，不再穿透闪退。"""
    from core.exceptions import SyncError
    assert issubclass(CommandTimeoutError, SyncError)


# ── git 子进程适配器 ──
def test_get_porcelain_disables_quotepath(monkeypatch):
    """中文文件名必须原样输出：get_porcelain 须带 -c core.quotepath=false。

    回归：默认 core.quotepath=true 时 git 把非 ASCII 路径转义成
    \\ooo 八进制（如 "01.\\343\\200\\212..."），format_diff 与
    _collect_updated_items 只剥引号不反解，中文文件名显示乱码、
    推送收集顶层路径出错。
    """
    import core.git_provider as gp

    captured: dict = {}

    def fake_run(command, cwd=None, timeout=None):
        captured["cmd"] = command
        return True, ""

    monkeypatch.setattr(gp, "run_command", fake_run)
    provider = gp.GitCLIProvider(".")
    provider.get_porcelain()
    assert captured["cmd"] == ["git", "-c", "core.quotepath=false",
                               "status", "--porcelain"]


def test_run_command_success():
    ok, out = run_command([sys.executable, "-c", "print('hello')"])
    assert ok is True
    assert out == "hello"


def test_run_command_failure():
    ok, out = run_command(
        [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"]
    )
    assert ok is False
    assert "boom" in out


# ── 重试装饰器 ──
def test_retry_succeeds_after_failures():
    calls = {"n": 0}

    @retry(max_attempts=3, backoff=(0.01, 0.01), exceptions=(ValueError,))
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("boom")
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3


def test_retry_gives_up():
    calls = {"n": 0}

    @retry(max_attempts=3, backoff=(0.01, 0.01), exceptions=(ValueError,))
    def always_fails():
        calls["n"] += 1
        raise ValueError("boom")

    with pytest.raises(ValueError):
        always_fails()
    assert calls["n"] == 3


def test_retry_only_catches_specified():
    calls = {"n": 0}

    @retry(max_attempts=3, backoff=(0.01, 0.01), exceptions=(KeyError,))
    def raises_type_error():
        calls["n"] += 1
        raise TypeError("not retried")

    with pytest.raises(TypeError):
        raises_type_error()
    assert calls["n"] == 1  # 非目标异常不重试


# ── FakeProvider 远程同步状态契约 ──
def test_fake_git_ahead_behind_and_remote():
    from tests.fakes import FakeGitProvider
    g = FakeGitProvider()
    g.ahead, g.behind = 2, 1
    assert g.ahead_behind("main") is None  # 未配置远程时无上游
    g.set_remote("https://github.com/o/r")
    assert g.ahead_behind("main") == (2, 1)
    assert g.remote_url() == "https://github.com/o/r"


def test_fake_git_fetch_records_call():
    from tests.fakes import FakeGitProvider
    g = FakeGitProvider()
    assert g.fetch() is True
    assert g.fetch_calls == 1
    g.fetch_ok = False
    assert g.fetch() is False


def test_fake_git_restore_to_origin_branch():
    from tests.fakes import FakeGitProvider
    g = FakeGitProvider()
    assert g.restore_to_commit("origin/main") is True
    assert g.reset_to == "origin/main"


def test_fake_git_remote_head():
    """FakeGitProvider.remote_head 返回可配置值；未配置返回 None。"""
    from tests.fakes import FakeGitProvider
    g = FakeGitProvider()
    assert g.remote_head("main") is None
    g.remote_head_hash = "fedcba9876543210"
    assert g.remote_head("main") == "fedcba9876543210"
