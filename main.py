"""GitHubSync 入口：argparse 调度 + 组合根（create_services 唯一组装点）。

用法：
    githubsync            # 无子命令 → 极简交互模式（非 tty 显示帮助）
    githubsync status     # 单行状态；--verbose 文件级；--json 机器可读
    githubsync push       # 全量同步（提交 + 推送 + Release 发布）
    githubsync restore    # 恢复 commit / 对齐远程
    githubsync diff       # 文件级变化列表
    githubsync info       # 远程地址 / 最近提交 / 最新 Release
    githubsync switch     # 切换分支（-c 新建并切换）

目录来源优先级：-C/--repo > 位置参数 > 当前目录。环境变量（GITHUBSYNC_REPO）由
github_sync.bat 层写入/读取，主程序不读取环境变量。
"""
from __future__ import annotations

import os
import sys

__version__ = "3.0.0"


def create_services(repo_path: str, log_path: str | None = None):
    """组合根：唯一组装依赖的地方。

    log_path: 文件日志路径（默认 ~/.githubsync/logs/ 下按时间戳生成会话文件，
    所有项目调用统一汇聚，见 core/file_logger.py）；传 None 用默认，测试或特殊场景可注入。
    """
    from core.branch_service import BranchService
    from core.events import DomainEventBus
    from core.file_logger import FileLogger
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
    logger = FileLogger(log_path)
    logger.attach(bus)  # 业务事件 + 命令执行详情落盘（TUI 无回显的日志进文件）
    logger.log("INFO", f"Session start: {repo_path}")
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
    from core.i18n import tr

    args_list = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()

    # 无子命令时的仓库目录位置参数：githubsync "C:\path\to\project"
    # （argparse subparsers 会把未知首词判成 invalid choice，需在解析前取出）
    top_path = None
    if args_list and not args_list[0].startswith("-") \
            and args_list[0] not in COMMANDS:
        top_path = args_list.pop(0)
        if not os.path.isdir(os.path.abspath(top_path)):
            # 首参数既非子命令也非已存在目录：报错（防子命令笔误误入交互）
            print(tr(f"目录不存在: {top_path}",
                     f"Directory not found: {top_path}"), file=sys.stderr)
            return EXIT_FAILED

    args = parser.parse_args(args_list)

    # 目录解析：-C/--repo > 位置参数 > 当前工作目录（环境变量仅由 github_sync.bat 层处理）
    repo = (getattr(args, "repo", None) or getattr(args, "path", None)
            or top_path)
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
