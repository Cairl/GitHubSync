"""CLI 子命令实现：只编排 core 服务层，不碰 git/gh 命令。

输出分流：结果数据（status_line / diff 行 / info 字段 / JSON）走 stdout，
诊断与交互提示（print_* / _prompt / ActionLog）走 stderr。
"""
from __future__ import annotations

import json
import sys

from core.events import ActionLog
from core.exceptions import SyncError
from core.i18n import tr
from core.services import Services
from core.status import RepoStatus, format_diff

from .exit_codes import EXIT_CHANGES, EXIT_DIVERGED, EXIT_FAILED, EXIT_OK
from .output import (echo, err, info_to_dict, print_action_log,
                     print_error, print_step, print_success, print_warn,
                     status_markup)

# 状态 → 退出码（NO_REPO / NO_REMOTE / ERROR 不在表中 → EXIT_FAILED）
_STATUS_EXIT = {
    RepoStatus.CLEAN: EXIT_OK,
    RepoStatus.CHANGED: EXIT_CHANGES,
    RepoStatus.AHEAD: EXIT_CHANGES,
    RepoStatus.BEHIND: EXIT_CHANGES,
    RepoStatus.DIVERGED: EXIT_DIVERGED,
}


def _prompt(msg: str) -> str:
    """交互提示走 stderr，避免污染 stdout 结果流。"""
    sys.stderr.write(msg)
    sys.stderr.flush()
    return sys.stdin.readline().rstrip("\n")


def _subscribe_logs(svc: Services, quiet: bool) -> None:
    """把 ActionLog 事件接到 stderr 诊断输出。"""
    svc.bus.subscribe(ActionLog, lambda e: print_action_log(e, quiet))


def cmd_status(args, svc: Services) -> int:
    info = svc.status.get_status()
    if args.json:
        print(json.dumps(info_to_dict(info), ensure_ascii=False))
    else:
        echo(status_markup(info), markup=True)
        if args.verbose and info.change_count:
            for line in format_diff(svc.git.get_porcelain()):
                echo(line)
    return _STATUS_EXIT.get(info.status, EXIT_FAILED)


def cmd_push(args, svc: Services) -> int:
    info = svc.status.get_status()
    if not args.yes:
        if not sys.stdin.isatty():
            print_error(tr("非交互环境需要 --yes 确认",
                           "non-interactive environment requires --yes"))
            return EXIT_FAILED
        target = f"origin/{info.branch}" if info.remote_url else "GitHub"
        answer = _prompt(tr(f"推送 {info.change_count} 处变化到 {target}? [y/N] ",
                            f"Push {info.change_count} changes to {target}? [y/N] "))
        if answer.strip().lower() != "y":
            err(tr("已取消。", "Cancelled."))
            return EXIT_OK
    _subscribe_logs(svc, args.quiet)
    try:
        svc.sync.run()
    except SyncError as e:
        print_error(e.message)
        if args.verbose and e.detail:
            err(e.detail)
        return EXIT_FAILED
    return EXIT_OK


def cmd_restore(args, svc: Services) -> int:
    if args.to:
        ok = svc.restore.restore(args.to)
        if ok:
            print_success(tr(f"已恢复到 {args.to[:8]}",
                             f"restored to {args.to[:8]}"))
        else:
            print_error(tr("恢复失败", "restore failed"))
        return EXIT_OK if ok else EXIT_FAILED
    if args.remote:
        ok = svc.restore.restore_remote()
        return EXIT_OK if ok else EXIT_FAILED
    # 无参数：tty 内列出最近 commit 编号选择
    commits = svc.git.get_recent_commits(20)
    if not commits:
        print_warn(tr("没有提交历史", "No commit history"))
        return EXIT_FAILED
    if not sys.stdin.isatty():
        print_error(tr("非交互环境请使用 --to <hash> 指定 commit",
                       "non-interactive environment requires --to <hash>"))
        return EXIT_FAILED
    for i, c in enumerate(commits, 1):
        err(f"{i:>2}. {c['hash'][:8]}  {c['time']}")
    answer = _prompt(tr("恢复到 [编号, q 退出]: ",
                        "Restore to [number, q to quit]: "))
    if not answer.isdigit() or not (1 <= int(answer) <= len(commits)):
        err(tr("已取消。", "Cancelled."))
        return EXIT_OK
    target = commits[int(answer) - 1]["hash"]
    if not args.yes:
        confirm = _prompt(tr(f"硬重置到 {target[:8]}? [y/N] ",
                             f"Reset --hard to {target[:8]}? [y/N] "))
        if confirm.strip().lower() != "y":
            err(tr("已取消。", "Cancelled."))
            return EXIT_OK
    ok = svc.restore.restore(target)
    return EXIT_OK if ok else EXIT_FAILED


def cmd_diff(args, svc: Services) -> int:
    lines = format_diff(svc.git.get_porcelain())
    if not lines:
        err(tr("工作区干净。", "Working tree clean."))
        return EXIT_OK
    for line in lines:
        echo(line)
    return EXIT_CHANGES


def cmd_info(args, svc: Services) -> int:
    info = svc.status.get_status(fetch=False)
    release = svc.gh.get_latest_release()
    commits = svc.git.get_recent_commits(5)
    if args.json:
        print(json.dumps({
            "path": info.path,
            "branch": info.branch,
            "remote_url": info.remote_url,
            "latest_release": release,
            "recent_commits": commits,
        }, ensure_ascii=False))
        return EXIT_OK
    echo(tr("路径: ", "Path:    ") + info.path)
    echo(tr("分支: ", "Branch:  ") + info.branch)
    echo(tr("远程: ", "Remote:  ")
         + (info.remote_url or tr("未配置", "not configured")))
    echo(tr("发布: ", "Release: ")
         + (release["tag"] if release else tr("无", "none")))
    if commits:
        echo(tr("提交:", "Commits:"))
        for c in commits:
            echo(f"  {c['hash'][:8]}  {c['time']}")
    return EXIT_OK


def cmd_switch(args, svc: Services) -> int:
    """切换/新建分支：结果走 stdout，失败诊断走 stderr。"""
    ok, msg = svc.branch.switch(args.branch, create=args.create)
    if ok:
        echo(tr(f"已切换到 {args.branch}", f"Switched to {args.branch}"))
        return EXIT_OK
    print_error(msg)
    return EXIT_FAILED


COMMANDS = {
    "status": cmd_status,
    "push": cmd_push,
    "restore": cmd_restore,
    "diff": cmd_diff,
    "info": cmd_info,
    "switch": cmd_switch,
}
