import os
import sys

if sys.platform != "win32":
    print("此工具仅支持 Windows 平台。")
    sys.exit(1)

try:
    from rich.console import Console
except ImportError:
    print("请先安装依赖: pip install -r requirements.txt")
    sys.exit(1)

from .app import App


def main():
    if len(sys.argv) > 1:
        potential_path = sys.argv[1]
        if os.path.isdir(potential_path):
            repo_path = potential_path
        else:
            print(f"错误: '{potential_path}' 不是一个有效的文件夹。")
            sys.exit(1)
    else:
        repo_path = os.getcwd()

    app = App(repo_path)
    app.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"\n发生错误: {e}")
