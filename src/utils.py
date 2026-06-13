import os
import sys
import subprocess
import unicodedata
import msvcrt


def enable_vt100():
    os.system("")


def get_display_width(text):
    return sum(2 if unicodedata.east_asian_width(c) in ('F', 'W') else 1 for c in str(text))


def run_command(command, cwd=None):
    """执行子进程命令。command 可以是字符串（shell=True）或列表（shell=False）。"""
    try:
        result = subprocess.run(
            command, cwd=cwd, shell=not isinstance(command, list), check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', errors='replace'
        )
        return True, result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return False, f"{e.stdout.strip()}\n{e.stderr.strip()}".strip()


def get_key():
    key = msvcrt.getch()
    if key in (b'\xe0', b'\x00'):
        return msvcrt.getch()
    return key


def get_input_with_default(prompt, default_val=""):
    sys.stdout.write(prompt + default_val)
    sys.stdout.flush()

    res = list(default_val)
    while True:
        try:
            char = msvcrt.getwch()
        except (UnicodeDecodeError, OSError):
            continue

        if char == '\r':
            sys.stdout.write('\n')
            return "".join(res)
        elif char == '\x08':
            if res:
                res.pop()
                sys.stdout.write('\b \b')
                sys.stdout.flush()
        elif char == '\x1b':
            sys.stdout.write('\n')
            return ""
        elif char in ('\x00', '\xe0'):
            msvcrt.getwch()
        else:
            if char.isprintable():
                res.append(char)
                sys.stdout.write(char)
                sys.stdout.flush()
