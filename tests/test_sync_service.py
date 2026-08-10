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


def test_sync_rejected_raises_without_force(tmp_path):
    sync, git, gh, bus, _ = make_services(str(tmp_path))
    git.init_repo()
    git.remote = "https://github.com/octocat/repo"
    git.files["c.txt"] = "data"
    git.fail_mode = "rejected"

    with pytest.raises(PushRejectedError):
        sync.run()

    assert git.force_push_calls == 0  # 不再自动强推


def test_sync_rejected_force_push_when_explicit(tmp_path):
    sync, git, gh, bus, _ = make_services(str(tmp_path))
    git.init_repo()
    git.remote = "https://github.com/octocat/repo"
    git.files["c.txt"] = "data"
    git.fail_mode = "rejected"

    result = sync.run(force=True)

    assert result.pushed is True
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


def test_restore_remote_fetch_failure(tmp_path):
    git = FakeGitProvider()
    git.init_repo()
    git.fetch_ok = False
    assert RestoreService(git, DomainEventBus()).restore_remote() is False
