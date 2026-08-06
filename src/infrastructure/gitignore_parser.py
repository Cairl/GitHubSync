"""gitignore 规范解析器（替代 app.py 中简化 glob 实现）。

覆盖主流规范：空行/注释、`!` 取反、`/` 锚定（前缀/后缀）、`**` 递归匹配、
`*`/`?`/`[...]` glob、目录通配（结尾 `/`）、反斜杠转义、目录继承忽略。

行为与 git 一致的关键点：目录被忽略则其下所有内容被忽略；
`!` 取反规则按从根到目标的完整路径逐级评估，最后匹配的规则生效。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class _Pattern:
    negated: bool
    dir_only: bool
    anchored: bool
    regex: re.Pattern


def _glob_to_regex(glob: str) -> str:
    """将 gitignore glob 片段转为正则表达式（不含锚定部分）。"""
    out = []
    i = 0
    n = len(glob)
    while i < n:
        ch = glob[i]
        if ch == "\\" and i + 1 < n:
            out.append(re.escape(glob[i + 1]))
            i += 2
        elif ch == "*":
            if i + 1 < n and glob[i + 1] == "*":
                # **：匹配任意层级（含空），转换为 .* 并允许跨 /
                out.append(".*")
                i += 2
                # 处理 **/ 后的分隔符已包含在 .* 中
            else:
                out.append("[^/]*")
                i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        elif ch == "[":
            # 字符类：找到闭合的 ]（支持开头的 ! 或 ^ 取反）
            j = i + 1
            if j < n and glob[j] in "!^":
                j += 1
            if j < n and glob[j] == "]":
                j += 1
            while j < n and glob[j] != "]":
                j += 1
            if j < n:
                cls = glob[i + 1 : j]
                if cls.startswith("!"):
                    cls = "^" + cls[1:]
                out.append("[" + cls + "]")
                i = j + 1
            else:
                out.append(re.escape(ch))
                i += 1
        else:
            out.append(re.escape(ch))
            i += 1
    return "".join(out)


def parse_gitignore(text: str) -> list[_Pattern]:
    """解析 .gitignore 内容为规则列表。"""
    patterns: list[_Pattern] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        # 去掉未转义的尾部空白（gitignore 规范：尾部空格被忽略，除非转义）
        line = re.sub(r"(?<!\\)\s+$", "", line)
        if not line or line.startswith("#"):
            continue

        negated = False
        if line.startswith("!"):
            negated = True
            line = line[1:]
            if not line:
                continue

        dir_only = False
        if line.endswith("/"):
            dir_only = True
            line = line[:-1]
        if not line:
            continue

        # 锚定判断：前导 / 或模式中出现未转义的 / 则锚定到仓库根
        anchored = False
        if line.startswith("/"):
            anchored = True
            line = line[1:]
        elif "/" in line:
            anchored = True
        core = _glob_to_regex(line)
        if anchored:
            regex = re.compile("^" + core + "$")
        else:
            # 非锚定：可匹配任意层级的片段
            regex = re.compile(r"(?:^|/)" + core + "$")
        patterns.append(_Pattern(negated, dir_only, anchored, regex))
    return patterns


class GitignoreMatcher:
    """按 git 语义评估 rel_path 是否被忽略。"""

    def __init__(self, text: str = ""):
        self._patterns = parse_gitignore(text) if text else []

    def is_ignored(self, rel_path: str, is_dir: bool = False) -> bool:
        """评估相对路径（POSIX 分隔符）是否被忽略。

        逐级前缀评估：目录被忽略则内部全部忽略；! 取反在更深的级别可重新生效。
        """
        path = rel_path.replace("\\", "/").strip("/")
        if not path:
            return False
        parts = path.split("/")
        ignored = False
        for i in range(1, len(parts) + 1):
            prefix = "/".join(parts[:i])
            prefix_is_dir = (i < len(parts)) or is_dir
            for pat in self._patterns:
                if pat.dir_only and not prefix_is_dir:
                    continue
                if pat.regex.search(prefix) if not pat.anchored else pat.regex.match(prefix):
                    ignored = not pat.negated
        return ignored
