"""markup → ANSI 转换（markup_to_ansi）。

语法与着色判定见 core/ansi.py；不做终端折行（宽度由调用方自行控制）。
"""

from __future__ import annotations

import sys

from core.ansi import render_markup, supports_color


def markup_to_ansi(text: str) -> str:
    """markup → ANSI 字符串（stderr 为 tty 时着色，管道/重定向时纯文本）。"""
    return render_markup(text, supports_color(sys.stderr))
