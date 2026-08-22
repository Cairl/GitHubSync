"""子进程执行基础设施：run_command / run_command_stream（超时保护）与 retry。

命令日志钩子：register_command_hook 注册的回调在每次命令执行后收到
(command, cwd, ok, output)，供 FileLogger 等落盘调试（钩子异常静默忽略）。
"""
from __future__ import annotations

import functools
import queue
import subprocess
import threading
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


def run_command_stream(command: list[str], cwd: str | None = None,
                       timeout: float | None = None,
                       on_chunk: Callable[[str], None] | None = None
                       ) -> tuple[bool, str]:
    """流式执行子进程命令：stderr 逐行实时回调 on_chunk（进度回显用）。

    与 run_command 的区别：命令运行期间 stderr 每输出一行（含 \r 回车行，
    如 git push --progress 的进度刷新），即调用 on_chunk(line)；调用方可在
    回调中实时解析进度。返回 (成功, 合并输出) 与 run_command 一致，
    超时抛 CommandTimeoutError。command 仅接受参数列表（不经 shell）。

    git push --progress 的进度行以 \r 结尾（同一行反复覆盖刷新），
    逐行读取需按 \r/\n 双分隔符切分，否则会阻塞到命令结束才拿到全部输出。
    """
    proc = subprocess.Popen(
        command, cwd=cwd,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
        bufsize=1,
    )
    lines: queue.Queue[str | None] = queue.Queue()

    def _read_stream(src) -> None:
        """读单个输出流：按 \r/\n 切分入队；流结束置标记。"""
        try:
            for line in src:
                start = 0
                for i, ch in enumerate(line):
                    if ch in "\r\n":
                        lines.put(line[start:i + 1])
                        start = i + 1
                if start < len(line):
                    lines.put(line[start:])
        finally:
            with _eof_lock:
                _eof_count[0] += 1
                if _eof_count[0] == 2:
                    lines.put(None)  # 两个流都读完才入 EOF 哨兵

    _eof_count: list[int] = [0]
    _eof_lock = threading.Lock()
    for src in (proc.stdout, proc.stderr):
        threading.Thread(target=_read_stream, args=(src,), daemon=True).start()

    deadline = time.monotonic() + timeout if timeout is not None else None
    out_chunks: list[str] = []
    timed_out = False
    while True:
        if deadline is not None and time.monotonic() > deadline:
            timed_out = True
            break
        try:
            line = lines.get(timeout=0.1)
        except queue.Empty:
            if proc.poll() is None:
                continue  # 进程仍在运行，继续等待输出
            line = lines.get()  # 进程已退出，等 EOF 哨兵收尾
        if line is None:
            break
        out_chunks.append(line)
        if on_chunk is not None:
            try:
                on_chunk(line)
            except Exception:
                pass  # 回调异常不得中断命令执行
    if timed_out:
        proc.kill()
        proc.wait()
        _notify_hooks(command, cwd, False, "TIMEOUT")
        raise CommandTimeoutError(f"命令超时 / Command timed out: {command}")

    proc.wait(timeout=timeout)

    out = "".join(out_chunks).strip()
    ok = proc.returncode == 0
    _notify_hooks(command, cwd, ok, out)
    return ok, out


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
