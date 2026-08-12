"""GhCLIProvider：gh 子进程适配器（GitHubProvider 协议的真实实现）。

含浏览器引导建仓：打开 github.com/new 后轮询 gh repo view 直到仓库出现。
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
import webbrowser

from .command import DEFAULT_TIMEOUT, run_command


def _extract_gh_user(remote_output: str) -> str | None:
    """从 git remote -v 输出中提取 GitHub 用户名。"""
    if "github.com" not in remote_output:
        return None
    match = re.search(r"github\.com[:/]([^/ \n\r]+)/", remote_output)
    if match:
        user = match.group(1).split("@")[-1]
        return user if user and user != "git" else None
    return None


class GhCLIProvider:
    """通过 gh CLI 操作 repo_path 对应仓库的 GitHub 资源。"""

    def __init__(self, repo_path: str):
        self.cwd = repo_path

    # ── 账号与仓库 ──
    def get_username(self) -> str | None:
        ok, out = run_command(["gh", "api", "user", "-q", ".login"],
                              timeout=DEFAULT_TIMEOUT)
        if ok and out and len(out) < 40:
            return out.strip()
        ok, out = run_command(["git", "remote", "-v"], cwd=self.cwd)
        if ok:
            user = _extract_gh_user(out)
            if user:
                return user
        # 回退：扫描邻近目录的仓库 remote
        try:
            parent_dir = os.path.dirname(self.cwd)
            for folder in os.listdir(parent_dir):
                folder_path = os.path.join(parent_dir, folder)
                if not os.path.isdir(folder_path) or folder.startswith("."):
                    continue
                if os.path.exists(os.path.join(folder_path, ".git")):
                    ok, out = run_command(["git", "-C", folder_path,
                                           "remote", "-v"])
                    if ok:
                        user = _extract_gh_user(out)
                        if user:
                            return user
        except OSError:
            pass
        return None

    def get_repo_slug(self) -> str | None:
        ok, out = run_command(["git", "remote", "-v"], cwd=self.cwd)
        if ok and "github.com" in out:
            match = re.search(
                r"github\.com[:/]([^/ \n\r]+)/([^/ \n\r]+?)(?:\.git)?(?:\s|$)",
                out)
            if match:
                return f"{match.group(1)}/{match.group(2)}"
        return None

    def repo_exists(self, slug: str) -> bool:
        ok, _ = run_command(["gh", "repo", "view", slug],
                            timeout=DEFAULT_TIMEOUT)
        return ok

    # ── Release ──
    def get_latest_release(self) -> dict | None:
        slug = self.get_repo_slug()
        if not slug:
            return None
        # gh release list 默认按创建时间排序，edit 过的 tag（如 26w33c）会被排到后面，
        # 导致 --limit 1 取到旧 tag、版本号撞车。拉多条后按 publishedAt 取最新。
        ok, out = run_command([
            "gh", "release", "list", "--repo", slug, "--limit", "30",
            "--json", "tagName,publishedAt",
        ], timeout=DEFAULT_TIMEOUT)
        if ok and out:
            try:
                data = json.loads(out)
            except ValueError:
                data = None
            if data:
                best = max(data, key=lambda r: r.get("publishedAt", "") or "")
                return {"tag": best.get("tagName", ""),
                        "published_at": best.get("publishedAt", "")}
            if data is None:
                # JSON 解析失败（旧版 gh 不支持 --json）：回退解析文本输出（首列为标签名）。
                # 注意：无 Release 时 gh 输出 "[]"，JSON 解析成功但为空，此时应返回 None
                # 而非把 "[]" 当 tag（顶栏显示 `-` 占位）。
                parts = out.split()
                if parts:
                    return {"tag": parts[0], "published_at": ""}
        return None

    def get_all_releases(self, limit: int = 20) -> list[str]:
        slug = self.get_repo_slug()
        if not slug:
            return []
        ok, out = run_command(["gh", "release", "list", "--repo", slug,
                               "--limit", str(limit)], timeout=DEFAULT_TIMEOUT)
        if not ok or not out:
            return []
        return [line.split()[0] for line in out.splitlines() if line.strip()]

    def publish_release(self, tag: str, notes_body: str) -> bool:
        slug = self.get_repo_slug()
        if not slug:
            return False
        tmp_file = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".md",
                                             delete=False,
                                             encoding="utf-8") as f:
                f.write(notes_body)
                tmp_file = f.name
            ok, out = run_command([
                "gh", "release", "create", tag, "--repo", slug,
                "--target", "main", "--notes-file", tmp_file,
            ], timeout=DEFAULT_TIMEOUT)
            if not ok and "already exist" in out.lower():
                ok, _ = run_command([
                    "gh", "release", "edit", tag, "--repo", slug,
                    "--notes-file", tmp_file,
                ], timeout=DEFAULT_TIMEOUT)
            return ok
        except OSError:
            return False
        finally:
            if tmp_file and os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except OSError:
                    pass

    # ── 建仓引导 ──
    def ensure_repo_created(self, repo_name: str) -> str | None:
        """打开浏览器引导建仓并轮询等待（最长约 5 分钟），成功返回仓库 URL。"""
        username = self.get_username()
        if not username:
            return None
        webbrowser.open(f"https://github.com/new?name={repo_name}")
        slug = f"{username}/{repo_name}"
        for _ in range(100):  # 100 × 3s = 5min
            time.sleep(3)
            if self.repo_exists(slug):
                return f"https://github.com/{slug}"
        return None
