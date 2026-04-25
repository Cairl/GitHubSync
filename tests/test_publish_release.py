import pytest
from unittest.mock import patch, MagicMock
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from github_sync import GitManager


class TestGetRepoSlug:
    def test_get_repo_slug_https_remote(self):
        with patch.object(GitManager, '__init__', lambda self, *a, **kw: None):
            gm = GitManager.__new__(GitManager)
            gm.cwd = "/tmp/test"
            gm.logs = []
            gm.on_log = None
            gm.frozen_changes = None
            gm.updated_items = {}

        with patch("github_sync.run_command") as mock_run:
            mock_run.return_value = (True, "origin  https://github.com/owner/repo.git (fetch)\norigin  https://github.com/owner/repo.git (push)")
            result = gm.get_repo_slug()
            assert result == "owner/repo"

    def test_get_repo_slug_ssh_remote(self):
        with patch.object(GitManager, '__init__', lambda self, *a, **kw: None):
            gm = GitManager.__new__(GitManager)
            gm.cwd = "/tmp/test"
            gm.logs = []
            gm.on_log = None
            gm.frozen_changes = None
            gm.updated_items = {}

        with patch("github_sync.run_command") as mock_run:
            mock_run.return_value = (True, "origin  git@github.com:owner/repo.git (fetch)\norigin  git@github.com:owner/repo.git (push)")
            result = gm.get_repo_slug()
            assert result == "owner/repo"

    def test_get_repo_slug_no_remote(self):
        with patch.object(GitManager, '__init__', lambda self, *a, **kw: None):
            gm = GitManager.__new__(GitManager)
            gm.cwd = "/tmp/test"
            gm.logs = []
            gm.on_log = None
            gm.frozen_changes = None
            gm.updated_items = {}

        with patch("github_sync.run_command") as mock_run:
            mock_run.return_value = (False, "")
            result = gm.get_repo_slug()
            assert result is None

    def test_get_repo_slug_non_github(self):
        with patch.object(GitManager, '__init__', lambda self, *a, **kw: None):
            gm = GitManager.__new__(GitManager)
            gm.cwd = "/tmp/test"
            gm.logs = []
            gm.on_log = None
            gm.frozen_changes = None
            gm.updated_items = {}

        with patch("github_sync.run_command") as mock_run:
            mock_run.return_value = (True, "origin  https://gitlab.com/owner/repo.git (fetch)")
            result = gm.get_repo_slug()
            assert result is None


class TestPublishRelease:
    def _make_gm(self, tmp_path):
        with patch.object(GitManager, '__init__', lambda self, *a, **kw: None):
            gm = GitManager.__new__(GitManager)
            gm.cwd = str(tmp_path)
            gm.logs = []
            gm.on_log = None
            gm.frozen_changes = None
            gm.updated_items = {}
        return gm

    def test_no_releases_md_skips(self, tmp_path):
        gm = self._make_gm(tmp_path)
        gm.publish_release()
        assert len(gm.logs) == 0

    def test_arbitrary_version_creates_release(self, tmp_path):
        releases = tmp_path / "releases.md"
        releases.write_text("v1.0.0\n\n添加:\n- 新功能", encoding="utf-8")
        gm = self._make_gm(tmp_path)
        with patch.object(gm, "get_repo_slug", return_value="owner/repo"), \
             patch("github_sync.run_command") as mock_run:
            mock_run.return_value = (True, "")
            gm.publish_release()
        assert any("发布成功" in log for log in gm.logs)
        mock_run.assert_called()
        call_args = mock_run.call_args[0][0]
        assert "gh release create v1.0.0" in call_args
        assert "--target main" in call_args

    def test_markdown_heading_version_stripped(self, tmp_path):
        releases = tmp_path / "releases.md"
        releases.write_text("# 26w17a\n\n添加:\n- 新功能", encoding="utf-8")
        gm = self._make_gm(tmp_path)
        with patch.object(gm, "get_repo_slug", return_value="owner/repo"), \
             patch("github_sync.run_command") as mock_run:
            mock_run.return_value = (True, "")
            gm.publish_release()
        assert any("发布成功" in log for log in gm.logs)
        call_args = mock_run.call_args[0][0]
        assert "gh release create 26w17a" in call_args

    def test_existing_release_edits(self, tmp_path):
        releases = tmp_path / "releases.md"
        releases.write_text("26w17a\n\n修复:\n- bug", encoding="utf-8")
        gm = self._make_gm(tmp_path)
        with patch.object(gm, "get_repo_slug", return_value="owner/repo"), \
             patch("github_sync.run_command") as mock_run:
            mock_run.side_effect = [
                (False, "already exists"),
                (True, ""),
            ]
            gm.publish_release()
        assert any("发布成功" in log for log in gm.logs)
        edit_call = mock_run.call_args_list[1][0][0]
        assert "gh release edit 26w17a" in edit_call

    def test_no_repo_slug_warns(self, tmp_path):
        releases = tmp_path / "releases.md"
        releases.write_text("26w17a\ncontent", encoding="utf-8")
        gm = self._make_gm(tmp_path)
        with patch.object(gm, "get_repo_slug", return_value=None):
            gm.publish_release()
        assert any("无法获取仓库信息" in log for log in gm.logs)
