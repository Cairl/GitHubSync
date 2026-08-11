"""同步异常体系与推送错误分类。

SyncError 携带面向用户的双语 message 与原始 detail；
classify_push_error 把 git/gh 的英文原始输出归类为具体异常类型。
"""
from __future__ import annotations

from .i18n import tr


class SyncError(Exception):
    """同步操作失败的基类。message 为用户可读文案，detail 为原始输出。"""

    def __init__(self, message: str, detail: str | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail


class PushRejectedError(SyncError):
    """推送被拒绝（非快进）：远程包含本地没有的提交。"""


class RepoNotFoundError(SyncError):
    """远程仓库不存在或无访问权限。"""


class NetworkError(SyncError):
    """网络连接异常。"""


class CommandTimeoutError(SyncError):
    """子进程命令执行超时（归入同步异常体系，TUI/CLI 按 SyncError 统一兜底）。"""


def classify_push_error(detail: str) -> SyncError:
    """把推送失败的原始输出归类为具体异常（大小写不敏感关键词匹配）。"""
    m = (detail or "").lower()
    if "non-fast-forward" in m or "fetch first" in m or "rejected" in m \
            or "failed to push" in m:
        return PushRejectedError(
            tr("推送被拒绝：远程包含本地没有的提交",
               "Push rejected: remote contains commits not present locally"),
            detail)
    if "repository not found" in m or "does not exist" in m or "404" in m:
        return RepoNotFoundError(
            tr("仓库不存在或没有访问权限",
               "Repository not found or access denied"), detail)
    if any(k in m for k in ("recv failure", "connection", "failed to connect",
                            "could not resolve host", "timeout", "timed out")):
        return NetworkError(
            tr("网络连接异常，请检查网络或代理设置",
               "Network error: check your connection or proxy settings"), detail)
    if "authentication failed" in m or "403" in m:
        return SyncError(
            tr("认证异常，请检查 GitHub 登录状态",
               "Authentication failed: check GitHub login status"), detail)
    if "schannel" in m or "certificate" in m or "ssl" in m:
        return SyncError(
            tr("SSL 证书验证异常，请检查系统根证书或代理设置",
               "SSL certificate verification failed"), detail)
    if "everything up-to-date" in m:
        return SyncError(tr("无需推送，所有内容已是最新",
                            "Everything up-to-date"), detail)
    return SyncError(tr(f"推送失败: {detail}", f"Push failed: {detail}"), detail)
