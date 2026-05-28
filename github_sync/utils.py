import os
import sys
import subprocess
import msvcrt


def enable_vt100():
    os.system("")


def run_command(command, cwd=None):
    try:
        result = subprocess.run(
            command, cwd=cwd, shell=True, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', errors='replace'
        )
        return True, result.stdout.strip()
    except subprocess.CalledProcessError as e:
        msg = (e.stdout.strip() + "\n" + e.stderr.strip()).strip()
        return False, msg


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
        except Exception:
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
        elif char == '\x00' or char == '\xe0':
            msvcrt.getwch()
        else:
            if char.isprintable():
                res.append(char)
                sys.stdout.write(char)
                sys.stdout.flush()
