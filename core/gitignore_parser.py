"""完整 gitignore 规范匹配器。

支持：* ? ** 通配、字符类 [...]、! 取反、/ 根锚定、目录专属模式（尾随 /）、
父目录继承（忽略目录即忽略其全部内容）、后规则覆盖先规则。
"""
from __future__ import annotations

import re


class GitignoreMatcher:
    """解析 .gitignore 文本并判断路径是否被忽略。"""

    def __init__(self, text: str):
        self.rules: list[tuple[re.Pattern, bool, bool]] = []
        for raw in text.splitlines():
            line = raw.rstrip()
            if not line or line.startswith("#"):
                continue
            # 转义的前缀 \! \# 视为字面字符
            negated = False
            if line.startswith(("\\!", "\\#")):
                line = line[1:]
            elif line.startswith("!"):
                negated = True
                line = line[1:]
            dir_only = line.endswith("/")
            if dir_only:
                line = line[:-1]
            # 含斜杠（或前导 /）的模式锚定到仓库根，否则匹配任意层级 basename
            anchored = "/" in line
            line = line.lstrip("/")
            if not line:
                continue
            self.rules.append((self._compile(line, anchored), negated, dir_only))

    def is_ignored(self, path: str, is_dir: bool = False) -> bool:
        """判断路径是否被忽略；is_dir 标记路径本身是否为目录。"""
        path = path.replace("\\", "/").strip("/")
        if not path:
            return False
        parts = path.split("/")
        # 候选：完整路径 + 各父级目录前缀（父目录被忽略则内容继承）
        candidates = [(path, is_dir)]
        for i in range(1, len(parts)):
            candidates.append(("/".join(parts[:i]), True))
        ignored = False
        for regex, negated, dir_only in self.rules:
            for candidate, cand_is_dir in candidates:
                if dir_only and not cand_is_dir:
                    continue
                if regex.match(candidate):
                    ignored = not negated
                    break
        return ignored

    @staticmethod
    def _compile(pattern: str, anchored: bool) -> re.Pattern:
        """gitignore glob → 正则。"""
        out: list[str] = []
        i, n = 0, len(pattern)
        while i < n:
            c = pattern[i]
            if c == "*":
                if pattern[i:i + 3] == "**/":
                    out.append("(?:.*/)?")   # **/ 匹配零或多级目录
                    i += 3
                elif pattern[i:i + 2] == "**":
                    out.append(".*")
                    i += 2
                else:
                    out.append("[^/]*")       # * 不跨目录
                    i += 1
            elif c == "?":
                out.append("[^/]")
                i += 1
            elif c == "[":
                j = pattern.find("]", i + 1)
                if j == -1:
                    out.append(re.escape(c))
                    i += 1
                else:
                    out.append(pattern[i:j + 1])
                    i = j + 1
            else:
                out.append(re.escape(c))
                i += 1
        body = "".join(out)
        if anchored:
            return re.compile(f"^{body}$")
        return re.compile(f"(?:^|/){body}$")
