"""git push --progress 输出解析：把原始进度行转成紧凑可读文本（纯函数）。

git push 加 --progress 后（stderr 非 tty 也强制输出进度），进度行形如：

    Enumerating objects: 12, done.
    Counting objects: 100% (12/12), done.
    Writing objects: 100% (12/12), 1.20 MiB | 1.10 MiB/s, done.
    Total 12 (delta 0), reused 0 (delta 0), pack-reused 0
    remote: Resolving deltas: 100% (3/3), done.

进度刷新行以 \\r 结尾（同一行覆盖），最终完成行以 \\n 结尾（带 ", done."）。
本模块只提取对用户有意义的进度片段（对象枚举/写入计数），其余噪音（远程
分支提示、delta 统计、URL 等）一律忽略，返回 None 由调用方跳过。
"""
from __future__ import annotations

import re

# 写入对象进度：Writing objects: 100% (12/12), 1.20 MiB | 1.10 MiB/s, done.
_WRITING_RE = re.compile(
    r"Writing objects:\s*(\d+)%\s*\((\d+)/(\d+)\)[, ]*([0-9.]+ [A-Za-z]+)?")
# 枚举对象：Enumerating objects: 12, done.
_ENUMERATING_RE = re.compile(r"Enumerating objects:\s*(\d+)")


def parse_progress(line: str) -> str | None:
    """从一行 push 进度输出提取紧凑进度文本；无进度信息返回 None。

    返回形如 "100% (12/12) · 1.20 MiB" 或 "12 个对象"。只做提取不做 i18n
    （数字与单位通用），供事件总线带 stage 发布后由表现层拼接回显。
    """
    m = _WRITING_RE.search(line)
    if m:
        pct, cur, total = m.group(1), m.group(2), m.group(3)
        speed = m.group(4)
        text = f"{pct}% ({cur}/{total})"
        if speed:
            text += f" · {speed}"
        return text
    m = _ENUMERATING_RE.search(line)
    if m:
        return f"{m.group(1)} objects"
    return None
