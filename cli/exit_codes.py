"""CLI 退出码约定（脚本化契约）。"""

EXIT_OK = 0        # 成功 / 工作区干净
EXIT_CHANGES = 1   # 检测到待同步变化
EXIT_DIVERGED = 2  # 分叉 / 冲突
EXIT_FAILED = 3    # 操作失败
