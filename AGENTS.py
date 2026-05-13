import os
import msvcrt
import subprocess
import atexit

HIGHLIGHT = "\033[7m"
RESET = "\033[0m"

ARROW_UP = b"H"
ARROW_DOWN = b"P"
ENTER = b"\r"
ESC = b"\x1b"

MENU: list[tuple[str, str]] = [
    ("Claude Code", "claude --dangerously-skip-permissions"),
    ("Gemini CLI", "gemini --yolo"),
    ("Codex CLI", "codex"),
]


def get_key() -> bytes:
    """读取单次按键，正确处理方向键双字节扫描码。"""
    ch = msvcrt.getch()
    if ch in (b"\x00", b"\xe0"):
        return msvcrt.getch()
    return ch


def render_menu(items: list[tuple[str, str]], selected: int, width: int) -> None:
    """清屏并渲染菜单，选中项以反色高亮显示。"""
    os.system("cls")
    print(f"┌{'─' * width}┐")
    for i, (name, _) in enumerate(items):
        line = f"  {name}"
        if selected == i:
            print(f"│{HIGHLIGHT}{line:<{width}}{RESET}│")
        else:
            print(f"│{line:<{width}}│")
    print(f"└{'─' * width}┘")


def main() -> None:
    atexit.register(lambda: print("\033[?25h", end=""))
    print("\033[?25l", end="")

    items = sorted(MENU, key=lambda x: x[0].lower())
    width = max(len(name) for name, _ in items) + 14
    selected = 0
    n = len(items)

    try:
        while True:
            render_menu(items, selected, width)
            key = get_key()

            if key == ARROW_UP:
                selected = (selected - 1) % n
            elif key == ARROW_DOWN:
                selected = (selected + 1) % n
            elif key == ENTER:
                os.system("cls")
                subprocess.call(items[selected][1], shell=True)
                msvcrt.getch()
    except KeyboardInterrupt:
        pass
    finally:
        print("\033[?25h", end="")


if __name__ == "__main__":
    main()
