"""基础设施：命令执行与重试。

- run_command：子进程执行封装，支持超时（根治网络挂死卡死 TUI 的问题）；
- retry：重试装饰器，仅对可安全重试的操作启用（写操作绝不自动重试）。
"""

from __future__ import annotations

import subprocess
import time
from functools import wraps
from typing import Callable, Optional, Sequence, TypeVar, Union

from ..domain.exceptions import CommandTimeoutError

T = TypeVar("T")

# 默认超时：普通命令 30s，推送可放宽
DEFAULT_TIMEOUT = 30
PUSH_TIMEOUT = 120


def run_command(
    command: Union[str, Sequence[str]],
    cwd: Optional[str] = None,
    timeout: Optional[float] = DEFAULT_TIMEOUT,
) -> tuple[bool, str]:
    """执行子进程命令。

    - command 为字符串时使用 shell=True，为列表时使用 shell=False；
    - 成功返回 (True, stdout.strip())；
    - 失败（非零退出码）返回 (False, "stdout\\nstderr")；
    - 超时抛 CommandTimeoutError（调用方必须处理，不得静默吞掉）。
    """
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            shell=not isinstance(command, list),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return True, result.stdout.strip()
    except subprocess.TimeoutExpired:
        raise CommandTimeoutError(
            f"命令执行超时（>{timeout:.0f}s）",
            detail=str(command),
        )
    except subprocess.CalledProcessError as e:
        return False, f"{e.stdout.strip()}\n{e.stderr.strip()}".strip()


def retry(
    max_attempts: int = 3,
    backoff: Sequence[float] = (1.0, 2.0, 4.0),
    exceptions: tuple[type[Exception], ...] = (CommandTimeoutError,),
    on_retry: Optional[Callable[[int, Exception], None]] = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """重试装饰器：指数退避，仅对指定异常重试。

    注意：只应装饰幂等的只读操作（查询状态 / fetch / release 列表等）。
    写操作（commit / push / rm）绝不使用本装饰器。
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            attempt = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    attempt += 1
                    if attempt >= max_attempts:
                        raise
                    delay = backoff[min(attempt - 1, len(backoff) - 1)]
                    if on_retry is not None:
                        on_retry(attempt, e)
                    time.sleep(delay)

        return wrapper

    return decorator
