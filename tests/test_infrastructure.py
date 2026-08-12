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
    assert g.ahead_behind_upstream() is None  # 未配置远程时无上游
    g.set_remote("https://github.com/o/r")
    assert g.ahead_behind_upstream() == (2, 1)
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


# ── markup 超链接（OSC 8）──
def test_markup_link_emits_osc8():
    """`[link url]…[/]` 渲染为 OSC 8 超链接序列，可与颜色组合。"""
    from core.ansi import render_markup
    out = render_markup("[link https://x.test/a #F6E2B7]text[/]", color=True)
    assert "\x1b]8;;https://x.test/a\x1b\\" in out  # 超链接开头
    assert out.endswith("\x1b]8;;\x1b\\\x1b[0m")  # 闭合序列 + 样式恢复
    assert "#F6E2B7" not in out  # 颜色已转为 SGR（无字面色值残留）


def test_markup_link_stripped_when_plain():
    """非 tty（管道/重定向）时超链接标签剥离，文本原样输出，无 OSC 8 序列。"""
    from core.ansi import render_markup
    assert render_markup("[link https://x.test/a #F6E2B7]text[/]",
                         color=False) == "text"


def test_markup_link_unclosed_safety_close():
    """未闭合的 link 标签在末尾兜底闭合，防超链接泄漏到后续输出。"""
    from core.ansi import render_markup
    out = render_markup("[link https://x.test/a]text", color=True)
    assert out.endswith("\x1b]8;;\x1b\\\x1b[0m")  # 兜底闭合 + 样式重置


def test_markup_link_nested_with_color_restore():
    """link 与颜色嵌套：闭合后外层样式恢复，OSC 8 闭合先于样式恢复。"""
    from core.ansi import render_markup
    out = render_markup("[bold][link https://x.test/a]x[/]y[/]", color=True)
    assert "\x1b]8;;https://x.test/a\x1b\\x\x1b]8;;\x1b\\" in out
    assert out.endswith("y\x1b[0m")  # 外层 bold 在 link 闭合后继续作用于 y


# ── 文件日志（FileLogger）──
def test_file_logger_writes_timestamped_line(tmp_path):
    """log() 自动创建目录并写入 `时间 [级别] 消息` 行。"""
    from core.file_logger import FileLogger
    p = tmp_path / "sub" / "debug.log"  # 目录不存在，应自动创建
    FileLogger(str(p)).log("ACTION", "发布 Release 26w32a")
    content = p.read_text(encoding="utf-8")
    assert "[ACTION] 发布 Release 26w32a" in content
    assert content.startswith("20")  # 带时间戳


def test_file_logger_attaches_events_and_commands(tmp_path):
    """attach() 后：事件总线 ActionLog 与命令执行（CMD OK/FAIL）全部落盘。"""
    from core.command import clear_command_hooks, run_command
    from core.events import ActionLog, DomainEventBus
    from core.file_logger import FileLogger
    clear_command_hooks()
    try:
        bus = DomainEventBus()
        logger = FileLogger(str(tmp_path / "debug.log"))
        logger.attach(bus)
        bus.publish(ActionLog("DONE", "已推送"))
        run_command([sys.executable, "-c", "print('hi')"])
        run_command([sys.executable, "-c", "import sys; sys.exit(1)"])
        content = (tmp_path / "debug.log").read_text(encoding="utf-8")
        assert "[DONE] 已推送" in content
        assert "[CMD OK" in content and "-c" in content
        assert "[CMD FAIL" in content
    finally:
        clear_command_hooks()


def test_file_logger_reprs_domain_events(tmp_path):
    """非 ActionLog 事件以 repr 落盘（含关键字段）。"""
    from core.events import DomainEventBus, SyncCompleted
    from core.file_logger import FileLogger
    bus = DomainEventBus()
    logger = FileLogger(str(tmp_path / "debug.log"))
    logger.attach(bus)
    bus.publish(SyncCompleted(pushed=True, committed=2))
    content = (tmp_path / "debug.log").read_text(encoding="utf-8")
    assert "SyncCompleted" in content and "pushed=True" in content


def test_file_logger_rotates_over_limit(tmp_path, monkeypatch):
    """超过大小上限后轮转：旧内容进 .1，主文件重新开始。"""
    import core.file_logger as fl
    monkeypatch.setattr(fl, "MAX_LOG_SIZE", 60)
    p = tmp_path / "debug.log"
    logger = fl.FileLogger(str(p))
    for i in range(40):
        logger.log("X", "y" * 20)
    assert (tmp_path / "debug.log.1").exists()
    assert p.exists()


def test_file_logger_write_failure_silent(tmp_path):
    """路径不可写（指向目录）时静默降级，不抛异常。"""
    from core.file_logger import FileLogger
    logger = FileLogger(str(tmp_path))  # path 是目录，open 会失败
    logger.log("X", "msg")  # 不抛


def test_file_logger_defaults_to_session_file(monkeypatch, tmp_path):
    """未传 path 时在统一日志目录生成会话文件（githubsync-<时间戳>.log）。"""
    import os
    from core.file_logger import FileLogger, LOG_PREFIX
    monkeypatch.setattr("core.file_logger.LOG_DIR", str(tmp_path))
    logger = FileLogger()
    name = os.path.basename(logger.path)
    assert name.startswith(LOG_PREFIX) and name.endswith(".log")
    logger.log("INFO", "Session start")
    assert (tmp_path / name).exists()


# ── executor 抽象 ──
def test_inline_executor_runs_synchronously():
    from core.executor import InlineExecutor
    seen = []
    InlineExecutor().submit(lambda: 42, seen.append)
    assert seen == [42]


def test_thread_executor_runs_callback_with_result():
    import threading
    from core.executor import ThreadExecutor
    done = threading.Event()
    seen = []
    ex = ThreadExecutor(max_workers=1)
    ex.submit(lambda: 7, lambda r: (seen.append(r), done.set()))
    assert done.wait(2) and seen == [7]
    ex.shutdown()


def test_executor_exception_yields_none():
    from core.executor import InlineExecutor
    seen = []

    def boom():
        raise RuntimeError("x")

    InlineExecutor().submit(boom, seen.append)
    assert seen == [None]
