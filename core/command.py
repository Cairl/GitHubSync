"""子进程执行基础设施：run_command（超时保护）与 retry 重试装饰器。

命令日志钩子：register_command_hook 注册的回调在每次命令执行后收到
(command, cwd, ok, output)，供 FileLogger 等落盘调试（钩子异常静默忽略）。
"""
from __future__ import annotations

import functools
import subprocess
import time
from typing import Callable

from .exceptions import CommandTimeoutError

# 网络类命令默认超时（秒）
DEFAULT_TIMEOUT = 120.0

# 命令执行日志钩子（全局注册，测试用 clear_command_hooks 清理）
CommandHook = Callable[[list[str], str | None, bool, str], None]
_command_hooks: list[CommandHook] = []


def register_command_hook(hook: CommandHook) -> None:
    """注册命令执行日志钩子（每次 run_command 结束后回调）。"""
    _command_hooks.append(hook)


def clear_command_hooks() -> None:
    """清空全部命令钩子（测试隔离用）。"""
    _command_hooks.clear()


def _notify_hooks(command: list[str], cwd: str | None,
                  ok: bool, output: str) -> None:
    """通知全部钩子；钩子异常静默忽略（日志失败不影响主流程）。"""
    for hook in _command_hooks:
        try:
            hook(command, cwd, ok, output)
        except Exception:
            pass


def run_command(command: list[str], cwd: str | None = None,
                timeout: float | None = None) -> tuple[bool, str]:
    """执行子进程命令，返回 (成功, 合并输出)。

    command 仅接受参数列表（永远不经 shell，杜绝注入）；超时抛 CommandTimeoutError。
    """
    try:
        result = subprocess.run(
            command, cwd=cwd, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
        out = result.stdout.strip()
        _notify_hooks(command, cwd, True, out)
        return True, out
    except subprocess.TimeoutExpired as e:
        _notify_hooks(command, cwd, False, "TIMEOUT")
        raise CommandTimeoutError(f"命令超时 / Command timed out: {command}") from e
    except subprocess.CalledProcessError as e:
        out = f"{e.stdout.strip()}\n{e.stderr.strip()}".strip()
        _notify_hooks(command, cwd, False, out)
        return False, out


def retry(max_attempts: int = 3, backoff: tuple[float, ...] = (0.5, 2.0),
          exceptions: tuple = (Exception,)) -> Callable:
    """失败重试装饰器。

    backoff = (初始延迟秒, 增长系数)；仅捕获 exceptions 指定的异常类型，
    达到 max_attempts 后原样抛出最后一次异常。
    """

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            delay = backoff[0] if backoff else 0.0
            factor = backoff[1] if len(backoff) > 1 else 1.0
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except exceptions:
                    if attempt >= max_attempts:
                        raise
                    time.sleep(delay)
                    delay *= factor

        return wrapper

    return decorator
