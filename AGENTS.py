import os
import msvcrt
import subprocess
import atexit

MENU = [
    ("Claude Code", "claude --dangerously-skip-permissions"),
    ("Gemini CLI", "gemini --yolo"),
    ("Codex CLI",  "codex"),
]

def main() -> None:
    atexit.register(lambda: print("\033[?25h", end=""))
    print("\033[?25l", end="")

    while True:
        os.system("cls")
        for i, (label, _) in enumerate(MENU, 1):
            print(f"  [{i}] {label}")

        ch = msvcrt.getwch()
        if ch in "123":
            os.system("cls")
            subprocess.call(MENU[int(ch) - 1][1], shell=True)

if __name__ == "__main__":
    main()
