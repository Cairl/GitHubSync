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

from .application.file_ops_service import FileOpsService
from .application.release_service import ReleaseService
from .application.restore_service import RestoreService
from .application.sync_service import SyncService
from .domain.events import DomainEventBus
from .domain.state import AppState
from .infrastructure.git_provider import GitCLIProvider
from .infrastructure.github_provider import GhCLIProvider
from .presentation.app import App
from .presentation.context import AppContext
from .presentation.modes.push_mode import PushMode
from .presentation.modes.registry import ModeRegistry
from .presentation.modes.restore_mode import RestoreMode
from .presentation.renderer import RichRenderer


def create_app(repo_path: str) -> App:
    """组合根：唯一组装依赖的地方（其余模块均为构造注入）。"""
    bus = DomainEventBus()
    git = GitCLIProvider(repo_path)
    gh = GhCLIProvider(repo_path)
    release = ReleaseService(gh, bus, repo_path)
    sync = SyncService(git, gh, bus, repo_path, release)
    restore = RestoreService(git, bus)
    file_ops = FileOpsService(git, bus, repo_path)
    state = AppState(repo_path)

    registry = ModeRegistry()
    registry.register("推送模式", PushMode)
    registry.register("恢复模式", RestoreMode)
    renderer = RichRenderer(registry.names(), repo_path)

    ctx = AppContext(
        state=state, bus=bus, git=git, gh=gh,
        sync=sync, restore=restore, release=release, file_ops=file_ops,
        renderer=renderer, repo_path=repo_path,
    )
    modes = registry.create_all()
    return App(ctx, modes)


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

    app = create_app(repo_path)
    app.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"\n发生错误: {e}")
