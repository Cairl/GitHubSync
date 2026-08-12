"""文件日志：把 TUI 无回显化的业务日志与 git/gh 命令执行详情落盘，供后期 AI 调试。

- 业务日志：订阅 DomainEventBus（ActionLog 的 ACTION/DONE/FAIL/NOTE 与各类完成/失败事件），
  TUI 交互模式取消 ActionLog 回显，但这些事件在此全部落盘；
- 命令日志：注册 core.command 的命令钩子，每次 run_command 执行后记录
  （命令 + 成功/失败 + 输出截断），可还原完整执行序列；
- 落盘位置：用户目录 ~/.githubsync/githubsync.log（仓库外，不参与同步），
  单文件 append，超过 1MB 轮转为 .1（旧备份丢弃）；
- 写失败一律静默降级（try/except OSError），绝不干扰主流程。
"""
from __future__ import annotations

import os
import time

from .command import register_command_hook
from .events import (ActionLog, DomainEventBus, ReleasePublished,
                     RestoreCompleted, SyncCompleted, SyncFailed)

# 单文件上限：超出后轮转为 .1（覆盖旧备份），防止无限膨胀
MAX_LOG_SIZE = 1_048_576
# 单条命令输出截断长度（防多行输出把日志撑爆）
_MAX_LINE = 500


def default_log_path() -> str:
    """默认日志路径：用户目录 ~/.githubsync/githubsync.log。"""
    return os.path.join(os.path.expanduser("~"), ".githubsync",
                        "githubsync.log")


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class FileLogger:
    """文件日志写入器：log() 直写 + attach() 挂到事件总线与命令钩子。"""

    def __init__(self, path: str | None = None):
        self.path = path or default_log_path()
        self._prepare()

    def _prepare(self) -> None:
        """确保目录存在（失败静默，后续写操作同样降级）。"""
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
        except OSError:
            pass

    # ── 写入 ──
    def _maybe_rotate(self) -> None:
        try:
            if os.path.getsize(self.path) > MAX_LOG_SIZE:
                os.replace(self.path, self.path + ".1")
        except OSError:
            pass

    def log(self, level: str, message: str) -> None:
        """追加一行 `时间 [级别] 消息`；写失败静默（调试日志不阻塞业务）。"""
        try:
            self._maybe_rotate()
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(f"{_now()} [{level}] {message}\n")
        except OSError:
            pass

    # ── 挂接 ──
    def attach(self, bus: DomainEventBus) -> None:
        """订阅全部可记录事件 + 注册命令钩子。"""
        for event_type in (ActionLog, SyncCompleted, SyncFailed,
                           RestoreCompleted, ReleasePublished):
            bus.subscribe(event_type, self._on_event)
        register_command_hook(self._on_command)

    # ── 事件处理 ──
    def _on_event(self, event) -> None:
        if isinstance(event, ActionLog):
            self.log(event.level, event.message)
        else:
            # 完成/失败类事件：repr 含关键字段（pushed/committed/target/tag…）
            self.log("EVENT", repr(event))

    def _on_command(self, command: list[str], cwd: str | None,
                    ok: bool, output: str) -> None:
        status = "CMD OK  " if ok else "CMD FAIL"
        text = " ".join(command)
        if output:
            text += " | " + output.replace("\n", " \\n ")[:_MAX_LINE]
        self.log(status, text)
