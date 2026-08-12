"""文件标签页：变化/忽略文件列表，Enter 切换 include/exclude。

切入即显示（activate 首次 refresh_file_list，懒加载缓存）；↑/↓ 移动选中，
Enter 切换推送/忽略后返回 ["files"] 由主循环失效重扫（等价旧 dirty 逻辑）。
失败文件行首红色 [!]（_failed 集合跨重扫保留，invalidate 不清）。
"""
from __future__ import annotations

from core.config import (COLOR_BRANCH, COLOR_ERROR, COLOR_MENU_ACTIVE_BG,
                         COLOR_MENU_ACTIVE_FG, COLOR_PLACEHOLDER, KEY_DOWN,
                         KEY_ENTER, KEY_UP)
from core.file_ops_service import FileOpsService
from core.i18n import tr
from core.utils import get_display_width

from .renderer import markup_to_ansi
from .view_base import ViewBase


def _escape_markup(name: str) -> str:
    """文件名转义，防止选中行背景 markup 内被误解析为标签。

    只转义反斜杠与左方括号：`\\` 是 markup 的反斜杠转义符，`[` 是标签
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
        # 带样式 tag 用 [/] 关闭（关闭最近未闭合 tag，选中行内嵌套安全）
        name = f"[strike]{name}[/]"
    pad = name_col - get_display_width(raw_name)
    raw_btn = push_text if item["ignored"] else ignore_text
    btn_pad = btn_w - get_display_width(raw_btn)
    btn = f"[{COLOR_BRANCH}]{raw_btn}[/]" if item["ignored"] else raw_btn
    gap = f"{' ' * pad}  "  # 文件名字段补齐 + 固定 2 空格分隔
    head = f"[{COLOR_ERROR}]\\[!][/]" if failed else (" › " if selected else "   ")
    if selected:
        # 与导航栏光标同款：› 箭头 + #636363 底色框选（左右各冗余 1 格）
        return (f"[bold {COLOR_MENU_ACTIVE_FG} on {COLOR_MENU_ACTIVE_BG}]"
                f"{head}{name}{gap}{btn}{' ' * btn_pad} [/]")
    return f"{head}{name}{gap}{btn}{' ' * btn_pad} "


class FilesView(ViewBase):
    """文件标签页：无循环组件，键处理经 handle_key，渲染经 render。"""

    id = "files"

    def __init__(self, file_ops: FileOpsService):
        super().__init__()
        self.file_ops = file_ops
        self._items: list[dict] = []
        self._index = 0
        self._failed: set[str] = set()  # 操作失败的文件名集合（行首 [!]）

    def _load(self) -> None:
        """重新扫描文件列表（仅保留有操作按钮的项）；光标按长度钳位保留。"""
        self._items = [i for i in self.file_ops.refresh_file_list()
                       if i["action_text"]]
        self._index = max(0, min(self._index, len(self._items) - 1))

    def render(self) -> str:
        if not self._items:
            return markup_to_ansi(  # 无文件占位
                f"[{COLOR_PLACEHOLDER}]none[/]")
        # 按钮列：已忽略 → 「推送」（Enter 纳入同步），未忽略 → 「忽略」（Enter 排除）
        push_text = tr("推送", "Push")
        ignore_text = tr("忽略", "Ignore")
        btn_w = max(get_display_width(push_text),
                    get_display_width(ignore_text))
        name_col = min(max(get_display_width(i["name"])
                           for i in self._items), _NAME_COL_MAX)
        lines: list[str] = []
        for i, item in enumerate(self._items):
            markup = _render_row(item, i == self._index, name_col, btn_w,
                                 push_text, ignore_text,
                                 failed=item["name"] in self._failed)
            lines.append(markup_to_ansi(markup))
        return "\n".join(lines)

    def handle_key(self, key: bytes) -> list[str]:
        if not self._items:
            return []
        if key == KEY_UP:
            self._index = (self._index - 1) % len(self._items)
        elif key == KEY_DOWN:
            self._index = (self._index + 1) % len(self._items)
        elif key == KEY_ENTER:
            item = self._items[self._index]
            if item["ignored"]:
                ok = self.file_ops.push_file(item["name"])
            else:
                ok = self.file_ops.remove_file(item["name"])
            if ok:
                self._failed.discard(item["name"])
            else:
                self._failed.add(item["name"])
            return ["files"]  # 列表已变化，主循环失效重扫
        return []
