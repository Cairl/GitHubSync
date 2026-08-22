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
from core import i18n
from tests.fakes import FakeGitProvider, FakeGitHubProvider

i18n.LANG = "en"  # 测试固定英文输出


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


def test_sync_changelog_published_but_not_tracked(tmp_path):
    """changelog.md 存在时：发布 Release，但 gitignore 隔离、不入库、不计变更项。"""
    sync, git, gh, bus, _ = make_services(str(tmp_path))
    git.init_repo()
    git.remote = "https://github.com/octocat/repo"
    git.files["a.txt"] = "hello"
    git.files["changelog.md"] = "- 优化同步流程"
    changelog_path = os.path.join(str(tmp_path), "changelog.md")
    with open(changelog_path, "w", encoding="utf-8") as f:
        f.write("- 优化同步流程")

    result = sync.run()

    assert gh.published                              # 已发布 Release
    assert not os.path.exists(changelog_path)        # 发布后删除本地文件
    assert "changelog.md" in git.gitignore_lines     # gitignore 隔离（不入库）
    assert "changelog.md" not in git.tracked         # 不入库、不上远程
    assert "changelog.md" not in result.updated_items  # 不计入变更项
    assert "a.txt" in git.tracked
    assert result.committed == 1


def test_sync_changelog_never_tracked_across_runs(tmp_path):
    """changelog.md 从未入库：发布删除后下次同步无删除提交、无 changelog 痕迹。"""
    sync, git, gh, bus, _ = make_services(str(tmp_path))
    git.init_repo()
    git.remote = "https://github.com/octocat/repo"
    git.files["a.txt"] = "hello"
    git.files["changelog.md"] = "- 优化同步流程"
    changelog_path = os.path.join(str(tmp_path), "changelog.md")
    with open(changelog_path, "w", encoding="utf-8") as f:
        f.write("- 优化同步流程")

    first = sync.run()
    assert gh.published                             # 首次发布 Release
    assert not os.path.exists(changelog_path)       # 发布后本地删除
    assert "changelog.md" not in git.tracked        # 从未入库

    # 模拟发布后的工作区状态：内存工作区同步删除 changelog.md（fakes 与磁盘不同步）
    del git.files["changelog.md"]
    second = sync.run()

    assert second.committed == 0                    # 无删除提交
    assert second.updated_items == {}               # 无 changelog 痕迹
    assert "changelog.md" not in git.tracked


def test_sync_changelog_publish_failure_keeps_local(tmp_path):
    """发布失败：文件保留本地且仍 gitignore 隔离（不入库），同步仍成功。"""
    sync, git, gh, bus, _ = make_services(str(tmp_path))
    git.init_repo()
    git.remote = "https://github.com/octocat/repo"
    git.files["a.txt"] = "hello"
    git.files["changelog.md"] = "- 待发布内容"
    changelog_path = os.path.join(str(tmp_path), "changelog.md")
    with open(changelog_path, "w", encoding="utf-8") as f:
        f.write("- 待发布内容")
    gh.publish_ok = False                            # 发布失败

    result = sync.run()

    assert os.path.exists(changelog_path)            # 文件保留待重试
    assert "changelog.md" in git.gitignore_lines     # 仍 gitignore 隔离
    assert "changelog.md" not in git.tracked         # 不入库
    assert result.pushed is True                     # 其余文件正常推送


def test_sync_untracks_legacy_tracked_changelog(tmp_path):
    """旧版已入库的 changelog.md：首次同步自动停止跟踪（保留本地），推送清远端。"""
    sync, git, gh, bus, _ = make_services(str(tmp_path))
    git.init_repo()
    git.remote = "https://github.com/octocat/repo"
    git.files["a.txt"] = "hello"
    git.tracked.add("a.txt")
    # 模拟历史残留：changelog.md 已被 git 跟踪且本地文件存在
    git.files["changelog.md"] = "- 优化同步流程"
    git.tracked.add("changelog.md")
    changelog_path = os.path.join(str(tmp_path), "changelog.md")
    with open(changelog_path, "w", encoding="utf-8") as f:
        f.write("- 优化同步流程")

    result = sync.run()

    assert "changelog.md" not in git.tracked        # 已停止跟踪
    assert "changelog.md" in git.gitignore_lines     # 已加入 gitignore
    assert result.updated_items == {"changelog.md": "D"}  # 本次推送删除远端
    assert gh.published                              # Release 照常发布
    assert not os.path.exists(changelog_path)        # 发布后本地删除
    assert result.committed == 1


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


def test_sync_emits_progress_logs(tmp_path):
    """实时进度：scan 文件数 / commit 提交数 / push 进度均以 PROGRESS 发布。"""
    sync, git, gh, bus, _ = make_services(str(tmp_path))
    git.init_repo()
    git.remote = "https://github.com/octocat/repo"
    git.files["a.txt"] = "x"
    git.files["b.txt"] = "y"
    git.push_progress = ["45% (1/2) · 512 B", "100% (2/2) · 1.00 KiB"]

    logs = []
    bus.subscribe(ActionLog, logs.append)

    sync.run()

    progress = [e for e in logs if e.level == "PROGRESS"]
    stages = [e.stage for e in progress]
    assert "scan" in stages and "commit" in stages and "push" in stages
    scan = next(e for e in progress if e.stage == "scan")
    assert scan.message == "2 change(s)"
    commit = next(e for e in progress if e.stage == "commit")
    assert commit.message == "Committed 2 change(s)"
    push = [e.message for e in progress if e.stage == "push"]
    assert push == ["45% (1/2) · 512 B", "100% (2/2) · 1.00 KiB"]


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
