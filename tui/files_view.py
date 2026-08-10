"""文件级展开视图：变化/忽略文件列表，回车切换 include/exclude。

两种渲染模式：
- render_body 提供（InteractiveApp 整屏重绘）：列表渲染进内容区视图块；
- 缺省：独立 DiffRenderer 块刷新（兼容独立使用与测试）。
"""
from __future__ import annotations

from typing import Callable

from core.config import (COLOR_MENU_ACTIVE_BG, KEY_BACKSPACE, KEY_DOWN,
                         KEY_ENTER, KEY_ESC, KEY_UP)
from core.file_ops_service import FileOpsService
from core.i18n import tr
from core.utils import get_key

from .renderer import DiffRenderer, markup_to_ansi


def _escape_markup(name: str) -> str:
    """文件名转义，防止选中行背景 markup 内被 Rich 误解析。

    只转义反斜杠与左方括号：`\\` 是 Rich 的反斜杠转义符，`[` 是标签
    开始符；孤立的 `]` 不构成标签，无需转义（转义反而会残留反斜杠）。
    """
    return name.replace("\\", "\\\\").replace("[", "\\[")


class FilesView:
    """主循环内按 [f] 进入的文件视图；Backspace/Esc 返回主屏。块级差异刷新。"""

    def __init__(self, file_ops: FileOpsService,
                 key_source: Callable[[], bytes] = get_key,
                 out: Callable[[str], None] = print,
                 render_body: Callable[[str | None], None] | None = None):
        self.file_ops = file_ops
        self._key = key_source
        self._out = out
        self._render_body = render_body

    def run(self) -> None:
        block = DiffRenderer(self._out) if self._render_body is None else None
        index = 0
        dirty = True  # 是否需要重新扫描（进入时 / Enter 切换后）
        while True:
            if dirty:
                items = [i for i in self.file_ops.refresh_file_list()
                         if i["action_text"]]
                if not items:
                    if self._render_body is not None:
                        self._render_body(tr("没有文件。", "No files."))
                        self._render_body(None)  # 交还主循环重新生成主屏视图
                    else:
                        self._out(tr("\n没有文件。\n", "\nNo files.\n"))
                    return
                index = max(0, min(index, len(items) - 1))
                dirty = False
            lines: list[str] = []
            for i, item in enumerate(items):
                tag = tr(" [已忽略]", " [ignored]") if item["ignored"] else ""
                if i == index:
                    # 与导航栏光标同款：› 箭头 + #636363 底色框选（左右各冗余 1 格）
                    markup = (f"[bold on {COLOR_MENU_ACTIVE_BG}]"
                              f" › {_escape_markup(item['name'])}{tag} [/]")
                    lines.append(markup_to_ansi(markup))
                else:
                    lines.append(f"   {item['name']}{tag} ")
            text = "\n".join(lines)
            if self._render_body is not None:
                self._render_body(text)
            else:
                block.render(text)
            key = self._key()
            lower = key.lower() if isinstance(key, bytes) else key
            if key == KEY_BACKSPACE or key == KEY_ESC:
                if self._render_body is not None:
                    self._render_body(None)  # 交还主循环重新生成主屏视图
                else:
                    block.clear()
                return
            if key == KEY_UP:
                index = (index - 1) % len(items)
            elif key == KEY_DOWN:
                index = (index + 1) % len(items)
            elif key == KEY_ENTER:
                if self._render_body is None:
                    # 先清块：切换产生的 ActionLog 在下方自然滚动
                    block.clear()
                item = items[index]
                if item["ignored"]:
                    self.file_ops.push_file(item["name"])
                else:
                    self.file_ops.remove_file(item["name"])
                dirty = True  # 列表已变化，下一轮重新扫描
