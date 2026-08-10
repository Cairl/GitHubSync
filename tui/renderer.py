"""差异化刷新器：块级原地重绘，内容未变不重绘。

与「每次按键整块追加打印」的区别：
- 首次渲染直接输出；
- 内容与上次相同 → 零输出（按无效键不再刷屏）；
- 内容变化 → ANSI 上移并逐行清除旧块，在原位置重画新块；
- 块下方的日志（ActionLog、diff、info）不受影响，保持自然滚动。

限制：块内文本若因终端过窄发生换行，行数统计会失真，
清除可能残留一列。交互内容行短，实际可忽略。
"""

from __future__ import annotations

import sys
from typing import Callable

from core.ansi import render_markup, supports_color

_CLEAR_LINE = "\x1b[2K"   # 清除光标所在整行
_LINE_DOWN = "\x1b[1B"    # 光标下移一行
_LINE_UP = "\x1b[{n}A"    # 光标上移 n 行


def markup_to_ansi(text: str) -> str:
    """markup → ANSI 字符串（stderr 为 tty 时着色，管道/重定向时纯文本）。

    语法与着色判定见 core/ansi.py；不做终端折行（宽度由调用方自行控制）。
    """
    return render_markup(text, supports_color(sys.stderr))


class DiffRenderer:
    """块级差异刷新器。out 与调用方共用（默认 print，自带换行）。"""

    def __init__(self, out: Callable[[str], None]):
        self._out = out
        self._lines = 0
        self._rendered = False
        self._last = ""

    @property
    def rendered(self) -> bool:
        return self._rendered

    def render(self, text: str) -> None:
        """渲染当前块。内容与上次相同则跳过；否则原地重绘。"""
        if self._rendered and text == self._last:
            return
        lines = text.splitlines()
        if self._rendered and self._lines:
            # 清掉旧块，光标停在旧块首行，随后直接接新块首行（out 自带换行）
            first = lines[0] if lines else ""
            self._out(self._erase(self._lines) + first)
            for line in lines[1:]:
                self._out(line)
        elif lines:
            self._out(text)
        self._lines = len(lines)
        self._last = text
        self._rendered = True

    def clear(self) -> None:
        """清除当前块并重置状态（视图切换时调用，避免错位重绘）。"""
        if self._rendered and self._lines:
            self._out(self._erase(self._lines))
        self.reset()

    def reset(self) -> None:
        """丢弃块状态：下次 render 直接输出。"""
        self._rendered = False
        self._lines = 0
        self._last = ""

    @staticmethod
    def _erase(n: int) -> str:
        """生成清除 n 行的 ANSI 序列，结束后光标回到首行行首。"""
        seq = _LINE_UP.format(n=n - 1) if n > 1 else ""
        seq += _CLEAR_LINE + (_LINE_DOWN + _CLEAR_LINE) * (n - 1)
        if n > 1:
            seq += _LINE_UP.format(n=n - 1)
        return seq
