"""SyncService 用例测试：同步流程、失败恢复、事件发布。"""

from __future__ import annotations

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.sync_service import SyncService
from core.events import ActionLog, DomainEventBus, SyncCompleted, SyncFailed
from core.exceptions import NetworkError, PushRejectedError, SyncError
from core.release_service import ReleaseService
from tests.fakes import FakeGitProvider, FakeGitHubProvider


def make_services(tmp_path: str):
    bus = DomainEventBus()
    git = FakeGitProvider()
    gh = FakeGitHubProvider()
    release = ReleaseService(gh, bus, tmp_path)
    sync = SyncService(git, gh, bus, tmp_path, release)
    return sync, git, gh, bus, release


def test_sync_full_success(tmp_path):
    sync, git, gh, bus, _ = make_services(str(tmp_path))
    git.init_repo()
    git.remote = "https://github.com/octocat/repo"
    git.files["a.txt"] = "hello"

    events = []
    bus.subscribe(SyncCompleted, events.append)

    result = sync.run()

    assert result.pushed is True
    assert result.committed == 1
    assert "a.txt" in result.updated_items
    assert len(events) == 1
    assert git.tracked == {"a.txt"}


def test_sync_no_changes(tmp_path):
    sync, git, gh, bus, _ = make_services(str(tmp_path))
    git.init_repo()
    git.remote = "https://github.com/octocat/repo"
    git.tracked = {"a.txt"}
    git.files = {"a.txt": "hello"}

    result = sync.run()

    assert result.committed == 0
    assert result.pushed is True


def test_sync_changelog_committed_not_ignored(tmp_path):
    """changelog.md 不被 .gitignore 排除：残留条目被清理，正常暂存、提交、入库。"""
    sync, git, gh, bus, _ = make_services(str(tmp_path))
    git.init_repo()
    git.remote = "https://github.com/octocat/repo"
    git.gitignore_lines = ["__pycache__/", "changelog.md"]  # 旧版残留
    git.files["a.txt"] = "hello"
    git.files["changelog.md"] = "# v1.0"

    result = sync.run()

    assert result.committed == 1
    assert "changelog.md" in result.updated_items   # 计入提交项
    assert "changelog.md" in git.tracked            # 已提交入库
    assert "changelog.md" not in git.gitignore_lines  # 残留条目被清理


def test_sync_repo_not_found_recovers(tmp_path):
    sync, git, gh, bus, _ = make_services(str(tmp_path))
    git.init_repo()
    git.remote = "https://github.com/octocat/repo"
    git.files["b.txt"] = "data"
    git.fail_mode = "repo_not_found"

    result = sync.run()

    assert result.pushed is True
    assert gh.repo_created_url is not None  # 已引导创建仓库
    assert git.remote == gh.repo_created_url


def test_sync_rejected_auto_force_push(tmp_path):
    sync, git, gh, bus, _ = make_services(str(tmp_path))
    git.init_repo()
    git.remote = "https://github.com/octocat/repo"
    git.files["c.txt"] = "data"
    git.fail_mode = "rejected"

    logs = []
    bus.subscribe(ActionLog, logs.append)

    result = sync.run()

    assert result.pushed is True
    assert git.force_push_calls == 1  # 分叉自动强推
    assert any("force pushing" in e.message for e in logs)


def test_sync_rejected_force_push_fails_raises(tmp_path):
    sync, git, gh, bus, _ = make_services(str(tmp_path))
    git.init_repo()
    git.remote = "https://github.com/octocat/repo"
    git.files["c.txt"] = "data"
    git.fail_mode = "rejected"
    git.force_fail = True  # 强推仍失败（如分支保护）

    with pytest.raises(PushRejectedError):
        sync.run()

    assert git.force_push_calls == 1


def test_sync_network_error_publishes_failed(tmp_path, monkeypatch):
    from core import i18n
    monkeypatch.setattr(i18n, "LANG", "zh")
    sync, git, gh, bus, _ = make_services(str(tmp_path))
    git.init_repo()
    git.remote = "https://github.com/octocat/repo"
    git.files["d.txt"] = "data"
    git.fail_mode = "network"

    failed = []
    bus.subscribe(SyncFailed, failed.append)

    with pytest.raises(NetworkError):
        sync.run()

    assert len(failed) == 1
    assert "网络" in failed[0].message


def test_sync_creates_repo_when_unconfigured(tmp_path):
    sync, git, gh, bus, _ = make_services(str(tmp_path))
    git.init_repo()
    git.remote = None  # 未配置
    git.files["e.txt"] = "data"

    result = sync.run()

    assert result.pushed is True
    assert git.remote.startswith("https://github.com/octocat/")  # 按目录名自动配置


def test_sync_emits_action_logs(tmp_path):
    sync, git, gh, bus, _ = make_services(str(tmp_path))
    git.init_repo()
    git.remote = "https://github.com/octocat/repo"
    git.files["f.txt"] = "x"

    logs = []
    bus.subscribe(ActionLog, logs.append)

    sync.run()

    levels = [e.level for e in logs]
    assert "ACTION" in levels and "DONE" in levels


def test_sync_on_feature_branch_keeps_branch_and_push_target(tmp_path):
    """契约：非 main 分支同步后分支名不变，推送目标为当前分支。"""
    sync, git, gh, bus, _ = make_services(str(tmp_path))
    git.init_repo()
    git.remote = "https://github.com/octocat/repo"
    git.branch = "feature"
    git.branches = ["main", "feature"]
    git.files["g.txt"] = "x"

    result = sync.run()

    assert result.pushed is True
    assert git.branch == "feature"          # 分支名不被改名
    assert git.push_branches == ["feature"]  # 推送目标是 feature 而非 main


def test_sync_init_renames_to_main_once(tmp_path):
    """契约：建仓初始化时默认分支改名 main 一次（模拟 git init 默认 master）。"""
    sync, git, gh, bus, _ = make_services(str(tmp_path))
    git.branch = "master"  # 模拟老版本 git init 的默认分支名
    git.remote = "https://github.com/octocat/repo"
    git.files["h.txt"] = "x"

    result = sync.run()

    assert result.pushed is True
    assert git.branch == "main"
    assert git.push_branches == ["main"]


def test_sync_push_timeout_publishes_failed(tmp_path):
    """推送超时不穿透：按 SyncError 兜底，发布 SyncFailed 事件。"""
    from core.exceptions import CommandTimeoutError
    sync, git, gh, bus, _ = make_services(str(tmp_path))
    git.init_repo()
    git.remote = "https://github.com/octocat/repo"
    git.files["t.txt"] = "data"

    def timeout_push(*args, **kwargs):
        raise CommandTimeoutError("命令超时 / Command timed out: git push")

    git.push = timeout_push

    failed = []
    bus.subscribe(SyncFailed, failed.append)

    with pytest.raises(SyncError):
        sync.run()
    assert len(failed) == 1


# ── RestoreService.restore_remote ──
from core.restore_service import RestoreService


def test_restore_remote_resets_to_origin(tmp_path):
    bus = DomainEventBus()
    git = FakeGitProvider()
    git.init_repo()
    git.remote = "https://github.com/octocat/repo"
    svc = RestoreService(git, bus)

    assert svc.restore_remote() is True
    assert git.reset_to == "origin/main"
    assert git.fetch_calls == 1
    assert git.clean_calls == 1  # 1:1 复刻：reset 后清理未跟踪文件


def test_restore_remote_fetch_failure(tmp_path):
    git = FakeGitProvider()
    git.init_repo()
    git.fetch_ok = False
    assert RestoreService(git, DomainEventBus()).restore_remote() is False
    assert git.clean_calls == 0


def test_restore_remote_clean_failure(tmp_path):
    bus = DomainEventBus()
    git = FakeGitProvider()
    git.init_repo()
    git.remote = "https://github.com/octocat/repo"
    git.clean_ok = False
    failed = []
    bus.subscribe(ActionLog, failed.append)

    assert RestoreService(git, bus).restore_remote() is False
    assert git.reset_to == "origin/main"  # reset 已执行
    assert git.clean_calls == 1
    assert any("clean" in e.message for e in failed)
