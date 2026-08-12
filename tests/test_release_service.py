"""ReleaseService 测试：版本号纯逻辑 + 发布流程。"""

from __future__ import annotations

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.release_service import ReleaseService
from core.events import DomainEventBus, ReleasePublished
from tests.fakes import FakeGitHubProvider

# 固定"当前时间"用于版本计算测试：2026-08-06 是 2026 年第 32 周
NOW = datetime(2026, 8, 6, 12, 0, 0)


def test_version_first_release():
    assert ReleaseService.calculate_next_version(None, now=NOW) == "26w32a"


def test_version_same_week_increments():
    latest = {"tag": "26w32a"}
    assert ReleaseService.calculate_next_version(latest, now=NOW) == "26w32b"


def test_version_rolls_alpha():
    latest = {"tag": "26w32z"}
    assert ReleaseService.calculate_next_version(latest, now=NOW) == "26w32aa"


def test_version_new_week_resets():
    latest = {"tag": "26w31z"}
    assert ReleaseService.calculate_next_version(latest, now=NOW) == "26w32a"


def test_version_unrecognized_tag_resets():
    latest = {"tag": "v1.0.0"}
    assert ReleaseService.calculate_next_version(latest, now=NOW) == "26w32a"


def test_maybe_publish_no_changelog(tmp_path):
    gh = FakeGitHubProvider()
    bus = DomainEventBus()
    svc = ReleaseService(gh, bus, str(tmp_path))
    assert svc.maybe_publish() is False
    assert gh.published == []


def test_maybe_publish_publishes_and_deletes(tmp_path):
    gh = FakeGitHubProvider()
    bus = DomainEventBus()
    changelog = os.path.join(str(tmp_path), "changelog.md")
    with open(changelog, "w", encoding="utf-8") as f:
        f.write("# 更新内容\n- 修复 bug")

    published = []
    bus.subscribe(ReleasePublished, published.append)
    svc = ReleaseService(gh, bus, str(tmp_path))
    expected = ReleaseService.calculate_next_version(None, now=datetime.now())

    assert svc.maybe_publish() is True
    assert len(gh.published) == 1
    tag, notes = gh.published[0]
    assert tag == expected
    assert "修复 bug" in notes
    assert not os.path.exists(changelog)  # 发布后删除本地 changelog
    assert len(published) == 1


def test_get_latest_release_sorts_by_published_at(monkeypatch):
    """gh release list 按创建时间排序时，取 publishedAt 最新的 tag（防版本号撞车）。"""
    import json as _json

    from core.github_provider import GhCLIProvider
    import core.github_provider as gh_mod

    provider = GhCLIProvider(".")
    monkeypatch.setattr(provider, "get_repo_slug", lambda: "octocat/repo")
    # 模拟 gh 默认排序：edit 过的 26w33c 排后面，创建更早的 26w33b 在首位
    payload = _json.dumps([
        {"tagName": "26w33b", "publishedAt": "2026-08-10T12:49:32Z"},
        {"tagName": "26w33a", "publishedAt": "2026-08-10T11:02:48Z"},
        {"tagName": "26w33c", "publishedAt": "2026-08-10T12:51:09Z"},
    ])
    monkeypatch.setattr(gh_mod, "run_command", lambda *a, **k: (True, payload))

    latest = provider.get_latest_release()
    assert latest == {"tag": "26w33c",
                      "published_at": "2026-08-10T12:51:09Z"}
    # 版本号计算不撞车：26w33c → 26w33d（33 周内递增）
    assert ReleaseService.calculate_next_version(
        latest, now=datetime(2026, 8, 10, 13, 0, 0)) == "26w33d"
