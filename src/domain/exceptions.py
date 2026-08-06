"""领域异常体系：统一错误类型，每个异常携带用户可读的中文提示。

替代旧实现中散落的字符串匹配错误翻译（_parse_push_error），
让上层（应用层/表现层）只捕获类型即可决定如何处理。
"""


class SyncError(Exception):
    """同步领域异常基类。message 为用户可读的中文提示。"""

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.message = message
        self.detail = detail

    def __str__(self) -> str:
        return self.message if not self.detail else f"{self.message}: {self.detail}"


class AuthError(SyncError):
    """认证异常：gh 未登录、凭据失效等。"""


class NetworkError(SyncError):
    """网络异常：连接失败、DNS 解析失败、超时等。"""


class RepoNotFoundError(SyncError):
    """仓库不存在或没有访问权限。"""


class PushRejectedError(SyncError):
    """推送被拒绝：远程有更新未同步（non-fast-forward）。"""


class CommandTimeoutError(SyncError):
    """命令执行超时：子进程被强制终止。"""


def classify_push_error(msg: str) -> SyncError:
    """将 git push 原始错误归类为领域异常（替代旧 _parse_push_error 字符串翻译）。

    纯函数，便于单测；上层依据异常类型决定恢复策略。
    """
    m = msg.lower()
    if ("recv failure" in m or "connection" in m or "failed to connect" in m
            or "could not resolve host" in m):
        return NetworkError("网络连接异常，请检查网络或代理设置", msg)
    if "timeout" in m:
        return NetworkError("连接超时，网络可能不稳定", msg)
    if "authentication failed" in m or "403" in m or "401" in m:
        return AuthError("认证异常，请检查 GitHub 登录状态", msg)
    if "repository not found" in m or "does not exist" in m or "404" in m:
        return RepoNotFoundError("仓库不存在或没有访问权限", msg)
    if "schannel" in m or "certificate" in m or "ssl" in m:
        return NetworkError("SSL 证书验证异常，请检查系统根证书或代理设置", msg)
    if "rejected" in m and ("non-fast-forward" in m or "fetch first" in m):
        return PushRejectedError("推送被拒绝，远程仓库有更新未同步", msg)
    if "everything up-to-date" in m:
        return SyncError("无需推送，所有内容已是最新")
    return SyncError(f"未知错误: {msg}", msg)
