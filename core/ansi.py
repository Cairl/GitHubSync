"""ANSI 着色与 markup 解析：Rich 的自研替代，零第三方依赖。

markup 语法（项目既有用法的 Rich 子集）：
- ``[#RRGGBB]...[/]``          前景色（24-bit）
- ``[on #RRGGBB]...[/]``       背景色
- ``[bold]`` / ``[dim]`` / ``[strike]``，可组合（如 ``[bold on #636363]``）
- ``[link <url>]...[/]``       超链接（OSC 8）：终端原生支持 Ctrl+点击打开，可与颜色组合
- ``[/]`` 关闭最近打开的样式；支持嵌套，内层关闭后外层样式继续生效
- ``\\[`` 转义为字面 ``[``，``\\\\`` 转义为字面 ``\\``
- 无法识别的方括号内容按字面文本处理（不抛异常，对文件名等安全）

着色判定：仅当目标流 isatty 时产出 ANSI 序列，管道/重定向自动纯文本
（超链接序列随之省略，文本原样保留）；Windows 下首次着色写入前惰性启用
VT100 处理。
"""
from __future__ import annotations

import os
import re
import sys
from typing import IO

_RESET = "\x1b[0m"
_HEX_RE = re.compile(r"#[0-9A-Fa-f]{6}\Z")
_OSC8_CLOSE = "\x1b]8;;\x1b\\"  # OSC 8 超链接闭合序列

# 已启用 VT100 的流句柄缓存（每进程每流一次）
_vt100_ready: set[int] = set()


def fg_sgr(color: str) -> str:
    """#RRGGBB → 前景色 SGR 序列（用于消息本体不参与标签解析的着色）。"""
    r, g, b = _hex_to_rgb(color)
    return f"\x1b[38;2;{r};{g};{b}m"


RESET = _RESET


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


def _parse_tag(spec: str) -> dict | None:
    """标签内容 → 样式属性字典；无法识别返回 None（按字面文本处理）。

    支持 `link <url>`：url 为超链接目标（OSC 8，终端 Ctrl+点击打开），
    可与其他样式组合（如 `[link https://… #F6E2B7]`）。
    """
    attrs: dict = {}
    tokens = spec.split()
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "link" and i + 1 < len(tokens):
            attrs["link"] = tokens[i + 1]
            i += 1
        elif token in ("bold", "dim", "strike"):
            attrs[token] = True
        elif token == "on" and i + 1 < len(tokens) and _HEX_RE.match(tokens[i + 1]):
            attrs["bg"] = tokens[i + 1]
            i += 1
        elif _HEX_RE.match(token):
            attrs["fg"] = token
        else:
            return None
        i += 1
    return attrs if attrs else None


def _sgr(attrs: dict) -> str:
    """样式属性 → SGR 序列（不含 reset）。"""
    codes = []
    if attrs.get("bold"):
        codes.append("1")
    if attrs.get("dim"):
        codes.append("2")
    if attrs.get("strike"):
        codes.append("9")
    parts = [f"\x1b[{';'.join(codes)}m"] if codes else []
    if "fg" in attrs:
        r, g, b = _hex_to_rgb(attrs["fg"])
        parts.append(f"\x1b[38;2;{r};{g};{b}m")
    if "bg" in attrs:
        r, g, b = _hex_to_rgb(attrs["bg"])
        parts.append(f"\x1b[48;2;{r};{g};{b}m")
    return "".join(parts)


def _merged(stack: list[dict]) -> dict:
    """样式栈合并：内层覆盖外层同名属性。"""
    merged: dict = {}
    for attrs in stack:
        merged.update(attrs)
    return merged


def render_markup(text: str, color: bool) -> str:
    """markup 文本 → ANSI 字符串（color=True）或剥离标签的纯文本（False）。

    超链接（`[link <url>]...[/]`）：color=True 时输出 OSC 8 序列
    （``\x1b]8;;url\x1b\\ … \x1b]8;;\x1b\\``），终端原生支持 Ctrl+点击打开，
    与终端自动识别 URL 的交互一致；color=False（管道/重定向）时标签剥离，
    文本原样输出，不污染纯文本流。
    """
    out: list[str] = []
    stack: list[dict] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n and text[i + 1] in "[\\":
            out.append(text[i + 1])
            i += 2
            continue
        if ch == "[":
            end = text.find("]", i + 1)
            if end != -1:
                spec = text[i + 1:end]
                if spec == "/":
                    if stack:
                        popped = stack.pop()
                        if color:
                            if popped.get("link"):
                                out.append(_OSC8_CLOSE)  # 先闭合超链接，再恢复样式
                            merged = _merged(stack)
                            out.append(_RESET + (_sgr(merged) if merged else ""))
                    i = end + 1
                    continue
                attrs = _parse_tag(spec)
                if attrs is not None:
                    stack.append(attrs)
                    if color:
                        out.append(_RESET + _sgr(_merged(stack)))
                        link = attrs.get("link")
                        if link:
                            out.append(f"\x1b]8;;{link}\x1b\\")
                    i = end + 1
                    continue
            # 非标签的 [：字面输出（文件名等含方括号场景安全）
            out.append("[")
            i += 1
            continue
        out.append(ch)
        i += 1
    if color and stack:
        if any(a.get("link") for a in stack):
            out.append(_OSC8_CLOSE)  # 未闭合超链接兜底，防泄漏到后续输出
        out.append(_RESET)  # 未闭合标签兜底，防样式泄漏到后续输出
    return "".join(out)


def _enable_vt100(stream: IO[str]) -> None:
    """Windows 控制台启用 ENABLE_VIRTUAL_TERMINAL_PROCESSING（每流一次）。"""
    if sys.platform != "win32":
        return
    try:
        key = stream.fileno()
    except (OSError, AttributeError):
        return
    if key in _vt100_ready:
        return
    _vt100_ready.add(key)
    try:
        import ctypes
        handle = ctypes.windll.kernel32.GetStdHandle(-11 if key == 1 else -12)
        mode = ctypes.c_uint32()
        if ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            ctypes.windll.kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


def supports_color(stream: IO[str]) -> bool:
    """流是否产出 ANSI 颜色：isatty 判定 + NO_COLOR 环境变量尊重。"""
    if os.environ.get("NO_COLOR"):
        return False
    try:
        if not stream.isatty():
            return False
    except Exception:
        return False
    _enable_vt100(stream)
    return True
