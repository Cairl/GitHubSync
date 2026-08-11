"""终端工具：msvcrt 单键读取、光标显隐、CJK 显示宽度计算。

仅交互模式（tui/）依赖本模块；cli/ 与 core/ 其余模块零 msvcrt 依赖。
VT100 启用见 core/ansi.py 的 supports_color（ctypes 实现，零子进程）。
"""
from __future__ import annotations

import msvcrt
import sys
import unicodedata


def hide_cursor() -> None:
    """隐藏终端光标：交互模式增量刷新时避免光标闪烁干扰。"""
    sys.stdout.write("\x1b[?25l")
    sys.stdout.flush()


def show_cursor() -> None:
    """恢复显示终端光标（退出交互模式前必须调用，防止光标永久消失）。"""
    sys.stdout.write("\x1b[?25h")
    sys.stdout.flush()


def get_display_width(text) -> int:
    """计算显示宽度：CJK 全角字符占 2，其余占 1。"""
    return sum(2 if unicodedata.east_asian_width(c) in ("F", "W") else 1
               for c in str(text))


def get_key() -> bytes:
    """读取单个按键（含方向键等扩展键的第二次扫描码）。"""
    key = msvcrt.getch()
    if key in (b"\xe0", b"\x00"):
        return msvcrt.getch()
    return key
