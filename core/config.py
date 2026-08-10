"""全局常量：语义色（GitHub Primer 配色）、Rich Style、键盘扫描码。

颜色只用于三态语义：成功（绿）、警告（黄）、错误（红），外加次要（灰）
与分支名（蓝）。禁止在代码中硬编码其他颜色。
"""
from __future__ import annotations

from rich.style import Style

# ─── 语义色 ───────
COLOR_SUCCESS = "#3FB950"   # 成功 / 已同步
COLOR_SUCCESS_DIM = "#2EA043"  # 成功降档：推送结果 [✓] 标记（比 COLOR_SUCCESS 暗一档，避免刺眼）
COLOR_WARN = "#F6E2B7"      # 警告 / 有变化（浅米黄）
COLOR_ERROR = "#F85149"     # 错误 / 分叉
COLOR_GRAY = "#8B949E"      # 次要信息
COLOR_URL = "#F6E2B7"       # 主页地址（米黄）
COLOR_LABEL = "#666666"     # 标签（项目/分支/主页 冒号左边）
COLOR_MENU_BG = "#292929"   # 菜单行背景
COLOR_MENU_ACTIVE_BG = "#636363"  # 菜单光标选中项底色框选
COLOR_BRANCH = "#58A6FF"    # 分支名（CLI status 用）
COLOR_BRANCH_NAME = "#CDD6F4"  # 分支名（TUI 顶栏，Catppuccin Mocha 白）
COLOR_CYAN = "#39C5CF"    # 青：本地与远程一致的版本（拉取视图标注）

# ─── Rich Style ───────
STYLE_BOLD = Style(bold=True)
STYLE_DIM = Style(dim=True)
STYLE_GREEN = Style(color=COLOR_SUCCESS)
STYLE_YELLOW = Style(color=COLOR_WARN)
STYLE_RED = Style(color=COLOR_ERROR)
STYLE_GRAY = Style(color=COLOR_GRAY)
STYLE_BLUE = Style(color=COLOR_BRANCH)
STYLE_DEFAULT = Style()

# ─── 键盘扫描码（msvcrt 单键，仅交互模式使用）───────
KEY_UP = b"H"
KEY_DOWN = b"P"
KEY_LEFT = b"K"
KEY_RIGHT = b"M"
KEY_ENTER = b"\r"
KEY_ESC = b"\x1b"
KEY_BACKSPACE = b"\x08"
KEY_O = b"o"
