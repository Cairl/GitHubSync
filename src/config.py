from rich.style import Style

# ─── Catppuccin Mocha 颜色主题 ───────
STYLE_BOLD      = Style(bold=True)
STYLE_DIM       = Style(dim=True)
STYLE_RED       = Style(color="#F38BA8")
STYLE_GREEN     = Style(color="#A6E3A1")
STYLE_YELLOW    = Style(color="#F9E2AF")
STYLE_BLUE      = Style(color="#89B4FA")
STYLE_GRAY      = Style(color="#6C7086")
STYLE_DEFAULT   = Style()
STYLE_WHITE     = Style(color="#CDD6F4")
STYLE_STRIKE    = Style(strike=True, dim=True)
STYLE_SELECTED  = Style(bgcolor="#CDD6F4", bold=True, color="#11111B")
STYLE_LINK      = Style(color="#89B4FA", underline=True)

# ─── 日志样式 ───────
STYLE_LOG_SUCCESS = Style(color="#A6E3A1", bold=True)
STYLE_LOG_ERROR   = Style(color="#F38BA8", bold=True)
STYLE_LOG_WARN    = Style(color="#F9E2AF", bold=True)
STYLE_LOG_INFO    = Style(color="#89B4FA", bold=True)

LEVEL_STYLES = {
    "ACTION": STYLE_LOG_INFO,
    "DONE": STYLE_LOG_SUCCESS,
    "FAIL": STYLE_LOG_ERROR,
    "NOTE": STYLE_LOG_WARN,
}

LEVEL_LABELS = {
    "ACTION": "正在",
    "DONE": "完成",
    "FAIL": "失败",
    "NOTE": "注意",
}

# ─── 键盘扫描码 ───────
KEY_UP    = b"H"
KEY_DOWN  = b"P"
KEY_LEFT  = b"K"
KEY_RIGHT = b"M"
KEY_ENTER = b"\r"
KEY_ESC   = b"\x1b"
KEY_Q     = b"q"
KEY_O     = b"o"
KEY_TAB   = b"\t"

# ─── 超时设置 ───────
COOLDOWN_PERIOD = 1.0
