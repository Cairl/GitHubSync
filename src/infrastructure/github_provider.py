"""基础设施：GhCLIProvider —— 领域协议 GitHubProvider 的 gh CLI 实现。

集中全部 GitHub 远程操作（用户、仓库、Release），
实现可整体替换为 GitHub REST API 客户端而不影响上层。
"""

from __future__ import annotations

import json
import os
import re
import tempfile

from .command import run_command


class GhCLIProvider:
    def __init__(self, cwd: str):
        self.cwd = cwd

    @staticmethod
    def _extract_gh_user(remote_output: str) -> str | None:
        """从 git remote -v 输出中提取 GitHub 用户名"""
        if "github.com" not in remote_output:
            return None
        match = re.search(r"github\.com[:/]([^/ \n\r]+)/", remote_output)
        if match:
            user = match.group(1).split("@")[-1]
            return user if user and user != "git" else None
        return None

    def get_username(self) -> str | None:
        ok, out = run_command(["gh", "api", "user", "-q", ".login"])
        if ok and out and len(out) < 40:
            return out.strip()

        ok, out = run_command(["git", "remote", "-v"], cwd=self.cwd)
        user = self._extract_gh_user(out)
        if user:
            return user

        # 兜底：扫描邻近仓库的 remote 配置
        try:
            parent_dir = os.path.dirname(self.cwd)
            for folder in os.listdir(parent_dir):
                folder_path = os.path.join(parent_dir, folder)
                if not os.path.isdir(folder_path) or folder.startswith("."):
                    continue
                try:
                    if os.path.exists(os.path.join(folder_path, ".git")):
                        ok, out = run_command(["git", "-C", folder_path, "remote", "-v"])
                        user = self._extract_gh_user(out)
                        if user:
                            return user
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def get_repo_slug(self) -> str | None:
        ok, out = run_command(["git", "remote", "-v"], cwd=self.cwd)
        if ok and "github.com" in out:
            match = re.search(
                r"github\.com[:/]([^/ \n\r]+)/([^/ \n\r]+?)(?:\.git)?(?:\s|$)", out
            )
            if match:
                return f"{match.group(1)}/{match.group(2)}"
        return None

    def get_latest_release(self) -> dict | None:
        repo_slug = self.get_repo_slug()
        if not repo_slug:
            return None
        ok, out = run_command(
            ["gh", "release", "list", "--repo", repo_slug, "--limit", "1",
             "--json", "tagName,publishedAt"],
            cwd=self.cwd,
        )
        if ok and out:
            try:
                data = json.loads(out)
                if data:
                    return {
                        "tag": data[0].get("tagName", ""),
                        "published_at": data[0].get("publishedAt", ""),
                    }
            except (ValueError, IndexError):
                pass
            parts = out.split()
            if parts:
                return {"tag": parts[0], "published_at": ""}
        return None

    def get_all_releases(self, limit: int = 20) -> list[str]:
        repo_slug = self.get_repo_slug()
        if not repo_slug:
            return []
        ok, out = run_command(
            ["gh", "release", "list", "--repo", repo_slug, "--limit", str(limit)],
            cwd=self.cwd,
        )
        if not ok or not out:
            return []
        return [line.split()[0] for line in out.splitlines() if line.strip()]

    def publish_release(self, tag: str, notes_body: str) -> bool:
        """创建 Release；标签已存在则更新 notes。成功返回 True"""
        repo_slug = self.get_repo_slug()
        if not repo_slug:
            return False

        tmp_file = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=False, encoding="utf-8"
            ) as f:
                f.write(notes_body)
                tmp_file = f.name

            ok, out = run_command(
                ["gh", "release", "create", tag, "--repo", repo_slug,
                 "--target", "main", "--notes-file", tmp_file],
                cwd=self.cwd,
            )
            if not ok:
                if "already exist" in out.lower():
                    ok, out = run_command(
                        ["gh", "release", "edit", tag, "--repo", repo_slug,
                         "--notes-file", tmp_file],
                        cwd=self.cwd,
                    )
                    return ok
                return False
            return True
        finally:
            if tmp_file and os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except OSError:
                    pass

    def repo_exists(self, slug: str) -> bool:
        ok, _ = run_command(["gh", "repo", "view", slug], cwd=self.cwd)
        return ok

    def ensure_repo_created(self, repo_name: str) -> str | None:
        """打开浏览器引导创建仓库，轮询等待（最长 5 分钟）。

        成功返回 remote_url，无法确定用户名或超时返回 None。
        """
        import time
        import webbrowser

        username = self.get_username()
        url = f"https://github.com/new?name={repo_name}" if username else "https://github.com/new"
        webbrowser.open(url)
        if not username:
            return None

        remote_url = f"https://github.com/{username}/{repo_name}"
        for _ in range(100):  # 100 × 3s = 300s = 5min
            time.sleep(3)
            if self.repo_exists(f"{username}/{repo_name}"):
                return remote_url
        return None
