"""Services 容器：组合根组装一次，CLI 与交互模式共用。"""
from __future__ import annotations

from dataclasses import dataclass

from .events import DomainEventBus
from .file_ops_service import FileOpsService
from .protocols import GitProvider, GitHubProvider
from .release_service import ReleaseService
from .restore_service import RestoreService
from .status_service import StatusService
from .sync_service import SyncService


@dataclass
class Services:
    """全部服务与 Provider 的组装结果。"""

    git: GitProvider
    gh: GitHubProvider
    bus: DomainEventBus
    status: StatusService
    sync: SyncService
    restore: RestoreService
    file_ops: FileOpsService
    release: ReleaseService
