"""GitHubSync 入口：argparse 调度 + 组合根（create_services 唯一组装点）。

用法：
    githubsync            # 无子命令 → 极简交互模式（非 tty 显示帮助）
    githubsync status     # 单行状态；--verbose 文件级；--json 机器可读
    githubsync push       # 全量同步（提交 + 推送 + Release 发布）
    githubsync restore    # 恢复 commit / 对齐远程
    githubsync diff       # 文件级变化列表
    githubsync info       # 远程地址 / 最近提交 / 最新 Release
    githubsync switch     # 切换分支（-c 新建并切换）
"""
from __future__ import annotations

import os
import sys

__version__ = "3.0.0"


def create_services(repo_path: str):
    """组合根：唯一组装依赖的地方。"""
    from core.branch_service import BranchService
    from core.events import DomainEventBus
    from core.file_ops_service import FileOpsService
    from core.git_provider import GitCLIProvider
    from core.github_provider import GhCLIProvider
    from core.release_service import ReleaseService
    from core.restore_service import RestoreService
    from core.services import Services
    from core.status_service import StatusService
    from core.sync_service import SyncService

    bus = DomainEventBus()
    git = GitCLIProvider(repo_path)
    gh = GhCLIProvider(repo_path)
    release = ReleaseService(gh, bus, repo_path)
    return Services(
        git=git, gh=gh, bus=bus,
        status=StatusService(git, repo_path),
        sync=SyncService(git, gh, bus, repo_path, release),
        restore=RestoreService(git, bus),
        file_ops=FileOpsService(git, bus, repo_path),
        release=release,
        branch=BranchService(git, bus),
    )


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。返回退出码：0 成功/干净 · 1 有变化 · 2 分叉 · 3 失败。"""
    if sys.platform != "win32":
        print("GitHubSync only supports Windows. / 此工具仅支持 Windows 平台。")
        return 3

    from cli.commands import COMMANDS
    from cli.exit_codes import EXIT_FAILED
    from cli.parser import build_parser

    args_list = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(args_list)

    # 目录解析：-C/--repo 或位置参数优先，默认当前工作目录
    repo = getattr(args, "repo", None) or getattr(args, "path", None)
    repo_path = os.path.abspath(repo) if repo else os.getcwd()
    svc = create_services(repo_path)

    if args.command is None:
        if not sys.stdin.isatty():
            # 非交互环境（cron/管道）无子命令：显示帮助，避免 msvcrt 阻塞
            parser.print_help(sys.stderr)
            return EXIT_FAILED
        from tui.interactive import InteractiveApp
        return InteractiveApp(svc, repo_path).run()
    return COMMANDS[args.command](args, svc)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:  # 兜底：未预期错误统一失败退出码
        print(f"\nUnexpected error / 发生错误: {exc}")
        sys.exit(3)
