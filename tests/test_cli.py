"""CLI 子命令测试：退出码、输出渲染、--json、--yes、force 策略。"""
import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.file_ops_service import FileOpsService
from core.release_service import ReleaseService
from core.restore_service import RestoreService
from core.status_service import StatusService
from core.sync_service import SyncService
from cli import commands
from cli.exit_codes import EXIT_CHANGES, EXIT_DIVERGED, EXIT_FAILED, EXIT_OK
from cli.output import format_diff, status_line, status_markup
from core import i18n
from core.events import DomainEventBus

i18n.LANG = "en"  # 测试固定英文输出
from core.status import RepoInfo, RepoStatus
from core.services import Services
from tests.fakes import FakeGitHubProvider, FakeGitProvider


class Args:
    """简易参数命名空间。"""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def make_services(**git_kw):
    bus = DomainEventBus()
    git = FakeGitProvider()
    for k, v in git_kw.items():
        setattr(git, k, v)
    gh = FakeGitHubProvider()
    release = ReleaseService(gh, bus, "fake_repo")
    return Services(
        git=git, gh=gh, bus=bus,
        status=StatusService(git, "fake_repo"),
        sync=SyncService(git, gh, bus, "fake_repo", release),
        restore=RestoreService(git, bus),
        file_ops=FileOpsService(git, bus, "fake_repo"),
        release=release,
    )


def run(fn, args, svc):
    out_buf, err_buf = io.StringIO(), io.StringIO()
    with redirect_stdout(out_buf), redirect_stderr(err_buf):
        code = fn(args, svc)
    return code, out_buf.getvalue(), err_buf.getvalue()


# ── status_line 渲染 ──
def test_status_line_rendering():
    base = dict(branch="main", path="p")
    assert status_line(RepoInfo(RepoStatus.CLEAN, **base)) == "main · synced"
    assert status_line(RepoInfo(RepoStatus.CHANGED, added=1, modified=2, **base)) == \
        "main · 3 changes (+1 ~2)"
    assert status_line(RepoInfo(RepoStatus.AHEAD, ahead=2, **base)) == "main · ahead 2"
    assert status_line(RepoInfo(RepoStatus.BEHIND, behind=1, **base)) == "main · behind 1"
    assert status_line(RepoInfo(RepoStatus.DIVERGED, ahead=3, behind=1, **base)) == \
        "main · diverged (ahead 3, behind 1)"
    assert status_line(RepoInfo(RepoStatus.NO_REPO, **base)) == "not a git repository"
    assert status_line(RepoInfo(RepoStatus.NO_REMOTE, **base)) == "main · no remote"


def test_status_markup_keeps_plain_text():
    """status_markup 剥离 markup 后应与 status_line 一致（着色不改变文本）。"""
    import re
    base = dict(branch="main", path="p")
    for info in [RepoInfo(RepoStatus.CLEAN, **base),
                 RepoInfo(RepoStatus.CHANGED, added=1, modified=2, **base),
                 RepoInfo(RepoStatus.DIVERGED, ahead=3, behind=1, **base)]:
        plain = re.sub(r"\[/?[^\]]*\]", "", status_markup(info))
        assert plain == status_line(info)
    # 分支与状态语义色存在
    assert "#58A6FF" in status_markup(RepoInfo(RepoStatus.CLEAN, **base))  # 分支蓝
    assert "#3FB950" in status_markup(RepoInfo(RepoStatus.CLEAN, **base))  # 同步绿
    assert "#F85149" in status_markup(RepoInfo(RepoStatus.DIVERGED, ahead=1, behind=1, **base))  # 分叉红


def test_format_diff():
    assert format_diff(" M a.py\n?? b.txt\n D c.py\n") == ["M  a.py", "A  b.txt", "D  c.py"]


# ── status 命令退出码 ──
def test_cmd_status_exit_codes():
    args = Args(json=False, verbose=False)
    code, _, _ = run(commands.cmd_status, args,
                     make_services(initialized=True, remote="x"))
    assert code == EXIT_OK
    code, _, _ = run(commands.cmd_status, args,
                     make_services(initialized=True, remote="x", files={"a": "1"}))
    assert code == EXIT_CHANGES
    code, _, _ = run(commands.cmd_status, args,
                     make_services(initialized=True, remote="x", ahead=1, behind=1))
    assert code == EXIT_DIVERGED
    code, _, _ = run(commands.cmd_status, args, make_services())  # 未初始化
    assert code == EXIT_FAILED


def test_cmd_status_json():
    code, out, _ = run(commands.cmd_status, Args(json=True, verbose=False),
                       make_services(initialized=True, remote="x"))
    data = json.loads(out)
    assert code == EXIT_OK and data["status"] == "CLEAN" and data["branch"] == "main"


# ── push ──
def test_cmd_push_yes_success():
    svc = make_services(initialized=True, remote="x", files={"a.py": "1"})
    code, _, err = run(commands.cmd_push,
                      Args(yes=True, quiet=False, verbose=False), svc)
    assert code == EXIT_OK and "[OK]" in err


def test_cmd_push_diverged_auto_force():
    """分叉时推送自动强推（本地 1:1 覆盖远程），不再需要 --force。"""
    svc = make_services(initialized=True, remote="x", files={"a": "1"},
                        fail_mode="rejected")
    code, _, _ = run(commands.cmd_push,
                     Args(yes=True, quiet=False, verbose=False), svc)
    assert code == EXIT_OK
    assert svc.git.force_push_calls == 1


def test_cmd_push_network_error_fails():
    svc = make_services(initialized=True, remote="x", files={"a": "1"},
                        fail_mode="network")
    code, _, _ = run(commands.cmd_push,
                     Args(yes=True, quiet=False, verbose=False), svc)
    assert code == EXIT_FAILED


# ── diff ──
def test_cmd_diff_exit_codes():
    code, out, _ = run(commands.cmd_diff, Args(),
                       make_services(initialized=True, remote="x", files={"a.py": "1"}))
    assert code == EXIT_CHANGES and "M  a.py" in out
    code, out, _ = run(commands.cmd_diff, Args(),
                       make_services(initialized=True, remote="x"))
    assert code == EXIT_OK


# ── restore ──
def test_cmd_restore_to_and_remote():
    svc = make_services(initialized=True, remote="x")
    svc.git.commits = ["abcdef123456"]
    code, _, _ = run(commands.cmd_restore, Args(to="abcdef12", remote=False, yes=True), svc)
    assert code == EXIT_OK and svc.git.reset_to == "abcdef12"
    code, _, _ = run(commands.cmd_restore, Args(to=None, remote=True, yes=True), svc)
    assert code == EXIT_OK and svc.git.reset_to == "origin/main"


# ── 入口目录解析 ──
def test_main_resolves_repo_from_cwd(monkeypatch, tmp_path):
    """无路径参数时，main 使用 os.getcwd() 作为仓库目录。"""
    import main as main_module
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["githubsync", "status", "--json"])
    code = main_module.main()
    # 未初始化的 git 仓库 → EXIT_FAILED（3），证明目录解析到 tmp_path
    assert code == EXIT_FAILED


def test_format_diff_stripped_first_line():
    # run_command 整体 strip 导致首行 " M" 前缀丢失的回归测试
    assert format_diff("M a.py\n M b.py\n") == ["M  a.py", "M  b.py"]
    assert format_diff("D old.py\n M b.py\n") == ["D  old.py", "M  b.py"]


def test_status_line_zh(monkeypatch):
    """中文系统显示中文文案。"""
    monkeypatch.setattr(i18n, "LANG", "zh")
    base = dict(branch="main", path="p")
    assert status_line(RepoInfo(RepoStatus.CLEAN, **base)) == "main · 已同步"
    assert status_line(RepoInfo(RepoStatus.AHEAD, ahead=2, **base)) == "main · 领先 2"
    assert status_line(RepoInfo(RepoStatus.DIVERGED, ahead=3, behind=1, **base)) ==         "main · 分叉 (领先 3, 落后 1)"
    monkeypatch.setattr(i18n, "LANG", "en")
    assert status_line(RepoInfo(RepoStatus.CLEAN, **base)) == "main · synced"


def test_output_diagnostics_go_to_stderr():
    """print_success/warn/error/step 走 stderr，不污染 stdout。"""
    from cli.output import print_success, print_warn, print_error, print_step
    out_buf, err_buf = io.StringIO(), io.StringIO()
    with redirect_stdout(out_buf), redirect_stderr(err_buf):
        print_success("ok")
        print_warn("warn")
        print_error("err")
        print_step("step")
    assert out_buf.getvalue() == ""
    assert "ok" in err_buf.getvalue()
    assert "warn" in err_buf.getvalue()
    assert "err" in err_buf.getvalue()
    assert "step" in err_buf.getvalue()


def test_cmd_status_result_to_stdout_actionlog_to_stderr():
    """status 人读结果走 stdout，push 的 ActionLog 走 stderr。"""
    # status 结果在 stdout
    code, out, err = run(commands.cmd_status, Args(json=False, verbose=False),
                         make_services(initialized=True, remote="x"))
    assert "synced" in out and out.strip() != ""
    # push 成功的 [OK] 诊断在 stderr，stdout 为空
    svc = make_services(initialized=True, remote="x", files={"a.py": "1"})
    code, out, err = run(commands.cmd_push,
                         Args(yes=True, quiet=False, verbose=False), svc)
    assert "[OK]" in err and out == ""


def test_no_ansi_when_stdout_not_tty():
    """stdout 非 tty 时，status 输出不含 ANSI 转义序列（管道友好）。"""
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(io.StringIO()):
        commands.cmd_status(Args(json=False, verbose=False),
                            make_services(initialized=True, remote="x"))
    out = buf.getvalue()
    assert "\x1b[" not in out  # 无 ANSI CSI 序列
    assert "synced" in out
