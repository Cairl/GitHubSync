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
