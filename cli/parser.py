"""CLI 参数定义：githubsync [status|push|restore|diff|info]。"""
from __future__ import annotations

import argparse

from core.i18n import tr
from main import __version__


class _ArgumentParser(argparse.ArgumentParser):
    """中文化 argparse 内置词条（usage 前缀、分节标题、帮助/版本动作）。

    add_subparsers 默认 parser_class=type(self)，子命令解析器自动继承。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._positionals.title = tr("位置参数", "positional arguments")
        self._optionals.title = tr("选项", "options")
        for action in self._actions:
            if isinstance(action, argparse._HelpAction):
                action.help = tr("显示此帮助信息并退出",
                                 "show this help message and exit")
            elif isinstance(action, argparse._VersionAction):
                action.help = tr("显示版本号并退出",
                                 "show program's version number and exit")

    def add_argument(self, *args, **kwargs):
        # --version 动作在 __init__ 之后添加，单独补中文帮助
        if kwargs.get("action") == "version":
            kwargs.setdefault("help", tr("显示版本号并退出",
                                         "show program's version number and exit"))
        return super().add_argument(*args, **kwargs)

    def format_usage(self) -> str:
        # usage 前缀由 HelpFormatter.add_usage 内部 gettext 决定，此处替换
        return super().format_usage().replace(
            "usage: ", tr("用法: ", "usage: "), 1)

    def format_help(self) -> str:
        return super().format_help().replace(
            "usage: ", tr("用法: ", "usage: "), 1)


def build_parser() -> argparse.ArgumentParser:
    """构建完整参数解析器；每个子命令支持可选 path 位置参数与 -C/--repo。"""
    p = _ArgumentParser(
        prog="githubsync",
        description=tr("GitHub 同步工具：查看 → 决策 → 执行 → 完成",
                       "GitHub sync tool: see → decide → act → done"))
    p.add_argument("--version", action="version",
                   version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command")

    def base(name: str, help_text: str) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("path", nargs="?", default=None,
                        help=tr("仓库目录（默认当前目录）",
                                "repo directory (default: cwd)"))
        sp.add_argument("-C", "--repo", default=None,
                        help=tr("仓库目录（等价于位置参数）",
                                "repo directory (same as path)"))
        return sp

    sp = base("status", tr("显示仓库同步状态", "show sync status"))
    sp.add_argument("--verbose", action="store_true",
                    help=tr("展开文件级变化", "list file-level changes"))
    sp.add_argument("--json", action="store_true",
                    help=tr("机器可读输出", "machine-readable output"))

    sp = base("push", tr("提交并推送本地变化", "commit and push local changes"))
    sp.add_argument("--yes", "-y", action="store_true",
                    help=tr("跳过确认", "skip confirmation"))
    sp.add_argument("--force", "-f", action="store_true",
                    help=tr("分叉时强制推送", "force push when diverged"))
    sp.add_argument("--quiet", "-q", action="store_true",
                    help=tr("只输出错误", "errors only"))
    sp.add_argument("--verbose", action="store_true",
                    help=tr("显示 Git 原始输出", "show raw git output"))

    sp = base("restore", tr("从 GitHub 恢复到本地", "restore from GitHub"))
    sp.add_argument("--to", default=None,
                    help=tr("恢复到指定 commit", "restore to commit"))
    sp.add_argument("--remote", action="store_true",
                    help=tr("本地对齐远程", "align with origin/<branch>"))
    sp.add_argument("--yes", "-y", action="store_true",
                    help=tr("跳过确认", "skip confirmation"))

    base("diff", tr("显示文件级变化列表", "list file-level changes"))

    sp = base("info", tr("远程地址、提交、Release", "remote URL, commits, release"))
    sp.add_argument("--json", action="store_true",
                    help=tr("机器可读输出", "machine-readable output"))
    return p
