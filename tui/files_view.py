"""文件级展开视图：变化/忽略文件列表，回车切换 include/exclude。

每行文件名后跟一个独立列的操作按钮（垂直对齐）：已忽略文件显示「推送」
（Enter 重新纳入同步），未忽略文件显示「忽略」（Enter 排除同步），
同一按钮的两个状态，Enter 行为与按钮文案一一对应；已忽略文件文件名
加删除线（[strike]）标记。

两种渲染模式：
- render_body 提供（InteractiveApp 整屏重绘）：列表渲染进内容区视图块；
- 缺省：独立 DiffRenderer 块刷新（兼容独立使用与测试）。
"""
from __future__ import annotations

from typing import Callable

from core.config import (COLOR_BRANCH, COLOR_ERROR, COLOR_MENU_ACTIVE_BG,
                         KEY_BACKSPACE, KEY_DOWN, KEY_ENTER, KEY_ESC, KEY_UP)
from core.file_ops_service import FileOpsService
from core.i18n import tr
from core.utils import get_display_width, get_key

from .renderer import DiffRenderer, markup_to_ansi


def _escape_markup(name: str) -> str:
    """文件名转义，防止选中行背景 markup 内被 Rich 误解析。

    只转义反斜杠与左方括号：`\\` 是 Rich 的反斜杠转义符，`[` 是标签
    开始符；孤立的 `]` 不构成标签，无需转义（转义反而会残留反斜杠）。
    """
    return name.replace("\\", "\\\\").replace("[", "\\[")


# 文件名字段最大显示宽度：超长截断，保证按钮列垂直对齐不被顶散
_NAME_COL_MAX = 40


def _truncate(name: str, width: int) -> str:
    """按显示宽度截断文件名，超长以省略号结尾（截断不破坏按钮列对齐）。"""
    if get_display_width(name) <= width:
        return name
    ell = "…"
    budget = width - get_display_width(ell)
    out: list[str] = []
    w = 0
    for ch in name:
        cw = get_display_width(ch)
        if w + cw > budget:
            break
        out.append(ch)
        w += cw
    return "".join(out) + ell


def _render_row(item: dict, selected: bool, name_col: int, btn_w: int,
                push_text: str, ignore_text: str,
                failed: bool = False) -> str:
    """单行 markup：行首状态位 + 文件名（已忽略加删除线）+ 独立按钮列。

    selected: 选中行加 › 光标与 #636363 底色框选（同导航栏）。
    failed: 行首显示红色 [!]（3 宽，替换 3 空格前缀 / ` › ` 光标前缀，
    文件名字段起始列保持 3 不跳动；选中失败行隐藏 › 但保留底色框选）。
    删除线只包文件名本体，padding 与按钮不受影响，列对齐不跳动；
    文件名与按钮之间固定 2 空格分隔；「推送」按钮蓝色（#58A6FF），
    提示其触发同步动作。
    """
    raw_name = _truncate(item["name"], name_col)
    name = _escape_markup(raw_name)
    if item["ignored"]:
        # Rich 带样式 tag 用 [/] 关闭（关闭最近未闭合 tag，选中行内嵌套安全）
        name = f"[strike]{name}[/]"
    pad = name_col - get_display_width(raw_name)
    raw_btn = push_text if item["ignored"] else ignore_text
    btn_pad = btn_w - get_display_width(raw_btn)
    btn = f"[{COLOR_BRANCH}]{raw_btn}[/]" if item["ignored"] else raw_btn
    gap = f"{' ' * pad}  "  # 文件名字段补齐 + 固定 2 空格分隔
    head = f"[{COLOR_ERROR}]\\[!][/]" if failed else (" › " if selected else "   ")
    if selected:
        # 与导航栏光标同款：› 箭头 + #636363 底色框选（左右各冗余 1 格）
        return (f"[bold on {COLOR_MENU_ACTIVE_BG}]"
                f"{head}{name}{gap}{btn}{' ' * btn_pad} [/]")
    return f"{head}{name}{gap}{btn}{' ' * btn_pad} "


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
        self._failed: set[str] = set()  # 操作失败的文件名集合（行首 [!]）

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
            # 按钮列：已忽略 → 「推送」（Enter 纳入同步），未忽略 → 「忽略」（Enter 排除同步）
            push_text = tr("推送", "Push")
            ignore_text = tr("忽略", "Ignore")
            btn_w = max(get_display_width(push_text),
                        get_display_width(ignore_text))
            name_col = min(max(get_display_width(i["name"])
                               for i in items), _NAME_COL_MAX)
            for i, item in enumerate(items):
                markup = _render_row(item, i == index, name_col, btn_w,
                                     push_text, ignore_text,
                                     failed=item["name"] in self._failed)
                lines.append(markup_to_ansi(markup))
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
                    ok = self.file_ops.push_file(item["name"])
                else:
                    ok = self.file_ops.remove_file(item["name"])
                if ok:
                    self._failed.discard(item["name"])
                else:
                    self._failed.add(item["name"])
                dirty = True  # 列表已变化，下一轮重新扫描
